from abc import ABC, abstractmethod
from typing import Tuple, Optional, Any, Dict, Type
import json
import hmac
import hashlib


class NotificationChannel(ABC):
    """Base interface for all notification channels.

    Each channel adapter knows how to build both plain notification payloads
    and interactive approval card payloads, verify incoming callbacks, and
    parse callback payloads. Adapters are channel-specific but transport-agnostic:
    the caller is responsible for HTTP delivery.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Canonical channel slug, e.g. 'slack', 'email'."""
        pass

    @abstractmethod
    def supports_interactive(self) -> bool:
        """Return True if this channel can render inline approve/reject buttons."""
        pass

    @abstractmethod
    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        """Construct a one-way notification payload (no buttons).

        Args:
            subject: Short notification title.
            body: HTML or formatted body text.
            action_url: Optional link to view the full record in the web app.
            text_body: Optional plain-text variant.
            context: Optional extra context (form_data, etc.).
        """
        pass

    @abstractmethod
    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        """Construct an interactive approval card payload.

        Args:
            step_id: Identifier of the step being approved.
            description: Human-readable description of the approval request.
            callback_url: URL the platform should call back to.
            context: Optional extra context (form_data, etc.).
        """
        pass

    @abstractmethod
    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        """Verify the signature/token from an incoming platform webhook request."""
        pass

    @abstractmethod
    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        """Parse the webhook callback payload.

        Returns:
            Tuple[str, str, Optional[str]]: (step_id, decision, comment)
        """
        pass


class EmailAdapter(NotificationChannel):
    """Email adapter for plain notifications and link-based approvals.

    Email is "interactive" in the sense that approve/reject links can be clicked,
    but there are no inline buttons inside the message client. Verification and
    parsing of link callbacks are handled by the caller/API layer using signed
    tokens; this adapter only formats the payload.
    """

    @property
    def name(self) -> str:
        return "email"

    def supports_interactive(self) -> bool:
        return True

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        return {
            "type": "email",
            "subject": subject,
            "html": body,
            "action_url": action_url,
        }

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        approve_url = f"{callback_url}/approve"
        reject_url = f"{callback_url}/reject"
        html = f"""
        <h2>{title}</h2>
        <p>Please review and choose an action:</p>
        <p>
            <a href="{approve_url}" style="display:inline-block;padding:10px 20px;background:#16a34a;color:#fff;text-decoration:none;border-radius:4px;">Approve</a>
            &nbsp;
            <a href="{reject_url}" style="display:inline-block;padding:10px 20px;background:#dc2626;color:#fff;text-decoration:none;border-radius:4px;">Reject</a>
        </p>
        """
        return {
            "type": "email",
            "subject": title,
            "html": html,
            "approve_url": approve_url,
            "reject_url": reject_url,
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Email link callbacks use signed tokens verified by the API layer.
        return True

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        step_id = payload.get("step_id")
        decision = payload.get("decision")
        comment = payload.get("comment")
        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in email callback payload")
        return str(step_id), str(decision), comment


class SlackAdapter(NotificationChannel):
    """Slack Block Kit Adapter.

    Handles outbound Block Kit payloads, incoming Slack HMAC-SHA256 signature
    verification, and block_actions callback payload parsing.
    """

    @property
    def name(self) -> str:
        return "slack"

    def supports_interactive(self) -> bool:
        return True

    def _context_blocks(self, context: Optional[dict]) -> list:
        context_blocks = []
        if context and "form_data" in context:
            fields = []
            for k, v in context["form_data"].items():
                fields.append({"type": "mrkdwn", "text": f"*{k}:* {v}"})
            if fields:
                # Slack allows max 10 fields in a section block, chunk to be safe
                context_blocks.append({"type": "section", "fields": fields[:10]})
        return context_blocks

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": subject, "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ]
        blocks.extend(self._context_blocks(context))
        if action_url:
            blocks.append({
                "type": "actions",
                "block_id": "notification_actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View", "emoji": True},
                        "url": action_url,
                        "action_id": "open_view",
                    }
                ],
            })
        return {"text": subject, "blocks": blocks}

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Approval Request", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
        ]
        blocks.extend(self._context_blocks(context))
        blocks.append({
            "type": "actions",
            "block_id": f"approval_actions_{step_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                    "style": "primary",
                    "value": json.dumps({"step_id": step_id, "decision": "approve"}),
                    "action_id": "slack_approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject", "emoji": True},
                    "style": "danger",
                    "value": json.dumps({"step_id": step_id, "decision": "reject"}),
                    "action_id": "slack_reject",
                },
            ],
        })
        return {"text": title, "blocks": blocks}

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Slack signature verification: https://api.slack.com/authentication/verifying-requests-from-slack
        timestamp = headers.get("X-Slack-Request-Timestamp")
        signature = headers.get("X-Slack-Signature")
        if not timestamp or not signature:
            return False

        sig_basestring = f"v0:{timestamp}:".encode("utf-8") + body_bytes
        computed_hash = hmac.new(secret.encode("utf-8"), sig_basestring, hashlib.sha256).hexdigest()
        computed_signature = f"v0={computed_hash}"
        return hmac.compare_digest(computed_signature, signature)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        if "payload" in payload:
            data = json.loads(payload["payload"])
        else:
            data = payload

        actions = data.get("actions", [])
        if not actions:
            raise ValueError("No actions block in Slack callback")

        action_val = json.loads(actions[0].get("value", "{}"))
        step_id = action_val.get("step_id")
        decision = action_val.get("decision")
        comment = data.get("submission", {}).get("comment") or None

        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in Slack actions payload")

        return str(step_id), str(decision), comment


class TeamsAdapter(NotificationChannel):
    """Microsoft Teams Adaptive Cards Adapter."""

    @property
    def name(self) -> str:
        return "teams"

    def supports_interactive(self) -> bool:
        return True

    def _body_widgets(self, title: str, context: Optional[dict]) -> list:
        widgets = [
            {"type": "TextBlock", "text": title, "size": "large", "weight": "bolder", "color": "accent"},
        ]
        if context and "form_data" in context:
            fact_list = []
            for k, v in context["form_data"].items():
                fact_list.append({"title": str(k), "value": str(v)})
            if fact_list:
                widgets.append({"type": "FactSet", "facts": fact_list})
        return widgets

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        widgets = self._body_widgets(subject, context)
        widgets.append({"type": "TextBlock", "text": body, "wrap": True})
        actions = []
        if action_url:
            actions.append({"type": "Action.OpenUrl", "title": "View", "url": action_url})
        card_content = {"type": "AdaptiveCard", "version": "1.4", "body": widgets, "actions": actions}
        return {
            "type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card_content}],
        }

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required: {step_id}"
        widgets = self._body_widgets(title, context)
        card_content = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": widgets,
            "actions": [
                {"type": "Action.Execute", "title": "Approve", "verb": "approve", "data": {"step_id": step_id, "decision": "approve"}},
                {"type": "Action.Execute", "title": "Reject", "verb": "reject", "data": {"step_id": step_id, "decision": "reject"}},
            ],
        }
        return {
            "type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card_content}],
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        signature = headers.get("X-Teams-Signature") or headers.get("Authorization")
        if not signature:
            return False
        expected_sig = signature.replace("Bearer ", "").strip()
        computed_hash = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed_hash, expected_sig)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        action = payload.get("action", {})
        data = action.get("data", {})
        step_id = data.get("step_id")
        decision = data.get("decision") or action.get("verb")
        comment = data.get("comment")
        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in MS Teams callback")
        return str(step_id), str(decision), comment


class LarkAdapter(NotificationChannel):
    """Lark (Feishu) Interactive Card Adapter."""

    @property
    def name(self) -> str:
        return "lark"

    def supports_interactive(self) -> bool:
        return True

    def _elements(self, title: str, context: Optional[dict]) -> list:
        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{title}**"}},
        ]
        if context and "form_data" in context:
            fields = []
            for k, v in context["form_data"].items():
                fields.append({"is_short": True, "text": {"tag": "lark_md", "content": f"**{k}:** {v}"}})
            if fields:
                elements.append({"tag": "div", "fields": fields})
        return elements

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        elements = self._elements(subject, context)
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": body}})
        if action_url:
            elements.append({
                "tag": "action",
                "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": "View"}, "type": "primary", "url": action_url}
                ],
            })
        return {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": subject}},
            "elements": elements,
        }

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required: {step_id}"
        elements = self._elements(title, context)
        elements.append({
            "tag": "action",
            "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "Approve"}, "type": "primary", "value": {"step_id": step_id, "decision": "approve"}},
                {"tag": "button", "text": {"tag": "plain_text", "content": "Reject"}, "type": "danger", "value": {"step_id": step_id, "decision": "reject"}},
            ],
        })
        return {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"tag": "plain_text", "content": "Approval Required"}},
            "elements": elements,
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        timestamp = headers.get("X-Lark-Request-Timestamp")
        nonce = headers.get("X-Lark-Request-Nonce")
        signature = headers.get("X-Lark-Signature")
        if not timestamp or not nonce or not signature:
            return False
        sig_bytes = timestamp.encode("utf-8") + nonce.encode("utf-8") + secret.encode("utf-8") + body_bytes
        computed_hash = hashlib.sha256(sig_bytes).hexdigest()
        return hmac.compare_digest(computed_hash, signature)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        if payload.get("type") == "url_verification":
            return "", "challenge", payload.get("challenge")
        action = payload.get("action", {})
        value = action.get("value", {})
        step_id = value.get("step_id")
        decision = value.get("decision")
        comment = payload.get("comment") or None
        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in Lark callback payload")
        return str(step_id), str(decision), comment


class TelegramAdapter(NotificationChannel):
    """Telegram Bot Callback Adapter."""

    @property
    def name(self) -> str:
        return "telegram"

    def supports_interactive(self) -> bool:
        return True

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        text = f"<b>{subject}</b>\n\n{body}"
        keyboard = []
        if action_url:
            keyboard.append([{"text": "View", "url": action_url}])
        return {
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": keyboard} if keyboard else {},
        }

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        text = f"<b>Approval Required</b>\n\n{title}"
        if context and "form_data" in context:
            text += "\n\n<b>Details:</b>"
            for k, v in context["form_data"].items():
                text += f"\n• <b>{k}:</b> {v}"
        inline_keyboard = [
            [
                {"text": "Approve ✅", "callback_data": json.dumps({"step_id": step_id, "decision": "approve"})},
                {"text": "Reject ❌", "callback_data": json.dumps({"step_id": step_id, "decision": "reject"})},
            ]
        ]
        return {"text": text, "parse_mode": "HTML", "reply_markup": {"inline_keyboard": inline_keyboard}}

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        token = headers.get("X-Telegram-Bot-Api-Secret-Token")
        if token:
            return hmac.compare_digest(token, secret)
        return False

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        callback_query = payload.get("callback_query")
        if not callback_query:
            raise ValueError("No callback_query in Telegram payload")
        callback_data = callback_query.get("data", "")
        try:
            data = json.loads(callback_data)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid Telegram callback_data JSON: {callback_data}")
        step_id = data.get("step_id")
        decision = data.get("decision")
        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in Telegram callback_data")
        return str(step_id), str(decision), None


class WhatsAppAdapter(NotificationChannel):
    """WhatsApp Cloud API Interactive Message Adapter."""

    @property
    def name(self) -> str:
        return "whatsapp"

    def supports_interactive(self) -> bool:
        # WhatsApp supports reply buttons, but they are limited (3 buttons, 20-char titles).
        return True

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        body_text = f"{subject}\n\n{body}"[:1024]
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "text",
            "text": {"body": body_text},
        }

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required: {step_id}"
        body_text = f"Approval Required:\n{title}"
        if context and "form_data" in context:
            body_text += "\n"
            for k, v in context["form_data"].items():
                body_text += f"\n{k}: {v}"
        body_text = body_text[:1024]
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": f"approve:{step_id}", "title": "Approve"}},
                        {"type": "reply", "reply": {"id": f"reject:{step_id}", "title": "Reject"}},
                    ]
                },
            },
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        signature = headers.get("X-Hub-Signature-256")
        if not signature or not signature.startswith("sha256="):
            return False
        expected_sig = signature.split("sha256=")[1]
        computed_hash = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed_hash, expected_sig)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        if "hub.mode" in payload and "hub.challenge" in payload:
            return "", "challenge", payload.get("hub.challenge")
        try:
            entry = payload["entry"][0]
            changes = entry["changes"][0]
            value = changes["value"]
            message = value["messages"][0]
            interactive = message["interactive"]
            button_reply = interactive["button_reply"]
            reply_id = button_reply["id"]
        except (KeyError, IndexError):
            raise ValueError("Payload is not a valid WhatsApp interactive button reply")
        if ":" not in reply_id:
            raise ValueError(f"Invalid WhatsApp reply_id format: {reply_id}")
        decision, step_id = reply_id.split(":", 1)
        return str(step_id), str(decision), None


class GoogleChatAdapter(NotificationChannel):
    """Google Chat Cards V2 Adapter."""

    @property
    def name(self) -> str:
        return "google_chat"

    def supports_interactive(self) -> bool:
        return True

    def _widgets(self, title: str, body: Optional[str], context: Optional[dict]) -> list:
        widgets = [{"textParagraph": {"text": f"<b>{title}</b>"}}]
        if body:
            widgets.append({"textParagraph": {"text": body}})
        if context and "form_data" in context:
            facts = []
            for k, v in context["form_data"].items():
                facts.append(f"<b>{k}:</b> {v}")
            if facts:
                widgets.append({"textParagraph": {"text": "<br>".join(facts)}})
        return widgets

    def build_notification_payload(
        self,
        subject: str,
        body: str,
        action_url: Optional[str] = None,
        text_body: Optional[str] = None,
        context: Optional[dict] = None,
    ) -> dict:
        widgets = self._widgets(subject, body, context)
        buttons = []
        if action_url:
            buttons.append({
                "text": "View",
                "onClick": {"openLink": {"url": action_url}},
            })
        if buttons:
            widgets.append({"buttonList": {"buttons": buttons}})
        return {
            "cardsV2": [
                {
                    "cardId": "notification_card",
                    "card": {
                        "header": {"title": subject},
                        "sections": [{"widgets": widgets}],
                    },
                }
            ]
        }

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None,
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        widgets = self._widgets(title, None, context)
        widgets.append({
            "buttonList": {
                "buttons": [
                    {
                        "text": "Approve",
                        "color": {"red": 0.18, "green": 0.49, "blue": 0.20, "alpha": 1.0},
                        "onClick": {
                            "action": {
                                "actionMethodName": "approve",
                                "parameters": [
                                    {"key": "step_id", "value": step_id},
                                    {"key": "decision", "value": "approve"},
                                ],
                            }
                        },
                    },
                    {
                        "text": "Reject",
                        "color": {"red": 0.83, "green": 0.18, "blue": 0.18, "alpha": 1.0},
                        "onClick": {
                            "action": {
                                "actionMethodName": "reject",
                                "parameters": [
                                    {"key": "step_id", "value": step_id},
                                    {"key": "decision", "value": "reject"},
                                ],
                            }
                        },
                    },
                ]
            }
        })
        return {
            "cardsV2": [
                {
                    "cardId": f"approval_card_{step_id}",
                    "card": {
                        "header": {"title": "Approval System", "subtitle": "Workflow Step Request"},
                        "sections": [{"widgets": widgets}],
                    },
                }
            ]
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        auth = headers.get("Authorization") or headers.get("X-Google-Chat-Token")
        if not auth:
            return False
        token = auth.replace("Bearer ", "").strip()
        return hmac.compare_digest(token, secret)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        action = payload.get("action", {})
        parameters = action.get("parameters", [])
        step_id = None
        decision = None
        for p in parameters:
            if p.get("key") == "step_id":
                step_id = p.get("value")
            elif p.get("key") == "decision":
                decision = p.get("value")
        if not step_id or not decision:
            decision = action.get("actionMethodName")
            step_id = payload.get("commonSystemArguments", {}).get("step_id")
        if not step_id or not decision:
            raise ValueError("Could not parse step_id or decision in Google Chat callback payload")
        return str(step_id), str(decision), None


CHANNEL_REGISTRY: Dict[str, Type[NotificationChannel]] = {
    adapter().name: adapter
    for adapter in [
        EmailAdapter,
        SlackAdapter,
        TeamsAdapter,
        LarkAdapter,
        TelegramAdapter,
        WhatsAppAdapter,
        GoogleChatAdapter,
    ]
}


def get_channel_adapter(channel: str) -> Optional[NotificationChannel]:
    """Return an instantiated adapter for the given channel slug, or None."""
    cls = CHANNEL_REGISTRY.get(channel)
    return cls() if cls else None

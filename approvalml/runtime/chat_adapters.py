from abc import ABC, abstractmethod
from typing import Tuple, Optional, Any
import json
import hmac
import hashlib

class InteractiveChannel(ABC):
    @abstractmethod
    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        """Construct the platform-specific card JSON or message payload."""
        pass

    @abstractmethod
    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        """Verify the signature/token from the incoming platform webhook request."""
        pass

    @abstractmethod
    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        """Parse the webhook callback payload.

        Returns:
            Tuple[str, str, Optional[str]]: (step_id, decision, comment)
        """
        pass


class SlackAdapter(InteractiveChannel):
    """Slack Block Kit Adapter.

    Handles outbound Block Kit payloads, incoming Slack HMAC-SHA256 signature
    verification, and block_actions callback payload parsing.
    """

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        
        # Include context fields if provided
        context_blocks = []
        if context and "form_data" in context:
            fields = []
            for k, v in context["form_data"].items():
                fields.append({"type": "mrkdwn", "text": f"*{k}:* {v}"})
            if fields:
                # Slack allows max 10 fields in a section block, chunk to be safe
                context_blocks.append({
                    "type": "section",
                    "fields": fields[:10]
                })

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Approval Request",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{title}*"
                }
            }
        ]
        
        blocks.extend(context_blocks)
        
        blocks.append({
            "type": "actions",
            "block_id": f"approval_actions_{step_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve",
                        "emoji": True
                    },
                    "style": "primary",
                    "value": json.dumps({"step_id": step_id, "decision": "approve"}),
                    "action_id": "slack_approve"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Reject",
                        "emoji": True
                    },
                    "style": "danger",
                    "value": json.dumps({"step_id": step_id, "decision": "reject"}),
                    "action_id": "slack_reject"
                }
            ]
        })

        return {"text": title, "blocks": blocks}

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Slack signature verification: https://api.slack.com/authentication/verifying-requests-from-slack
        timestamp = headers.get("X-Slack-Request-Timestamp")
        signature = headers.get("X-Slack-Signature")
        if not timestamp or not signature:
            return False

        # Build the signature basestring
        sig_basestring = f"v0:{timestamp}:".encode("utf-8") + body_bytes
        computed_hash = hmac.new(
            secret.encode("utf-8"),
            sig_basestring,
            hashlib.sha256
        ).hexdigest()
        computed_signature = f"v0={computed_hash}"

        return hmac.compare_digest(computed_signature, signature)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        # Slack sends payloads under 'payload' form variable in raw string format
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


class TeamsAdapter(InteractiveChannel):
    """Microsoft Teams Adaptive Cards Adapter.

    Handles outbound Adaptive Card payloads, incoming webhook HTTP header token
    verification, and Action.Execute callback payload parsing.
    """

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        title = description or f"Approval required: {step_id}"
        
        body_widgets = [
            {
                "type": "TextBlock",
                "text": "Approval Required",
                "size": "large",
                "weight": "bolder",
                "color": "accent"
            },
            {
                "type": "TextBlock",
                "text": title,
                "wrap": True,
                "size": "medium"
            }
        ]

        if context and "form_data" in context:
            fact_list = []
            for k, v in context["form_data"].items():
                fact_list.append({"title": str(k), "value": str(v)})
            if fact_list:
                body_widgets.append({
                    "type": "FactSet",
                    "facts": fact_list
                })

        card_content = {
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": body_widgets,
            "actions": [
                {
                    "type": "Action.Execute",
                    "title": "Approve",
                    "verb": "approve",
                    "data": {
                        "step_id": step_id,
                        "decision": "approve"
                    }
                },
                {
                    "type": "Action.Execute",
                    "title": "Reject",
                    "verb": "reject",
                    "data": {
                        "step_id": step_id,
                        "decision": "reject"
                    }
                }
            ]
        }

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card_content
                }
            ]
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Standard HMAC-SHA256 signature verification over incoming payload
        signature = headers.get("X-Teams-Signature") or headers.get("Authorization")
        if not signature:
            return False

        # Support Bearer token prefix or raw signature string
        expected_sig = signature.replace("Bearer ", "").strip()
        computed_hash = hmac.new(
            secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed_hash, expected_sig)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        action = payload.get("action", {})
        verb = action.get("verb")
        data = action.get("data", {})
        
        step_id = data.get("step_id")
        decision = data.get("decision") or verb
        comment = data.get("comment")

        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in MS Teams callback")

        return str(step_id), str(decision), comment


class LarkAdapter(InteractiveChannel):
    """Lark (Feishu) Interactive Card Adapter.

    Handles outbound Lark Cards, URL challenge verification,
    and inbound signature verification and parsing.
    """

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        title = description or f"Approval required: {step_id}"
        
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{title}**"
                }
            }
        ]

        if context and "form_data" in context:
            fields = []
            for k, v in context["form_data"].items():
                fields.append({
                    "is_short": True,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{k}:** {v}"
                    }
                })
            if fields:
                elements.append({
                    "tag": "div",
                    "fields": fields
                })

        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Approve"
                    },
                    "type": "primary",
                    "value": {
                        "step_id": step_id,
                        "decision": "approve"
                    }
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "Reject"
                    },
                    "type": "danger",
                    "value": {
                        "step_id": step_id,
                        "decision": "reject"
                    }
                }
            ]
        })

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": "Approval Required"
                }
            },
            "elements": elements
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Lark webhook signature verification:
        # https://open.larksuite.com/document/ukTMukTMukTM/uYDNxYjLycTM24yM3EjN/event-subscription-configure-/signature-encryption-and-verification
        timestamp = headers.get("X-Lark-Request-Timestamp")
        nonce = headers.get("X-Lark-Request-Nonce")
        signature = headers.get("X-Lark-Signature")
        
        if not timestamp or not nonce or not signature:
            return False

        # basestring = timestamp + nonce + secret + body
        sig_bytes = timestamp.encode("utf-8") + nonce.encode("utf-8") + secret.encode("utf-8") + body_bytes
        computed_hash = hashlib.sha256(sig_bytes).hexdigest()

        return hmac.compare_digest(computed_hash, signature)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        # Handle URL verification challenge dynamically
        if payload.get("type") == "url_verification":
            # Standalone receiver can handle this check during router setup
            return "", "challenge", payload.get("challenge")

        action = payload.get("action", {})
        value = action.get("value", {})
        
        step_id = value.get("step_id")
        decision = value.get("decision")
        comment = payload.get("comment") or None

        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in Lark callback payload")

        return str(step_id), str(decision), comment


class TelegramAdapter(InteractiveChannel):
    """Telegram Bot Callback Adapter.

    Handles outbound HTML inline-keyboard payloads, token verification,
    and callback_query parsing.
    """

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        
        text = f"<b>Approval Required</b>\n\n{title}"
        if context and "form_data" in context:
            text += "\n\n<b>Details:</b>"
            for k, v in context["form_data"].items():
                text += f"\n• <b>{k}:</b> {v}"

        inline_keyboard = [
            [
                {
                    "text": "Approve ✅",
                    "callback_data": json.dumps({"step_id": step_id, "decision": "approve"})
                },
                {
                    "text": "Reject ❌",
                    "callback_data": json.dumps({"step_id": step_id, "decision": "reject"})
                }
            ]
        ]

        return {
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": inline_keyboard
            }
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Standard token check: Telegram bot token is configured as the webhook query token.
        # e.g., POST /webhook/telegram?token=SECRET
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
        comment = None  # Telegram callback queries don't support comment fields natively

        if not step_id or not decision:
            raise ValueError("Missing step_id or decision in Telegram callback_data")

        return str(step_id), str(decision), comment


class WhatsAppAdapter(InteractiveChannel):
    """WhatsApp Cloud API Interactive Message Adapter.

    Handles outbound Reply Button JSON payloads, webhook verification challenges,
    and webhook notification parsing.
    """

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        title = description or f"Approval required: {step_id}"
        
        # WhatsApp limits interactive button bodies to 1024 characters
        body_text = f"Approval Required:\n{title}"
        if context and "form_data" in context:
            body_text += "\n"
            for k, v in context["form_data"].items():
                body_text += f"\n{k}: {v}"
        
        body_text = body_text[:1024]

        # WhatsApp buttons are limited to 3 options, button IDs must be unique strings
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {
                    "text": body_text
                },
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"approve:{step_id}",
                                "title": "Approve"
                            }
                        },
                        {
                            "type": "reply",
                            "reply": {
                                "id": f"reject:{step_id}",
                                "title": "Reject"
                            }
                        }
                    ]
                }
            }
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # WhatsApp uses X-Hub-Signature-256 (sha256=HMAC-SHA256(secret, body))
        signature = headers.get("X-Hub-Signature-256")
        if not signature or not signature.startswith("sha256="):
            return False

        expected_sig = signature.split("sha256=")[1]
        computed_hash = hmac.new(
            secret.encode("utf-8"),
            body_bytes,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed_hash, expected_sig)

    def parse_callback(self, payload: dict) -> Tuple[str, str, Optional[str]]:
        # Verification endpoint challenge resolution helper
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

        # reply_id has format 'decision:step_id'
        if ":" not in reply_id:
            raise ValueError(f"Invalid WhatsApp reply_id format: {reply_id}")

        decision, step_id = reply_id.split(":", 1)
        return str(step_id), str(decision), None


class GoogleChatAdapter(InteractiveChannel):
    """Google Chat Cards V2 Adapter.

    Handles outbound CardsV2 payloads, signature/token verification,
    and widget action callback parsing.
    """

    def build_approval_payload(
        self,
        step_id: str,
        description: str,
        callback_url: str,
        context: Optional[dict] = None
    ) -> dict:
        title = description or f"Approval required for step: {step_id}"
        
        widgets = [
            {
                "textParagraph": {
                    "text": f"<b>Approval Required</b><br>{title}"
                }
            }
        ]

        if context and "form_data" in context:
            facts = []
            for k, v in context["form_data"].items():
                facts.append(f"<b>{k}:</b> {v}")
            if facts:
                widgets.append({
                    "textParagraph": {
                        "text": "<br>".join(facts)
                    }
                })

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
                                    {"key": "decision", "value": "approve"}
                                ]
                            }
                        }
                    },
                    {
                        "text": "Reject",
                        "color": {"red": 0.83, "green": 0.18, "blue": 0.18, "alpha": 1.0},
                        "onClick": {
                            "action": {
                                "actionMethodName": "reject",
                                "parameters": [
                                    {"key": "step_id", "value": step_id},
                                    {"key": "decision", "value": "reject"}
                                ]
                            }
                        }
                    }
                ]
            }
        })

        return {
            "cardsV2": [
                {
                    "cardId": f"approval_card_{step_id}",
                    "card": {
                        "header": {
                            "title": "Approval System",
                            "subtitle": "Workflow Step Request"
                        },
                        "sections": [
                            {
                                "widgets": widgets
                            }
                        ]
                    }
                }
            ]
        }

    def verify_request(self, headers: dict, body_bytes: bytes, secret: str) -> bool:
        # Standard token check for custom Google Chat webhook targets.
        # Google Chat webhooks usually have a verify token query param.
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
            # Fallback to actionMethodName
            decision = action.get("actionMethodName")
            # Scan common structures
            step_id = payload.get("commonSystemArguments", {}).get("step_id")
            
        if not step_id or not decision:
            raise ValueError("Could not parse step_id or decision in Google Chat callback payload")

        return str(step_id), str(decision), None

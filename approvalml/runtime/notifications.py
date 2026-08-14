"""
Channel-agnostic notification dispatcher.

Uses the adapters in chat_adapters.py to build platform-specific payloads and
delivers them via HTTP. The dispatcher is stateless and database-free; callers
provide the recipient configuration.
"""

from typing import Optional, Tuple, Any
import json
import logging

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None

from .chat_adapters import CHANNEL_REGISTRY, NotificationChannel, get_channel_adapter

logger = logging.getLogger(__name__)


# Field types that cannot be actioned inline in a chat message.
_NON_INLINE_FIELD_TYPES = {
    "file_upload",
    "signature",
    "richtext",
    "markdown",
    "line_items",
    "autocomplete",
}


def workflow_supports_inline_approval(workflow_definition: dict) -> bool:
    """
    Determine whether a workflow is simple enough to render inline approve/reject
    buttons inside a chat notification.

    Mirrors the SaaS helper so the standalone runtime can make the same decision.
    """
    workflow_section = workflow_definition.get("workflow", {})
    settings = workflow_section.get("settings", {})
    if not settings.get("inline_approval_in_chat"):
        return False

    layout = workflow_definition.get("form", {}).get("layout", {})
    sections = layout.get("sections", [])
    if len(sections) > 1:
        return False

    fields = workflow_definition.get("form", {}).get("fields", [])
    visible_field_names = set()
    for section in sections:
        for grid in section.get("grid", []):
            if isinstance(grid, list):
                for cell in grid:
                    if isinstance(cell, str):
                        visible_field_names.add(cell)
                    elif isinstance(cell, list):
                        visible_field_names.update(cell)

    for field in fields:
        if field.get("name") not in visible_field_names:
            continue
        if field.get("type") in _NON_INLINE_FIELD_TYPES:
            return False
        hidden = field.get("hidden")
        # Only permanently hidden fields are skipped; conditional hidden may still show.
        if hidden is True or field.get("type") == "hidden":
            continue
        for step_def in workflow_section.values():
            if not isinstance(step_def, dict):
                continue
            edit_sections = step_def.get("edit_sections", [])
            if field.get("name") in step_def.get("edit_fields", []):
                return False
            if visible_field_names.intersection(set(edit_sections or [])):
                return False

    return True


class NotificationDispatcher:
    """
    Dispatch plain notifications through registered channel adapters.

    Each channel's `recipient_config` is adapter-specific:

      - email: {"address": "user@example.com"}  # caller should handle email transport
      - slack: {"bot_token": "xoxb-...", "channel": "#approvals"} or {"bot_token": "...", "user_id": "U123"}
      - teams: {"webhook_url": "https://..."}
      - lark: {"webhook_url": "https://..."}
      - telegram: {"bot_token": "...", "chat_id": "..."}
      - whatsapp: {"phone_number_id": "...", "access_token": "...", "recipient": "..."}
      - google_chat: {"webhook_url": "https://..."}

    Returns (success: bool, error_message: Optional[str]) for each send.
    """

    def __init__(self, http_client: Optional[Any] = None):
        self._http = http_client

    def _client(self):
        if self._http is not None:
            return self._http
        if httpx is None:
            raise RuntimeError("httpx is required to send chat notifications")
        return httpx.AsyncClient(timeout=30.0)

    async def send_notification(
        self,
        channel: str,
        recipient_config: dict,
        message: dict,
    ) -> Tuple[bool, Optional[str]]:
        """Send a plain notification through the named channel.

        Args:
            channel: Channel slug, e.g. 'email', 'slack'.
            recipient_config: Channel-specific configuration.
            message: Dict with subject, body, optional text_body, action_url, context.

        Returns:
            (success, error_message)
        """
        adapter_cls = CHANNEL_REGISTRY.get(channel)
        if not adapter_cls:
            return False, f"Unknown notification channel: {channel}"

        adapter = adapter_cls()
        payload = adapter.build_notification_payload(**message)
        return await self._deliver_payload(channel, recipient_config, payload)

    async def _deliver_payload(
        self,
        channel: str,
        config: dict,
        payload: dict,
    ) -> Tuple[bool, Optional[str]]:
        if channel == "email":
            # Email transport is handled by the caller (EmailService or standalone SMTP).
            return True, None

        client = self._client()
        try:
            if channel == "slack":
                return await self._send_slack(client, config, payload)
            if channel == "teams":
                return await self._send_webhook(client, config.get("webhook_url"), payload)
            if channel == "lark":
                return await self._send_webhook(client, config.get("webhook_url"), payload)
            if channel == "telegram":
                return await self._send_telegram(client, config, payload)
            if channel == "whatsapp":
                return await self._send_whatsapp(client, config, payload)
            if channel == "google_chat":
                return await self._send_webhook(client, config.get("webhook_url"), payload)
            return False, f"Delivery not implemented for channel: {channel}"
        except Exception as e:
            logger.warning(f"Failed to send {channel} notification: {e}")
            return False, str(e)

    async def _send_slack(self, client, config: dict, payload: dict) -> Tuple[bool, Optional[str]]:
        token = config.get("bot_token")
        channel = config.get("channel") or config.get("user_id")
        if not token or not channel:
            return False, "Slack config requires bot_token and channel or user_id"

        body = {
            "channel": channel,
            "text": payload.get("text", ""),
            "blocks": payload.get("blocks", []),
        }
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
        )
        data = response.json()
        if not data.get("ok"):
            return False, f"Slack API error: {data.get('error')}"
        return True, None

    async def _send_webhook(self, client, webhook_url: Optional[str], payload: dict) -> Tuple[bool, Optional[str]]:
        if not webhook_url:
            return False, "Missing webhook_url"
        response = await client.post(webhook_url, json=payload)
        response.raise_for_status()
        return True, None

    async def _send_telegram(self, client, config: dict, payload: dict) -> Tuple[bool, Optional[str]]:
        token = config.get("bot_token")
        chat_id = config.get("chat_id")
        if not token or not chat_id:
            return False, "Telegram config requires bot_token and chat_id"

        body = {
            "chat_id": chat_id,
            "text": payload.get("text", ""),
            "parse_mode": payload.get("parse_mode", "HTML"),
        }
        reply_markup = payload.get("reply_markup")
        if reply_markup:
            body["reply_markup"] = json.dumps(reply_markup)

        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=body,
        )
        data = response.json()
        if not data.get("ok"):
            return False, f"Telegram API error: {data.get('description')}"
        return True, None

    async def _send_whatsapp(self, client, config: dict, payload: dict) -> Tuple[bool, Optional[str]]:
        phone_number_id = config.get("phone_number_id")
        access_token = config.get("access_token")
        recipient = config.get("recipient")
        if not phone_number_id or not access_token or not recipient:
            return False, "WhatsApp config requires phone_number_id, access_token, and recipient"

        body = dict(payload)
        body["to"] = recipient
        response = await client.post(
            f"https://graph.facebook.com/v18.0/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json=body,
        )
        response.raise_for_status()
        return True, None

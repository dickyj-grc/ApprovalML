"""
Environment-backed notification backend for the standalone ApprovalML runtime.

Reads channel credentials from ``APPROVALML_NOTIFICATION_*`` environment variables
and dispatches non-email notifications through the channel adapters in
``chat_adapters.py``. Email notifications are delegated to the configured SMTP
sender so the same mail transport is used for both approvals and notifications.

Environment variables used:

- Email (via SMTP): ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``,
  ``SMTP_PASSWORD``, ``EMAIL_FROM`` (same as ``SmtpEmailSender``).
- Slack: ``APPROVALML_NOTIFICATION_SLACK_BOT_TOKEN``
- Teams: ``APPROVALML_NOTIFICATION_TEAMS_WEBHOOK_URL``
- Lark: ``APPROVALML_NOTIFICATION_LARK_WEBHOOK_URL``
- Telegram: ``APPROVALML_NOTIFICATION_TELEGRAM_BOT_TOKEN``
- WhatsApp: ``APPROVALML_NOTIFICATION_WHATSAPP_PHONE_NUMBER_ID`` and
  ``APPROVALML_NOTIFICATION_WHATSAPP_ACCESS_TOKEN``
- Google Chat: ``APPROVALML_NOTIFICATION_GOOGLE_CHAT_WEBHOOK_URL``
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .base import NotificationBackend
from .notifications import NotificationDispatcher


class EnvNotificationBackend(NotificationBackend):
    """
    Standalone notification backend that sources credentials from environment
    variables.

    Args:
        email_sender: Optional email sender used for the ``email`` channel. If
            omitted, email notifications are silently skipped when SMTP is not
            configured.
        http_client: Optional async HTTP client used by the chat adapters.
    """

    def __init__(
        self,
        email_sender: Optional[Any] = None,
        http_client: Optional[Any] = None,
    ) -> None:
        self.email_sender = email_sender
        self.dispatcher = NotificationDispatcher(http_client=http_client)

    async def send(
        self,
        *,
        channel: str,
        recipient: str,
        message: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        Send one notification using environment-derived credentials.

        For email, ``recipient`` is the destination address. For chat channels,
        it is the channel-specific target (Slack channel/user, Telegram chat id,
        WhatsApp phone number, etc.). Webhook-based channels read the URL from
        the environment; ``recipient`` may be left empty for those channels.
        """
        if channel == "email":
            return await self._send_email(recipient, message)

        config = self._channel_config(channel, recipient)
        if config is None:
            return False, f"No credentials configured for notification channel: {channel}"

        return await self.dispatcher.send_notification(
            channel=channel,
            recipient_config=config,
            message=message,
        )

    async def _send_email(
        self,
        recipient: str,
        message: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        if not self.email_sender:
            return False, "No email sender configured for notification step"

        if not recipient or "@" not in recipient:
            return False, f"Invalid email recipient: {recipient}"

        try:
            self.email_sender.send_notification(
                to_email=recipient,
                subject=message.get("subject", "Notification"),
                body=message.get("body", ""),
                text_body=message.get("text_body"),
            )
            return True, None
        except Exception as e:
            return False, str(e)

    def _channel_config(
        self,
        channel: str,
        recipient: str,
    ) -> Optional[dict[str, Any]]:
        """Build a channel-specific config dict from environment variables."""
        if channel == "slack":
            token = os.environ.get("APPROVALML_NOTIFICATION_SLACK_BOT_TOKEN")
            if not token:
                return None
            cfg: dict[str, Any] = {"bot_token": token}
            if recipient.startswith("U") or recipient.startswith("@"):
                cfg["user_id"] = recipient.lstrip("@")
            else:
                cfg["channel"] = recipient
            return cfg

        if channel == "teams":
            url = os.environ.get("APPROVALML_NOTIFICATION_TEAMS_WEBHOOK_URL")
            if not url:
                return None
            return {"webhook_url": url}

        if channel == "lark":
            url = os.environ.get("APPROVALML_NOTIFICATION_LARK_WEBHOOK_URL")
            if not url:
                return None
            return {"webhook_url": url}

        if channel == "telegram":
            token = os.environ.get("APPROVALML_NOTIFICATION_TELEGRAM_BOT_TOKEN")
            if not token:
                return None
            return {"bot_token": token, "chat_id": recipient}

        if channel == "whatsapp":
            phone_id = os.environ.get("APPROVALML_NOTIFICATION_WHATSAPP_PHONE_NUMBER_ID")
            access_token = os.environ.get("APPROVALML_NOTIFICATION_WHATSAPP_ACCESS_TOKEN")
            if not phone_id or not access_token:
                return None
            return {
                "phone_number_id": phone_id,
                "access_token": access_token,
                "recipient": recipient,
            }

        if channel == "google_chat":
            url = os.environ.get("APPROVALML_NOTIFICATION_GOOGLE_CHAT_WEBHOOK_URL")
            if not url:
                return None
            return {"webhook_url": url}

        return None

"""
SMTP implementation of EmailSender.

Reads configuration from environment variables. Falls back to printing the
email content to stdout when SMTP is not configured — useful for local dev
and CI where you want to see the email but not actually send it.
"""

from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from .base import EmailSender


class SmtpEmailSender(EmailSender):
    """Send approval emails via SMTP, with a stdout fallback when unconfigured."""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_pass: Optional[str] = None,
        from_addr: Optional[str] = None,
        from_name: Optional[str] = None,
    ) -> None:
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "")
        self.smtp_port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
        self.smtp_pass = smtp_pass or os.environ.get("SMTP_PASSWORD", "")
        self.from_addr = from_addr or os.environ.get("EMAIL_FROM", "approvalml@localhost")
        self.from_name = from_name or os.environ.get("EMAIL_FROM_NAME", "ApprovalML")

    # ── EmailSender implementation ────────────────────────────────────────────

    def send_approval_request(
        self,
        to_email: str,
        description: str,
        approve_url: str,
        reject_url: str,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        subject = f"Approval Required: {description[:80]}"
        text_body = self._text_body(description, approve_url, reject_url, context)
        html_body = self._html_body(description, approve_url, reject_url, context)

        if not self.smtp_host or not self.smtp_user:
            self._stdout_fallback(to_email, subject, text_body)
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.from_addr}>"
        msg["To"] = to_email
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if self.smtp_user and self.smtp_pass:
                    smtp.login(self.smtp_user, self.smtp_pass)
                smtp.sendmail(self.from_addr, [to_email], msg.as_string())
        except Exception as exc:
            print(f"[ApprovalML] SMTP send failed to {to_email}: {exc}")
            self._stdout_fallback(to_email, subject, text_body)

    # ── private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _stdout_fallback(to_email: str, subject: str, body: str) -> None:
        print(f"\n{'─' * 60}")
        print("[ApprovalML — SMTP not configured, printing email to stdout]")
        print(f"To:      {to_email}")
        print(f"Subject: {subject}")
        print(body)
        print(f"{'─' * 60}\n")

    @staticmethod
    def _context_lines(context: Optional[dict[str, Any]]) -> str:
        if not context:
            return ""
        lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
        return f"\n\nContext:\n{lines}"

    @staticmethod
    def _context_html(context: Optional[dict[str, Any]]) -> str:
        if not context:
            return ""
        rows = "".join(
            f"<tr><td style='padding:4px 8px;color:#555'><code>{k}</code></td>"
            f"<td style='padding:4px 8px'>{v}</td></tr>"
            for k, v in context.items()
        )
        return (
            "<table style='border-collapse:collapse;margin:12px 0'>"
            f"{rows}</table>"
        )

    def _text_body(self, description, approve_url, reject_url, context) -> str:
        return f"""You have been asked to review and approve the following request.

{description}{self._context_lines(context)}

── APPROVE ──────────────────────────────────────────────
{approve_url}

── REJECT ───────────────────────────────────────────────
{reject_url}

─────────────────────────────────────────────────────────
Sent by ApprovalML. Do not reply to this email.
"""

    def _html_body(self, description, approve_url, reject_url, context) -> str:
        return f"""<!doctype html>
<html><body style="font-family:sans-serif;max-width:600px;margin:32px auto;color:#111">
<h2 style="color:#1a1a2e;margin-bottom:4px">Approval Required</h2>
<p style="font-size:16px;margin-top:0">{description}</p>
{self._context_html(context)}
<div style="margin:28px 0;display:flex;gap:12px">
  <a href="{approve_url}"
     style="background:#16a34a;color:#fff;padding:12px 28px;border-radius:6px;
            text-decoration:none;font-weight:600;font-size:15px">
    ✅ Approve
  </a>
  <a href="{reject_url}"
     style="background:#dc2626;color:#fff;padding:12px 28px;border-radius:6px;
            text-decoration:none;font-weight:600;font-size:15px">
    ❌ Reject
  </a>
</div>
<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
<p style="font-size:12px;color:#9ca3af">
  Sent by <strong>ApprovalML</strong> — if you were not expecting this, ignore it.
</p>
</body></html>"""

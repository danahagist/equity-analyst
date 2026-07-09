"""End-of-run email delivery (stdlib ``smtplib`` — no external dependency).

For the self-triggered weekly pipeline: after the committee + levels finish,
email the reports to Dana. Credentials come from the environment (see
``SMTPConfig``); with Gmail, use an App Password, not the account password.

Kept provider-agnostic: any SMTP host works. This never runs unless SMTP is
configured, and it attaches the report files rather than inlining them so the
formatting survives.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

from equity_analyst.config import SMTPConfig


class EmailNotConfigured(RuntimeError):
    """Raised when an email send is requested but SMTP settings are incomplete."""


def build_message(
    smtp: SMTPConfig, *, subject: str, body: str, attachments: list[Path] | None = None
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp.sender
    message["To"] = ", ".join(smtp.recipients)
    message.set_content(body)
    for path in attachments or []:
        data = path.read_bytes()
        subtype = "markdown" if path.suffix.lower() == ".md" else "plain"
        message.add_attachment(
            data, maintype="text", subtype=subtype, filename=path.name
        )
    return message


def send_email(
    smtp: SMTPConfig | None,
    *,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> None:
    """Send the run email via SMTP (STARTTLS). Raises if SMTP isn't configured."""
    if smtp is None or not smtp.configured:
        raise EmailNotConfigured(
            "SMTP is not configured — set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, and "
            "SMTP_TO in .env (Gmail: use an App Password). See docs/GETTING_STARTED.md."
        )
    message = build_message(smtp, subject=subject, body=body, attachments=attachments)
    with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
        server.starttls()
        server.login(smtp.username, smtp.password)
        server.send_message(message)

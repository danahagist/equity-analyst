"""Email notifier tests (message construction + config gating; no real SMTP)."""

from __future__ import annotations

import pytest

from equity_analyst.config import SMTPConfig
from equity_analyst.notify import EmailNotConfigured, build_message, send_email


def _smtp(**over):
    base = dict(host="smtp.example.com", port=587, username="u@example.com",
                password="pw", sender="u@example.com", recipients=("dana@example.com",))
    base.update(over)
    return SMTPConfig(**base)


def test_configured_property() -> None:
    assert _smtp().configured
    assert not _smtp(host="").configured
    assert not _smtp(recipients=()).configured


def test_build_message_with_attachment(tmp_path) -> None:
    report = tmp_path / "AAPL-2026-07-08.md"
    report.write_text("# report", encoding="utf-8")
    msg = build_message(_smtp(), subject="Weekly", body="see attached",
                        attachments=[report])
    assert msg["Subject"] == "Weekly"
    assert msg["To"] == "dana@example.com"
    attachments = [p for p in msg.iter_attachments()]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "AAPL-2026-07-08.md"


def test_send_email_requires_configuration() -> None:
    with pytest.raises(EmailNotConfigured, match="SMTP is not configured"):
        send_email(None, subject="x", body="y")
    with pytest.raises(EmailNotConfigured):
        send_email(_smtp(password=""), subject="x", body="y")

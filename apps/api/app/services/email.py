"""Email delivery — the bot's final hand-off step.

Gmail SMTP (stopgap for testing/early sends; swap for SES/Postmark later). When
TEST_RECIPIENT is set, every send is redirected there regardless of the requested
address — the guardrail that keeps "just testing" from ever reaching a real agent.
"""
from __future__ import annotations

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.config import Settings, get_settings


class Emailer:
    def __init__(self, settings: Settings | None = None):
        self.cfg = settings or get_settings()

    def send(self, to: str, subject: str, body: str,
             links: dict[str, str] | None = None,
             attachment: Path | None = None) -> str:
        recipient = self.cfg.test_recipient or to
        msg = MIMEMultipart()
        msg["From"] = f"Premier Home Tours <{self.cfg.email_from}>"
        msg["To"] = recipient
        msg["Subject"] = subject

        full = body
        for label, url in (links or {}).items():
            full += f"\n\n{label}: {url}"
        if self.cfg.test_recipient and self.cfg.test_recipient != to:
            full += f"\n\n[TEST MODE] originally addressed to: {to}"
        msg.attach(MIMEText(full, "plain"))

        if attachment and Path(attachment).exists():
            part = MIMEBase("application", "octet-stream")
            part.set_payload(Path(attachment).read_bytes())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            f'attachment; filename="{Path(attachment).name}"')
            msg.attach(part)

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:
            s.starttls()
            s.login(self.cfg.email_smtp_user, self.cfg.email_smtp_pass)
            s.send_message(msg)
        return recipient

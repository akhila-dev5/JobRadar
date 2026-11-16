"""Optional email notifications over SMTP.

Credentials come only from environment variables (use an app password or a
provider SMTP credential, never your normal mailbox password).
The SMTP class is injectable so tests never open a network connection.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage

from backend.app.core.config import Settings
from backend.app.models import Job

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    pass


def build_digest(jobs: list[Job]) -> tuple[str, str]:
    subject = f"JobRadar AI: {len(jobs)} new matching job{'s' if len(jobs) != 1 else ''}"
    lines = []
    for job in sorted(jobs, key=lambda j: j.match.score if j.match else 0, reverse=True):
        score = f"{job.match.score:.0f}%" if job.match else "n/a"
        lines.append(
            f"- {job.title} at {job.company_name} ({job.location or 'location n/a'})\n"
            f"  Match score: {score}\n  Apply: {job.application_url}"
        )
    body = "New jobs matching your keywords:\n\n" + "\n\n".join(lines)
    body += "\n\nScores rank relevance only; they are not a hiring probability."
    return subject, body


class EmailNotifier:
    def __init__(self, settings: Settings, smtp_factory: Callable[..., smtplib.SMTP] | None = None):
        self.settings = settings
        self._smtp_factory = smtp_factory or smtplib.SMTP

    @property
    def configured(self) -> bool:
        return self.settings.smtp_configured

    def send(self, to: str, subject: str, body: str) -> None:
        s = self.settings
        if not s.smtp_configured:
            raise NotificationError(
                "SMTP is not configured. Set SMTP_HOST and SMTP_FROM (and credentials) in .env."
            )
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
        msg.set_content(body)
        try:
            with self._smtp_factory(s.smtp_host, s.smtp_port, timeout=20) as server:
                if s.smtp_use_tls:
                    server.starttls(context=ssl.create_default_context())
                if s.smtp_username:
                    server.login(s.smtp_username, s.smtp_password)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationError(f"Email could not be sent: {exc}") from exc

    def send_digest(self, to: str, jobs: list[Job]) -> None:
        subject, body = build_digest(jobs)
        self.send(to, subject, body)

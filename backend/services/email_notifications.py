"""Optional SMTP completion notifications."""

import smtplib
from email.message import EmailMessage
from typing import Any

from backend.settings import settings


def email_is_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_job_notification(
    recipient: str,
    job_id: str,
    *,
    clips: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    if not email_is_configured():
        return

    message = EmailMessage()
    message["Subject"] = "Your AI Clipper job is ready" if clips else "Your AI Clipper job failed"
    message["From"] = settings.smtp_from
    message["To"] = recipient
    if clips:
        lines = ["Your clips are ready to download:", ""]
        for clip in clips:
            url = f"{settings.public_api_origin.rstrip('/')}{clip['url']}"
            lines.append(f"- {clip['title']}: {url}")
        body = "\n".join(lines)
    else:
        body = (
            "Your AI Clipper job could not be completed.\n\n"
            f"Job ID: {job_id}\n"
            f"Details: {error or 'Processing failed.'}"
        )
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)

"""Owner notifications and invite emails over SMTP (optional).

Plain text only. Every header value has CR and LF removed, so a name such as
"Eve\r\nBcc: x@example.com" cannot add headers. Sending runs in a thread and never raises:
a broken mail setup is logged, and the admin page still shows everything.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import ssl
from datetime import UTC, datetime
from email.message import EmailMessage

from loguru import logger

from ..config import SmtpSettings
from .db import AccessRequest

SMTP_TIMEOUT_SECONDS = 15
_LINE_BREAKS = re.compile(r"[\r\n\u2028\u2029]+")


def clean_header(value: str) -> str:
    return _LINE_BREAKS.sub(" ", value).strip()[:300]


def build_message(sender: str, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = clean_header(sender)
    msg["To"] = clean_header(to)
    msg["Subject"] = clean_header(subject)
    msg.set_content(body)
    return msg


def new_request_email(req: AccessRequest, admin_url: str) -> tuple[str, str]:
    subject = f"Openfolio Cloud: access request from {req.name}"
    lines = [
        "A new access request is waiting for you.",
        "",
        f"Name:       {req.name}",
        f"Email:      {req.email}",
        f"Portfolio:  {req.portfolio_url}",
        f"Does:       {req.about}",
    ]
    if req.reason:
        lines += ["", "Why they want it:", req.reason]
    lines += ["", f"Approve or reject it at {admin_url}"]
    return subject, "\n".join(lines) + "\n"


def _first(name: str) -> str:
    return name.split()[0] if name.split() else "there"


def invite_email(name: str, link: str, expires_at: int) -> tuple[str, str]:
    expires = datetime.fromtimestamp(expires_at, UTC).strftime("%d %B %Y")
    body = (
        f"Hi {_first(name)},\n\n"
        "You're approved for the Openfolio Cloud beta.\n\n"
        f"Create your account with this personal link (works once, until {expires}):\n{link}\n\n"
        "Then upload your résumé and a photo, and the Studio drafts your AI version for you to review.\n\n"
        "If you didn't ask for this, you can ignore this email.\n"
    )
    return "You're approved for Openfolio Cloud", body


def reset_email(name: str, link: str) -> tuple[str, str]:
    body = (
        f"Hi {_first(name)},\n\n"
        "Someone asked to reset the password of your Openfolio Cloud account.\n\n"
        f"Choose a new password with this link (works once, for one hour):\n{link}\n\n"
        "If it wasn't you, ignore this email; your password stays the same.\n"
    )
    return "Reset your Openfolio Cloud password", body


def review_email(name: str, approved: bool, note: str, page_url: str, studio_url: str) -> tuple[str, str]:
    if approved:
        subject = "Your Openfolio page is live"
        text = (
            f"Good news: your AI portfolio is approved and live at\n{page_url}\n\n"
            f"Your embed snippet is in the Studio: {studio_url}\n"
        )
    else:
        subject = "Your Openfolio page needs a few changes"
        text = (
            "Your AI portfolio isn't live yet. Please make a few changes in the Studio and submit it again:\n"
            f"{studio_url}\n"
        )
    if note:
        text += f"\nNote from the reviewer:\n{note}\n"
    return subject, f"Hi {_first(name)},\n\n{text}"


class Mailer:
    def __init__(self, smtp: SmtpSettings | None) -> None:
        self.smtp = smtp

    @property
    def enabled(self) -> bool:
        return self.smtp is not None

    @property
    def notify_email(self) -> str | None:
        return self.smtp.notify_email if self.smtp else None

    async def send(self, to: str, subject: str, body: str) -> bool:
        """Send one plain-text email. Returns False (and logs why) instead of raising."""
        if not self.smtp:
            return False
        try:
            await asyncio.to_thread(self._send, self.smtp, build_message(self.smtp.sender, to, subject, body))
        except Exception as e:
            # The address is personal data and the exception text can echo server replies; log the type only.
            logger.error(f"Email failed ({type(e).__name__}); the admin page still has everything")
            return False
        return True

    @staticmethod
    def _send(smtp: SmtpSettings, msg: EmailMessage) -> None:
        context = ssl.create_default_context()
        client: smtplib.SMTP
        if smtp.port == 465:
            client = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
        else:
            client = smtplib.SMTP(smtp.host, smtp.port, timeout=SMTP_TIMEOUT_SECONDS)
        with client:
            if smtp.port != 465:
                client.starttls(context=context)  # never send the password in the clear
            if smtp.user and smtp.password:
                client.login(smtp.user, smtp.password)
            client.send_message(msg)

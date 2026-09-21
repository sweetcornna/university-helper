"""Blocking SMTP sender.

Everything here is synchronous ``smtplib``; async callers must wrap
``send_email`` in ``asyncio.to_thread`` so a slow or hung SMTP server never
blocks the event loop.

All ``smtplib``/socket failures are wrapped in :class:`MailerError`. The SMTP
password is never included in an exception message or a log record.
"""

from __future__ import annotations

import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.config import settings

logger = logging.getLogger(__name__)

# Cap on how long a single connect/send may take. Without it a hung SMTP peer
# pins the worker thread forever (send_email runs via asyncio.to_thread).
_SMTP_TIMEOUT_SECONDS = 10


class MailerError(Exception):
    """Outbound mail could not be delivered."""


def is_configured() -> bool:
    """True when the minimum SMTP settings for sending are present."""
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _build_message(to: str, subject: str, html: str, text: str | None) -> EmailMessage:
    message = EmailMessage()
    # formataddr + EmailMessage header encoding gives an RFC 2047 encoded-word
    # for the Chinese display name and the CJK subject, so clients render them
    # correctly instead of showing mojibake.
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM))
    message["To"] = to
    message["Subject"] = subject
    # Always ship a plain-text alternative: some clients (and most spam
    # filters) treat HTML-only mail as suspicious.
    message.set_content(text or _html_to_text(html))
    message.add_alternative(html, subtype="html")
    return message


def _html_to_text(html: str) -> str:
    """Very small fallback used only when the caller passes no text part."""
    stripped = re.sub(r"<[^>]+>", " ", html)
    return " ".join(stripped.split())


def send_email(to: str, subject: str, html: str, text: str | None = None) -> None:
    """Send one message. BLOCKING — call via ``asyncio.to_thread``.

    Raises :class:`MailerError` on any configuration or delivery failure.
    """
    if not is_configured():
        raise MailerError("SMTP is not configured (SMTP_HOST / SMTP_FROM missing)")

    message = _build_message(to, subject, html, text)

    try:
        if settings.SMTP_SSL:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
                _login_and_send(smtp, message)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=_SMTP_TIMEOUT_SECONDS) as smtp:
                smtp.starttls()
                _login_and_send(smtp, message)
    except MailerError:
        raise
    except Exception as exc:
        # str(exc) on smtplib errors carries the server reply, never our
        # credentials — but keep the wrapped message generic regardless.
        logger.error("SMTP delivery failed: %s", type(exc).__name__, exc_info=True)
        raise MailerError("邮件发送失败，请稍后再试") from exc


def _login_and_send(smtp: smtplib.SMTP, message: EmailMessage) -> None:
    if settings.SMTP_USER:
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    smtp.send_message(message)

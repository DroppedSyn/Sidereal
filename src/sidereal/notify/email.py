"""SMTP email channel (M28, plan O10): one plain-text mail per batch via stdlib ``smtplib``
(STARTTLS on ``smtp_port``, or implicit TLS with ``smtp_ssl``), certificate checked with the
default SSL context. This is the only module allowed to import ``smtplib`` (static rules).

Header injection: the subject and addresses are single lines (CR, LF and other control
characters removed) before they reach ``EmailMessage``. The SMTP password comes from the
secrets loader and appears nowhere but the ``login`` call.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from sidereal.config import NotifySettings
from sidereal.notify.base import Notice, NotifyError
from sidereal.textclean import truncate
from sidereal.urls import is_http_url

TIMEOUT_S = 30.0
MAX_SUBJECT = 200
WHY_CHARS = 600
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u0085  ]+")


def header_line(text: str, limit: int = MAX_SUBJECT) -> str:
    """One header-safe line: CR/LF and other control characters become spaces."""
    return truncate(" ".join(_CONTROL.sub(" ", text).split()), limit)


def body_text(notices: list[Notice], *, heading: str) -> str:
    parts = [heading, ""]
    for n in notices:
        parts.append(f"* {header_line(n.title, 300)}")
        if n.sources:
            parts.append(f"  Source: {header_line(', '.join(n.sources), 300)}")
        if n.why:
            parts.append(f"  Why: {header_line(truncate(n.why, WHY_CHARS), WHY_CHARS + 10)}")
        if n.url and is_http_url(n.url):
            parts.append(f"  {header_line(n.url, 2000)}")
        parts.append("")
    return "\n".join(parts)


def build_message(cfg: NotifySettings, notices: list[Notice], *, subject: str,
                  heading: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = header_line(subject)
    msg["From"] = header_line(cfg.smtp_from, 300)
    msg["To"] = ", ".join(header_line(a, 300) for a in cfg.smtp_to)
    msg["Date"] = formatdate(localtime=False, usegmt=True)
    msg["Message-ID"] = make_msgid(domain="sidereal.local")
    msg.set_content(body_text(notices, heading=heading))
    return msg


class EmailChannel:
    name = "email"

    def __init__(self, cfg: NotifySettings, password: str, *,
                 smtp: Callable[..., smtplib.SMTP] | None = None,
                 smtp_ssl: Callable[..., smtplib.SMTP] | None = None) -> None:
        if not cfg.smtp_host or not cfg.smtp_from or not cfg.smtp_to:
            raise NotifyError("email: set notify.smtp_host, smtp_from and smtp_to")
        if cfg.smtp_user and not password:
            raise NotifyError("email: SIDEREAL_SMTP_PASSWORD is not set")
        self._cfg = cfg
        self._password = password
        self._smtp = smtp or smtplib.SMTP
        self._smtp_ssl = smtp_ssl or smtplib.SMTP_SSL

    def __repr__(self) -> str:
        return f"EmailChannel(host={self._cfg.smtp_host!r})"

    def _send_sync(self, msg: EmailMessage) -> None:
        cfg = self._cfg
        context = ssl.create_default_context()
        if cfg.smtp_ssl:
            conn = self._smtp_ssl(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT_S,
                                  context=context)
        else:
            conn = self._smtp(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT_S)
        with conn:
            if not cfg.smtp_ssl:
                conn.starttls(context=context)
            if cfg.smtp_user:
                conn.login(cfg.smtp_user, self._password)
            conn.send_message(msg)

    async def send(self, notices: list[Notice], *, heading: str) -> None:
        msg = build_message(self._cfg, notices, subject=heading, heading=heading)
        try:
            await asyncio.to_thread(self._send_sync, msg)
        except smtplib.SMTPResponseException as exc:  # server text may echo input: code only
            raise NotifyError(f"email: {type(exc).__name__} {exc.smtp_code}") from None
        except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
            raise NotifyError(f"email: {type(exc).__name__}") from None

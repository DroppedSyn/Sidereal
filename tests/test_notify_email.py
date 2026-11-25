"""notify/email.py (M28): SMTP through a fake ``smtplib.SMTP``, header safety, no secrets in
errors."""

from __future__ import annotations

import smtplib
import ssl

import pytest

from sidereal.config import NotifySettings
from sidereal.notify.base import Notice, NotifyError
from sidereal.notify.email import EmailChannel, body_text, build_message, header_line
from tests.notify_helpers import PASSWORD, FakeSMTP

CFG = NotifySettings(channels=["email"], smtp_host="smtp.example.net", smtp_port=587,
                     smtp_user="me@example.net", smtp_from="Sidereal <me@example.net>",
                     smtp_to=["me@example.net"])
N = Notice(story_id=1, title="Patch now", url="https://news.example/1",
           sources=("MSRC", "KEV"), why="Exploited.")


@pytest.fixture(autouse=True)
def _reset():
    FakeSMTP.reset()
    yield
    FakeSMTP.reset()


def channel(cfg: NotifySettings = CFG, password: str = PASSWORD) -> EmailChannel:
    return EmailChannel(cfg, password, smtp=FakeSMTP, smtp_ssl=FakeSMTP)


async def test_starttls_login_send():
    await channel().send([N], heading="Sidereal: 1 new TOP story")
    (smtp,) = FakeSMTP.instances
    assert (smtp.host, smtp.port, smtp.context) == ("smtp.example.net", 587, None)
    assert [c[0] for c in smtp.calls] == ["starttls", "login", "send", "quit"]
    assert isinstance(smtp.calls[0][1], ssl.SSLContext)
    assert smtp.calls[0][1].verify_mode == ssl.CERT_REQUIRED
    assert smtp.calls[1][1] == ("me@example.net", PASSWORD)
    msg = smtp.messages[0]
    assert msg["Subject"] == "Sidereal: 1 new TOP story"
    assert msg.get_content_type() == "text/plain"
    body = msg.get_content()
    assert "Patch now" in body and "MSRC, KEV" in body and "https://news.example/1" in body
    assert PASSWORD not in msg.as_string()


async def test_implicit_tls_skips_starttls():
    cfg = CFG.model_copy(update={"smtp_ssl": True, "smtp_port": 465})
    await channel(cfg).send([N], heading="h")
    (smtp,) = FakeSMTP.instances
    assert isinstance(smtp.context, ssl.SSLContext) and smtp.port == 465
    assert [c[0] for c in smtp.calls] == ["login", "send", "quit"]


async def test_no_user_no_login():
    await channel(CFG.model_copy(update={"smtp_user": ""}), password="").send([N], heading="h")
    assert [c[0] for c in FakeSMTP.instances[0].calls] == ["starttls", "send", "quit"]


def test_subject_crlf_is_stripped():
    msg = build_message(CFG, [N], subject="Hi\r\nBcc: victim@example.org\nX: y", heading="h")
    assert msg["Subject"] == "Hi Bcc: victim@example.org X: y"
    assert msg["Bcc"] is None
    assert "\nBcc:" not in msg.as_string()


def test_header_line_and_body_are_single_lines_per_field():
    assert header_line("a\rb\nc\x00d e") == "a b c d e"
    assert len(header_line("x" * 500)) <= 200
    body = body_text([Notice(1, "T\r\nInjected: yes", "javascript:x", ("S",), "w\nx")],
                     heading="h")
    assert "T Injected: yes" in body and "javascript" not in body and "w x" in body


async def test_auth_failure_hides_password_and_server_text():
    FakeSMTP.fail_on = "login"
    FakeSMTP.exc = smtplib.SMTPAuthenticationError(535, f"bad {PASSWORD}".encode())
    with pytest.raises(NotifyError) as info:
        await channel().send([N], heading="h")
    assert str(info.value) == "email: SMTPAuthenticationError 535"
    assert info.value.__cause__ is None
    assert PASSWORD not in str(info.value)


async def test_connect_failure_is_a_notify_error():
    FakeSMTP.fail_on = "connect"
    with pytest.raises(NotifyError, match="email: ConnectionRefusedError"):
        FakeSMTP.exc = ConnectionRefusedError("refused")
        await channel().send([N], heading="h")


@pytest.mark.parametrize("update", [{"smtp_host": ""}, {"smtp_from": ""}, {"smtp_to": []}])
def test_incomplete_config_refused(update):
    with pytest.raises(NotifyError, match="smtp_host, smtp_from and smtp_to"):
        channel(CFG.model_copy(update=update))


def test_user_without_password_refused():
    with pytest.raises(NotifyError, match="SIDEREAL_SMTP_PASSWORD"):
        channel(password="")


def test_repr_has_no_password():
    assert PASSWORD not in repr(channel())

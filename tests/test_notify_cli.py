"""``sidereal notify test`` (M28): sends one fixed message, never prints a secret."""

from __future__ import annotations

import httpx
import pytest

from sidereal import cli
from sidereal.notify import notifycli
from tests.notify_helpers import TOKEN, WEBHOOK, FakeSMTP, Recorder


@pytest.fixture
def rec(monkeypatch, config_file):
    r = Recorder()
    monkeypatch.setattr(notifycli, "make_fetcher", lambda settings: r.fetcher())
    monkeypatch.setenv("SIDEREAL_DISCORD_WEBHOOK_URL", WEBHOOK)
    return r


def test_discord_test_message(rec, capsys):
    assert cli.main(["notify", "test", "--channel", "discord"]) == 0
    assert capsys.readouterr().out.strip() == "discord: sent"
    (body,) = rec.payloads()
    assert body["allowed_mentions"] == {"parse": []}
    assert body["embeds"][0]["title"] == "Sidereal test notification"


def test_failure_exit_1_without_secret(rec, capsys):
    rec.answer = lambda r: httpx.Response(404, text=str(r.url))
    assert cli.main(["notify", "test", "--channel", "discord"]) == 1
    captured = capsys.readouterr()
    assert "discord: failed" in captured.err and "HTTP 404" in captured.err
    assert TOKEN not in captured.err + captured.out


def test_configured_channels_are_used(rec, capsys, monkeypatch):
    FakeSMTP.reset()
    monkeypatch.setattr("sidereal.notify.email.smtplib.SMTP", FakeSMTP)
    monkeypatch.setenv("SIDEREAL_NOTIFY__CHANNELS", '["email", "discord"]')
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_HOST", "smtp.example.net")
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_FROM", "a@example.net")
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_TO", '["a@example.net"]')
    assert cli.main(["notify", "test"]) == 0
    assert capsys.readouterr().out.splitlines() == ["email: sent", "discord: sent"]
    assert len(FakeSMTP.instances) == 1 and len(rec.requests) == 1
    FakeSMTP.reset()


def test_nothing_configured_exit_2(rec, capsys):
    assert cli.main(["notify", "test"]) == 2
    assert "no channels configured" in capsys.readouterr().err
    assert rec.requests == []


def test_missing_webhook_exit_1(rec, capsys, monkeypatch):
    monkeypatch.delenv("SIDEREAL_DISCORD_WEBHOOK_URL")
    assert cli.main(["notify", "test", "--channel", "discord"]) == 1
    assert "SIDEREAL_DISCORD_WEBHOOK_URL is not set" in capsys.readouterr().err


def test_bad_channel_is_a_usage_error(rec):
    with pytest.raises(SystemExit) as info:
        cli.main(["notify", "test", "--channel", "signal"])
    assert info.value.code == 2

"""notify/dispatcher.py (M28): once per story and channel, one batch per run, quiet hours,
failures recorded without secrets and never raised."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sidereal.db import notify_repo
from sidereal.notify import dispatcher
from sidereal.notify.base import Notice, NotifyError, Secrets
from sidereal.notify.dispatcher import dispatch, in_quiet_hours, send_test
from tests.factories import make_run, make_story
from tests.notify_helpers import PASSWORD, TOKEN, WEBHOOK, FakeSMTP, Recorder

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)  # 12:00 in Europe/London (GMT)
SECRETS = Secrets(smtp_password=PASSWORD, discord_webhook_url=WEBHOOK)


class FakeChannel:
    def __init__(self, name: str, fail: BaseException | None = None) -> None:
        self.name = name
        self.fail = fail
        self.batches: list[tuple[list[Notice], str]] = []

    async def send(self, notices: list[Notice], *, heading: str) -> None:
        self.batches.append((notices, heading))
        if self.fail is not None:
            raise self.fail


def factory_for(channels: dict[str, FakeChannel]):
    return lambda name, settings, secrets, fetcher: channels[name]


def with_notify(settings, **kw):
    return settings.model_copy(update={"notify": settings.notify.model_copy(update=kw)})


@pytest.fixture
def run_id(db):
    return make_run(db, at=NOW - timedelta(hours=1))


def top(db, run_id, **kw):
    return make_story(db, run_id=run_id, first_seen=kw.pop("first_seen", NOW - timedelta(hours=1)),
                      bucket="top", score=80.0, **kw)


async def test_no_channels_does_nothing(db, settings, run_id):
    top(db, run_id)
    assert await dispatch(db, settings, fetcher=None, now=NOW, run_id=run_id,
                          secrets=SECRETS) == {}


async def test_sends_once_per_story(db, settings, run_id):
    s = with_notify(settings, channels=["discord"])
    a, b = top(db, run_id, title="A"), top(db, run_id, title="B")
    ch = FakeChannel("discord")
    kw = {"fetcher": None, "run_id": run_id, "secrets": SECRETS, "factory": factory_for(
        {"discord": ch})}
    assert await dispatch(db, s, now=NOW, **kw) == {"discord": {"sent": 2}}
    assert len(ch.batches) == 1  # one batch per run
    notices, heading = ch.batches[0]
    assert sorted(n.story_id for n in notices) == [a, b]
    assert heading == "Sidereal: 2 new TOP stories"
    assert await dispatch(db, s, now=NOW + timedelta(hours=4), **kw) == {"discord": {"sent": 0}}
    assert len(ch.batches) == 1
    c = top(db, run_id, title="C")
    assert await dispatch(db, s, now=NOW + timedelta(hours=8), **kw) == {"discord": {"sent": 1}}
    assert [n.story_id for n in ch.batches[1][0]] == [c]
    assert ch.batches[1][1] == "Sidereal: 1 new TOP story"


async def test_channels_are_independent(db, settings, run_id):
    s = with_notify(settings, channels=["email", "discord"])
    a = top(db, run_id)
    email, discord = FakeChannel("email", fail=NotifyError("email: SMTPException")), \
        FakeChannel("discord")
    stats = await dispatch(db, s, fetcher=None, now=NOW, run_id=run_id, secrets=SECRETS,
                           factory=factory_for({"email": email, "discord": discord}))
    assert stats == {"email": {"error": "NotifyError: email: SMTPException", "pending": 1},
                     "discord": {"sent": 1}}
    assert notify_repo.sent_ids(db, "discord") == [a]
    assert notify_repo.sent_ids(db, "email") == []  # retried next run


async def test_failure_keeps_secrets_out_of_logs_stats_and_db(db, settings, run_id, caplog):
    caplog.set_level(logging.DEBUG)
    s = with_notify(settings, channels=["discord", "email"])
    top(db, run_id)
    leak = RuntimeError(f"POST {WEBHOOK} failed, password {PASSWORD}")
    chans = {"discord": FakeChannel("discord", fail=leak),
             "email": FakeChannel("email", fail=leak)}
    stats = await dispatch(db, s, fetcher=None, now=NOW, run_id=run_id, secrets=SECRETS,
                           factory=factory_for(chans))
    assert set(stats) == {"discord", "email"} and "error" in stats["discord"]
    for text in (repr(stats), caplog.text, "\n".join(db.iterdump())):
        assert TOKEN not in text and PASSWORD not in text
    assert "[redacted]" in stats["discord"]["error"]


async def test_real_discord_failure_has_no_secret(db, settings, run_id, caplog):
    caplog.set_level(logging.DEBUG)
    s = with_notify(settings, channels=["discord"])
    top(db, run_id)
    rec = Recorder(lambda r: httpx.Response(401, text=str(r.url)))
    stats = await dispatch(db, s, fetcher=rec.fetcher(), now=NOW, run_id=run_id,
                           secrets=SECRETS)
    assert stats["discord"]["error"] == "NotifyError: discord: FetchHTTPError: HTTP 401"
    assert TOKEN not in caplog.text and len(rec.requests) == 1


async def test_real_discord_success_through_the_fetcher(db, settings, run_id):
    s = with_notify(settings, channels=["discord"])
    a = top(db, run_id, title="@everyone **pwned**")
    rec = Recorder()
    stats = await dispatch(db, s, fetcher=rec.fetcher(), now=NOW, run_id=run_id,
                           secrets=SECRETS)
    assert stats == {"discord": {"sent": 1}}
    (body,) = rec.payloads()
    assert body["allowed_mentions"] == {"parse": []}
    assert body["embeds"][0]["title"] == r"\@everyone \*\*pwned\*\*"
    assert notify_repo.sent_ids(db, "discord") == [a]


async def test_missing_secret_is_an_error_not_a_crash(db, settings, run_id):
    s = with_notify(settings, channels=["discord"])
    top(db, run_id)
    stats = await dispatch(db, s, fetcher=None, now=NOW, run_id=run_id, secrets=Secrets())
    assert "SIDEREAL_DISCORD_WEBHOOK_URL is not set" in stats["discord"]["error"]


async def test_unreadable_env_file_is_reported(db, settings, run_id, monkeypatch):
    s = with_notify(settings, channels=["email"])

    def refuse(env=None):
        raise dispatcher.NotifyError("env is readable by group/other: chmod 600 it")

    monkeypatch.setattr(dispatcher, "load_secrets", refuse)
    stats = await dispatch(db, s, fetcher=None, now=NOW, run_id=run_id)
    assert "chmod 600" in stats["email"]["error"]


async def test_quiet_hours_hold_until_morning(db, settings, run_id):
    s = with_notify(settings, channels=["discord"])
    top(db, run_id, first_seen=NOW + timedelta(hours=10))
    ch = FakeChannel("discord")
    kw = {"fetcher": None, "run_id": run_id, "secrets": SECRETS,
          "factory": factory_for({"discord": ch})}
    night = datetime(2026, 11, 26, 0, 0, tzinfo=UTC)
    assert await dispatch(db, s, now=night, **kw) == {"discord": {"held": 1}}
    assert ch.batches == []
    morning = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    assert await dispatch(db, s, now=morning, **kw) == {"discord": {"sent": 1}}


@pytest.mark.parametrize(("hhmm", "start", "end", "quiet"), [
    ("21:59", "22:00", "07:00", False), ("22:00", "22:00", "07:00", True),
    ("03:00", "22:00", "07:00", True), ("06:59", "22:00", "07:00", True),
    ("07:00", "22:00", "07:00", False), ("13:00", "12:00", "14:00", True),
    ("14:00", "12:00", "14:00", False), ("03:00", "00:00", "00:00", False),
])
def test_in_quiet_hours(settings, hhmm, start, end, quiet):
    s = with_notify(settings, quiet_start=start, quiet_end=end)
    h, m = map(int, hhmm.split(":"))
    assert in_quiet_hours(datetime(2026, 11, 25, h, m, tzinfo=UTC), s) is quiet


def test_quiet_hours_use_local_time(settings):
    s = with_notify(settings, quiet_start="22:00", quiet_end="07:00")
    # 06:30 UTC in July is 07:30 in London (BST): not quiet.
    assert in_quiet_hours(datetime(2026, 7, 1, 6, 30, tzinfo=UTC), s) is False


async def test_bad_quiet_time_is_an_error(db, settings, run_id):
    s = with_notify(settings, channels=["email"], quiet_start="25:99")
    top(db, run_id)
    stats = await dispatch(db, s, fetcher=None, now=NOW, run_id=run_id, secrets=SECRETS)
    assert "bad quiet-hours time" in stats["email"]["error"]


async def test_send_test_uses_real_email_channel(settings, monkeypatch):
    FakeSMTP.reset()
    monkeypatch.setattr("sidereal.notify.email.smtplib.SMTP", FakeSMTP)
    s = with_notify(settings, smtp_host="smtp.example.net", smtp_user="u", smtp_from="a@b.c",
                    smtp_to=["a@b.c"])
    await send_test(s, "email", fetcher=None, secrets=SECRETS)
    (smtp,) = FakeSMTP.instances
    assert smtp.messages[0]["Subject"] == "Sidereal: test notification"
    FakeSMTP.reset()

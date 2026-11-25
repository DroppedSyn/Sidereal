"""M28 in the runner: a run notifies new TOP stories once; a notify failure never fails it."""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
import pytest

from sidereal.db import notify_repo
from sidereal.pipeline.runner import run_once
from tests.notify_helpers import TOKEN, WEBHOOK
from tests.pipeline_helpers import (
    NOW,
    FeedServer,
    assess_reply,
    ollama_for,
    seeded_db,
    smart_ollama,
)


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


@pytest.fixture
def notify_settings(settings, monkeypatch):
    monkeypatch.setenv("SIDEREAL_DISCORD_WEBHOOK_URL", WEBHOOK)
    # NOW is 00:00 London: inside the default quiet hours, so turn them off here.
    return settings.model_copy(update={"notify": settings.notify.model_copy(
        update={"channels": ["discord"], "quiet_start": "00:00", "quiet_end": "00:00"})})


def _fake():
    def by_title(title):
        return assess_reply(3, 3, 3, 2, exploited_in_wild=True) if "KEV" in title \
            else assess_reply(1, 1, 0, 1, focus="industry")
    return smart_ollama(assess=by_title)


async def _run(s, conn, server, now):
    return await run_once(s, conn, fetcher=server.fetcher(), ollama=ollama_for(_fake(), s),
                          now=now)


async def test_run_sends_top_stories_once(notify_settings, conn):
    posts: list[httpx.Request] = []
    server = FeedServer(conn)
    server.pages[WEBHOOK] = lambda r: (posts.append(r), httpx.Response(204))[1]
    row = await _run(notify_settings, conn, server, NOW)
    assert row.status == "ok", row.error
    top = row.stats["buckets"]["top"]
    assert top > 0
    assert row.stats["notify"] == {"discord": {"sent": top}}
    assert len(posts) == 1
    assert len(notify_repo.sent_ids(conn, "discord")) == top
    again = await _run(notify_settings, conn, server, NOW + timedelta(hours=4))
    assert again.stats["notify"] == {"discord": {"sent": 0}}
    assert len(posts) == 1


async def test_notify_failure_does_not_fail_the_run(notify_settings, conn, caplog):
    caplog.set_level(logging.DEBUG)
    server = FeedServer(conn)
    server.pages[WEBHOOK] = httpx.Response(500)
    row = await _run(notify_settings, conn, server, NOW)
    assert row.status == "partial"
    assert row.error == "notify failed: discord"
    assert row.stats["buckets"]["top"] > 0
    assert row.stats["notify"]["discord"]["error"].endswith("HTTP 500")
    assert notify_repo.sent_ids(conn, "discord") == []
    assert TOKEN not in caplog.text and TOKEN not in repr(row)
    assert TOKEN not in "\n".join(conn.iterdump())


async def test_no_channels_no_notify_stats(settings, conn):
    row = await _run(settings, conn, FeedServer(conn), NOW)
    assert "notify" not in row.stats

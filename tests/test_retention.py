"""pipeline/retention.py (M22): content_text after 30 days, dropped stories after 90 (§12.4)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sidereal.config import RetentionSettings
from sidereal.db import items_repo, stories_repo
from sidereal.pipeline.retention import apply_retention
from sidereal.pipeline.runner import run_once
from tests.pipeline_helpers import (
    NOW,
    FeedServer,
    add_story,
    ollama_for,
    seeded_db,
    smart_ollama,
    start,
)

DAY = timedelta(days=1)


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def story_with_content(conn, rid, at, *, bucket=None, state=None):
    sid = add_story(conn, rid, at=at, title=f"Story seen at {at.isoformat()} {bucket} {state}")
    item = items_repo.items_for_story(conn, sid)[0]
    items_repo.set_content(conn, item.id, text="article body", status="ok")
    if bucket is not None:
        stories_repo.set_score(conn, sid, score=10.0, bucket=bucket)
    if state is not None:
        stories_repo.set_state(conn, sid, state)
    return sid, item.id


def content(conn, item_id):
    return items_repo.get_item(conn, item_id).content_text


def test_content_cleared_strictly_after_30_days(conn):
    rid = start(conn)
    _, old = story_with_content(conn, rid, NOW - 30 * DAY - timedelta(seconds=1))
    _, edge = story_with_content(conn, rid, NOW - 30 * DAY)
    _, fresh = story_with_content(conn, rid, NOW - 29 * DAY)
    stats = apply_retention(conn, RetentionSettings(), now=NOW)
    assert stats == {"content_pruned": 1, "stories_deleted": 0}
    assert content(conn, old) is None
    assert content(conn, edge) == "article body" and content(conn, fresh) == "article body"
    old_item = items_repo.get_item(conn, old)
    assert old_item.excerpt == "An excerpt."  # summaries/excerpts are kept forever


def test_dropped_deleted_strictly_after_90_days(conn):
    rid = start(conn)
    old_drop, old_item = story_with_content(conn, rid, NOW - 90 * DAY - timedelta(seconds=1),
                                            bucket="drop")
    old_filtered, _ = story_with_content(conn, rid, NOW - 91 * DAY, state="filtered")
    old_triaged, _ = story_with_content(conn, rid, NOW - 91 * DAY, state="triaged_out")
    edge_drop, _ = story_with_content(conn, rid, NOW - 90 * DAY, bucket="drop")
    old_top, _ = story_with_content(conn, rid, NOW - 200 * DAY, bucket="top")
    stats = apply_retention(conn, RetentionSettings(), now=NOW)
    assert stats["stories_deleted"] == 3
    for gone in (old_drop, old_filtered, old_triaged):
        assert stories_repo.get_story(conn, gone) is None
    assert items_repo.get_item(conn, old_item) is None
    assert stories_repo.get_story(conn, edge_drop) is not None
    assert stories_repo.get_story(conn, old_top) is not None  # kept stories are never deleted


def test_day_counts_come_from_config(conn):
    rid = start(conn)
    _, item = story_with_content(conn, rid, NOW - 3 * DAY)
    drop, _ = story_with_content(conn, rid, NOW - 6 * DAY, bucket="drop")
    cfg = RetentionSettings(content_days=2, drop_days=5)
    # content is pruned first (both items), then the dropped story goes
    assert apply_retention(conn, cfg, now=NOW) == {"content_pruned": 2, "stories_deleted": 1}
    assert content(conn, item) is None and stories_repo.get_story(conn, drop) is None


def test_retention_settings_defaults_and_bounds():
    cfg = RetentionSettings()
    assert (cfg.content_days, cfg.drop_days, cfg.backup_keep) == (30, 90, 14)
    with pytest.raises(ValueError):
        RetentionSettings(drop_days=0)
    with pytest.raises(ValueError):
        RetentionSettings(backup_keep=0)


async def test_run_once_applies_retention(settings, conn):
    rid = start(conn, at=NOW - 100 * DAY)
    drop, _ = story_with_content(conn, rid, NOW - 100 * DAY, bucket="drop")
    server = FeedServer(conn)
    row = await run_once(settings, conn, fetcher=server.fetcher(),
                         ollama=ollama_for(smart_ollama(), settings), now=NOW)
    assert row.stats["retention"]["stories_deleted"] == 1
    assert stories_repo.get_story(conn, drop) is None


async def test_retention_error_leaves_run_partial(settings, conn, monkeypatch):
    from sidereal.pipeline import retention

    def boom(*a, **kw):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(retention, "apply_retention", boom)
    server = FeedServer(conn)
    row = await run_once(settings, conn, fetcher=server.fetcher(),
                         ollama=ollama_for(smart_ollama(), settings), now=NOW)
    assert row.status == "partial" and "retention failed: RuntimeError" in row.error

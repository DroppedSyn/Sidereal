"""db/notify_repo.py (M28) and migration 0005_notify."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db import feedback_repo, notify_repo, stories_repo
from tests.factories import make_run, make_story

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=48)


@pytest.fixture
def run_id(db):
    return make_run(db, at=NOW - timedelta(hours=1))


def top(db, run_id, **kw):
    kw.setdefault("first_seen", NOW - timedelta(hours=2))
    return make_story(db, run_id=run_id, bucket="top", score=kw.pop("score", 80.0), **kw)


def ids(rows):
    return [r.story_id for r in rows]


def test_pending_top_fields_and_order(db, run_id):
    a = top(db, run_id, title="A", score=75.0, sources=("msrc", "krebs"), why="Because.")
    b = top(db, run_id, title="B", score=90.0)
    rows = notify_repo.pending_top(db, "discord", since=SINCE)
    assert ids(rows) == [b, a]
    ra = rows[1]
    assert ra.title == "A" and ra.why == "Because." and ra.score == 75.0
    assert ra.url == f"https://msrc.example/{a}/0" and len(ra.sources) == 2


def test_pending_top_filters(db, run_id):
    keep = top(db, run_id)
    make_story(db, run_id=run_id, first_seen=NOW - timedelta(hours=2), bucket="relevant")
    top(db, run_id, first_seen=SINCE - timedelta(seconds=1))
    hidden = top(db, run_id)
    feedback_repo.set_hidden(db, hidden, True, at=NOW)
    at_cutoff = top(db, run_id, first_seen=SINCE)
    assert ids(notify_repo.pending_top(db, "email", since=SINCE)) == [keep, at_cutoff]


def test_mark_sent_is_per_channel_and_idempotent(db, run_id):
    a, b = top(db, run_id), top(db, run_id)
    assert notify_repo.mark_sent(db, [a], "discord", run_id=run_id, at=NOW) == 1
    assert notify_repo.mark_sent(db, [a, b], "discord", run_id=run_id, at=NOW) == 1
    assert ids(notify_repo.pending_top(db, "discord", since=SINCE)) == []
    assert ids(notify_repo.pending_top(db, "email", since=SINCE)) == [a, b]
    assert notify_repo.sent_ids(db, "discord") == [a, b]


def test_mark_sent_commits(db, run_id, settings):
    from sidereal.db.connect import connect

    a = top(db, run_id)
    notify_repo.mark_sent(db, [a], "email", run_id=run_id, at=NOW)
    other = connect(settings.db_path)
    assert notify_repo.sent_ids(other, "email") == [a]
    other.close()


def test_limit(db, run_id):
    for _ in range(3):
        top(db, run_id)
    assert len(notify_repo.pending_top(db, "email", since=SINCE, limit=2)) == 2


def test_unknown_channel(db):
    with pytest.raises(ValueError):
        notify_repo.pending_top(db, "signal", since=SINCE)
    with pytest.raises(ValueError):
        notify_repo.mark_sent(db, [1], "signal", run_id=None, at=NOW)


def test_rows_go_with_the_story(db, run_id):
    a = top(db, run_id, first_seen=NOW - timedelta(days=200))
    stories_repo.set_score(db, a, score=1.0, bucket="drop")
    notify_repo.mark_sent(db, [a], "email", run_id=run_id, at=NOW)
    stories_repo.delete_dropped_before(db, before=NOW - timedelta(days=90))
    assert notify_repo.sent_ids(db, "email") == []

"""views_repo.story_detail / item_counts_since (M15b)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.bootstrap import migrate
from sidereal.db.connect import connect
from sidereal.db.items_repo import items_for_story, set_content
from sidereal.db.sources_repo import get_by_key
from sidereal.db.views_repo import item_counts_since, story_detail
from tests.factories import make_run, make_story

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


@pytest.fixture
def conn(settings):
    migrate(settings)
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def run(conn):
    return make_run(conn, at=NOW - 2 * HOUR)


def test_unknown_is_none(conn):
    assert story_detail(conn, 1) is None


def test_hidden_is_none(conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW, state="filtered", bucket=None,
                     score=None)
    assert story_detail(conn, sid) is None


def test_items_in_id_order_with_sources(conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW, sources=("hn", "bleepingcomputer", "hn"),
                     urls=("https://a.example/1", "javascript:x", "https://a.example/3"))
    d = story_detail(conn, sid)
    assert d is not None
    assert [i.source_key for i in d.items] == ["hn", "bleepingcomputer", "hn"]
    assert [i.url for i in d.items] == ["https://a.example/1", None, "https://a.example/3"]
    assert [i.id for i in d.items] == sorted(i.id for i in d.items)
    assert d.story.id == sid
    assert [s.key for s in d.story.sources] == ["hn", "bleepingcomputer"]


def test_other_story_items_not_mixed(conn, run):
    a = make_story(conn, run_id=run, first_seen=NOW, sources=("hn",))
    b = make_story(conn, run_id=run, first_seen=NOW, sources=("bleepingcomputer",))
    da, db = story_detail(conn, a), story_detail(conn, b)
    assert [i.source_key for i in da.items] == ["hn"]
    assert [i.source_key for i in db.items] == ["bleepingcomputer"]


def test_assessment_fields(conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW, flags={"exploited": True})
    a = story_detail(conn, sid).assessment
    assert (a.model, a.prompt_version, a.relevance, a.urgency, a.actionability, a.novelty,
            a.exploited_in_wild) == ("demo-model", "assess.v1", 2, 2, 2, 2, True)
    other = make_story(conn, run_id=run, first_seen=NOW)
    assert story_detail(conn, other).assessment.exploited_in_wild is False


def test_no_assessment(conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW, state="assess_failed", bucket=None,
                     score=None)
    assert story_detail(conn, sid).assessment is None


def test_never_selects_content(conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW)
    set_content(conn, items_for_story(conn, sid)[0].id, text="BODY", status="ok")
    seen: list[str] = []
    conn.set_trace_callback(seen.append)
    d = story_detail(conn, sid)
    conn.set_trace_callback(None)
    assert d is not None and seen
    assert not any("content" in s for s in seen)
    assert "BODY" not in repr(d)


def test_item_counts_since(conn, run):
    make_story(conn, run_id=run, first_seen=NOW - 7 * 24 * HOUR, sources=("hn",))
    make_story(conn, run_id=run, first_seen=NOW - 7 * 24 * HOUR - timedelta(seconds=1),
               sources=("hn",))
    make_story(conn, run_id=run, first_seen=NOW, sources=("hn", "bleepingcomputer"))
    counts = item_counts_since(conn, since=NOW - 7 * 24 * HOUR)
    hn, bc = get_by_key(conn, "hn").id, get_by_key(conn, "bleepingcomputer").id
    assert counts == {hn: 2, bc: 1}
    assert item_counts_since(conn, since=NOW + HOUR) == {}

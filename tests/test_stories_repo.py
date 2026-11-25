"""Tests for ``src/sidereal/db/stories_repo.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db.items_repo import insert_item
from sidereal.db.runs_repo import start_run
from sidereal.db.seed import seed_sources
from sidereal.db.sources_repo import get_by_key
from sidereal.db.stories_repo import (
    attach_item,
    create_story,
    delete_dropped_before,
    get_story,
    pending_stories,
    recent_stories,
    set_score,
    set_state,
    set_triage,
    stories_for_day,
    stories_since,
)
from sidereal.defaults import SourceSeed

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
SEC = timedelta(seconds=1)
HOUR = timedelta(hours=1)


def _source(db, key="src"):
    seed_sources(db, [SourceSeed(key=key, name=key.upper(), kind="rss",
                                 url=f"https://{key}.example/feed", enabled=True, options={})])
    return get_by_key(db, key).id


def _run(db):
    return start_run(db, trigger="timer", at=T0)


def _story(db, run_id, *, title="T", first_seen_at=T0, day="2026-11-20", cve_ids=()):
    return create_story(db, title=title, day=day, first_seen_at=first_seen_at,
                        first_run_id=run_id, cve_ids=cve_ids)


def _item(db, source_id, story_id, run_id, *, guid, canonical_url,
          title_norm="t", first_seen_at=T0):
    return insert_item(db, source_id=source_id, story_id=story_id, guid=guid,
                       url=canonical_url, canonical_url=canonical_url,
                       title=title_norm, title_norm=title_norm, author=None,
                       published_at=None, first_seen_at=first_seen_at, run_id=run_id)


def _items_of(db, story_id):
    return db.execute("SELECT count(*) FROM items WHERE story_id = ?", (story_id,)).fetchone()[0]


@pytest.fixture
def env(db):
    return _source(db), _run(db)


def test_create_story_round_trip(db, env):
    _, rid = env
    st = get_story(db, create_story(db, title="Story", day="2026-11-20", first_seen_at=T0,
                                    first_run_id=rid, cve_ids=["CVE-2026-1", "CVE-2026-2"],
                                    flags={"kev": True, "cvss": 9.8}))
    assert (st.title, st.day, st.state, st.first_run_id) == ("Story", "2026-11-20", "new", rid)
    assert st.first_seen_at == st.last_seen_at == "2026-11-20T12:00:00Z"
    assert st.lead_item_id is None
    assert st.cve_ids == ["CVE-2026-1", "CVE-2026-2"]
    assert st.flags == {"kev": True, "cvss": 9.8}
    assert st.score is None and st.bucket is None and st.triage_relevance is None
    assert st.filter_reason is None
    plain = get_story(db, _story(db, rid))
    assert plain.cve_ids == [] and plain.flags == {}
    assert get_story(db, 9999) is None


def test_attach_sets_lead_once(db, env):
    sid, rid = env
    st = _story(db, rid)
    a = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/a")
    b = _item(db, sid, st, rid, guid="b", canonical_url="https://x.example/b")
    assert get_story(db, st).lead_item_id is None
    attach_item(db, st, item_id=a, seen_at=T0)
    attach_item(db, st, item_id=b, seen_at=T0 + HOUR)
    assert get_story(db, st).lead_item_id == a


def test_attach_merges_cves_in_order(db, env):
    sid, rid = env
    st = _story(db, rid, cve_ids=["CVE-1", "CVE-2"])
    a = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/a")
    attach_item(db, st, item_id=a, seen_at=T0,
                cve_ids=["CVE-2", "CVE-3", "CVE-3", "CVE-1", "CVE-4"])
    assert get_story(db, st).cve_ids == ["CVE-1", "CVE-2", "CVE-3", "CVE-4"]
    attach_item(db, st, item_id=a, seen_at=T0)
    assert get_story(db, st).cve_ids == ["CVE-1", "CVE-2", "CVE-3", "CVE-4"]


def test_attach_last_seen_never_moves_back(db, env):
    sid, rid = env
    st = _story(db, rid)
    a = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/a")
    attach_item(db, st, item_id=a, seen_at=T0 + 2 * HOUR)
    assert get_story(db, st).last_seen_at == "2026-11-20T14:00:00Z"
    attach_item(db, st, item_id=a, seen_at=T0 + HOUR)
    assert get_story(db, st).last_seen_at == "2026-11-20T14:00:00Z"
    assert get_story(db, st).first_seen_at == "2026-11-20T12:00:00Z"


def test_attach_unknown_story_raises(db, env):
    with pytest.raises(KeyError):
        attach_item(db, 9999, item_id=1, seen_at=T0)
    assert db.in_transaction is False


def test_recent_stories_window_inclusive(db, env):
    sid, rid = env
    since = T0 + 5 * HOUR
    a = _story(db, rid, title="A", cve_ids=["CVE-9"])
    b = _story(db, rid, title="B")
    c = _story(db, rid, title="C")
    a2 = _item(db, sid, a, rid, guid="a2", canonical_url="https://x.example/a2", title_norm="zz")
    a1 = _item(db, sid, a, rid, guid="a1", canonical_url="https://x.example/a1", title_norm="aa")
    b1 = _item(db, sid, b, rid, guid="b1", canonical_url="https://x.example/b1", title_norm="bb")
    attach_item(db, a, item_id=a2, seen_at=since)
    attach_item(db, a, item_id=a1, seen_at=since)
    attach_item(db, b, item_id=b1, seen_at=since - SEC)
    set_state(db, c, "assessed")
    attach_item(db, c, item_id=b1, seen_at=since + HOUR)  # lead only; no items of its own
    recent = recent_stories(db, since=since)
    assert [s.id for s in recent] == [a, c]
    assert recent[0].title == "A"
    assert recent[0].title_norms == ["zz", "aa"]
    assert recent[0].cve_ids == ["CVE-9"]
    assert recent[1].title_norms == []
    assert recent[1].cve_ids == []


def test_pending_oldest_first_and_limit(db, env):
    _, rid = env
    late = _story(db, rid, first_seen_at=T0 + 2 * HOUR)
    early = _story(db, rid, first_seen_at=T0)
    middle = _story(db, rid, first_seen_at=T0 + HOUR)
    tie = _story(db, rid, first_seen_at=T0)
    done = _story(db, rid, first_seen_at=T0 - HOUR)
    set_state(db, done, "assessed")
    assert [s.id for s in pending_stories(db)] == [early, tie, middle, late]
    assert [s.id for s in pending_stories(db, limit=2)] == [early, tie]
    assert [s.id for s in pending_stories(db, limit=10)] == [early, tie, middle, late]


def test_set_state_reason_and_invalid(db, env):
    _, rid = env
    st = _story(db, rid)
    set_state(db, st, "filtered", reason="no keywords")
    row = get_story(db, st)
    assert (row.state, row.filter_reason) == ("filtered", "no keywords")
    set_state(db, st, "new")
    row = get_story(db, st)
    assert (row.state, row.filter_reason) == ("new", None)
    with pytest.raises(ValueError):
        set_state(db, st, "bogus")
    assert get_story(db, st).state == "new"
    with pytest.raises(KeyError):
        set_state(db, 9999, "new")


def test_set_triage_bounds(db, env):
    _, rid = env
    st = _story(db, rid)
    set_triage(db, st, 0)
    assert get_story(db, st).triage_relevance == 0
    set_triage(db, st, 3)
    assert get_story(db, st).triage_relevance == 3
    for bad in (-1, 4):
        with pytest.raises(ValueError):
            set_triage(db, st, bad)
    assert get_story(db, st).triage_relevance == 3
    with pytest.raises(KeyError):
        set_triage(db, 9999, 1)


def test_set_score_and_invalid_bucket(db, env):
    _, rid = env
    st = _story(db, rid)
    set_score(db, st, score=81.5, bucket="top")
    row = get_story(db, st)
    assert (row.score, row.bucket) == (81.5, "top")
    set_score(db, st, score=None, bucket="side")
    row = get_story(db, st)
    assert (row.score, row.bucket) == (None, "side")
    with pytest.raises(ValueError):
        set_score(db, st, score=1.0, bucket="hot")
    assert get_story(db, st).bucket == "side"
    with pytest.raises(KeyError):
        set_score(db, 9999, score=1.0, bucket="top")


def test_stories_for_day(db, env):
    _, rid = env
    first = _story(db, rid, first_seen_at=T0 + HOUR)
    _story(db, rid, day="2026-11-21")
    second = _story(db, rid, first_seen_at=T0)
    assert [s.id for s in stories_for_day(db, "2026-11-20")] == [first, second]
    assert stories_for_day(db, "2026-11-22") == []


def test_stories_since_inclusive(db, env):
    _, rid = env
    since = T0 + 5 * HOUR
    later = _story(db, rid, first_seen_at=since + HOUR)
    _story(db, rid, first_seen_at=since - SEC)
    exact = _story(db, rid, first_seen_at=since)
    assert [s.id for s in stories_since(db, since)] == [exact, later]


def test_delete_dropped_before(db, env):
    sid, rid = env
    old = T0 - SEC
    drop = _story(db, rid, first_seen_at=old)
    set_score(db, drop, score=1.0, bucket="drop")
    _item(db, sid, drop, rid, guid="d1", canonical_url="https://x.example/d1")
    _item(db, sid, drop, rid, guid="d2", canonical_url="https://x.example/d2")
    db.execute(
        "INSERT INTO assessments (story_id, model, prompt_version, relevance, urgency,"
        " actionability, novelty, tags_json, summary, why, raw_json, duration_ms, created_at)"
        " VALUES (?, 'm', 'p', 0, 0, 0, 0, '[]', 's', 'w', '{}', 1, '2026-11-20T00:00:00Z')",
        (drop,),
    )
    db.commit()
    triaged = _story(db, rid, first_seen_at=old)
    set_state(db, triaged, "triaged_out")
    _item(db, sid, triaged, rid, guid="t1", canonical_url="https://x.example/t1")
    filtered = _story(db, rid, first_seen_at=old)
    set_state(db, filtered, "filtered", reason="r")
    at_cutoff = _story(db, rid, first_seen_at=T0)
    set_score(db, at_cutoff, score=1.0, bucket="drop")
    _item(db, sid, at_cutoff, rid, guid="c1", canonical_url="https://x.example/c1")
    side = _story(db, rid, first_seen_at=old)
    set_score(db, side, score=50.0, bucket="side")
    _item(db, sid, side, rid, guid="s1", canonical_url="https://x.example/s1")
    fresh = _story(db, rid, first_seen_at=old)
    _item(db, sid, fresh, rid, guid="n1", canonical_url="https://x.example/n1")

    assert delete_dropped_before(db, before=T0) == 3
    for gone in (drop, triaged, filtered):
        assert get_story(db, gone) is None
        assert _items_of(db, gone) == 0
    for kept in (at_cutoff, side, fresh):
        assert get_story(db, kept) is not None
        assert _items_of(db, kept) == 1
    assert db.execute("SELECT count(*) FROM assessments").fetchone()[0] == 0
    assert delete_dropped_before(db, before=T0) == 0


def test_writes_commit(db, env):
    sid, rid = env
    st = _story(db, rid, first_seen_at=T0 - HOUR)
    assert db.in_transaction is False
    item = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/a")
    attach_item(db, st, item_id=item, seen_at=T0, cve_ids=["CVE-1"])
    assert db.in_transaction is False
    set_state(db, st, "filtered", reason="r")
    assert db.in_transaction is False
    set_triage(db, st, 2)
    assert db.in_transaction is False
    set_score(db, st, score=0.0, bucket="drop")
    assert db.in_transaction is False
    assert delete_dropped_before(db, before=T0) == 1
    assert db.in_transaction is False

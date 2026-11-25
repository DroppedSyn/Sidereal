"""Tests for ``src/sidereal/db/items_repo.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db.items_repo import (
    get_item,
    insert_item,
    item_exists,
    items_for_story,
    prune_content,
    set_content,
)
from sidereal.db.runs_repo import start_run
from sidereal.db.seed import seed_sources
from sidereal.db.sources_repo import get_by_key
from sidereal.db.stories_repo import create_story
from sidereal.defaults import SourceSeed

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


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


def _count(db):
    return db.execute("SELECT count(*) FROM items").fetchone()[0]


@pytest.fixture
def env(db):
    rid = _run(db)
    return _source(db), _story(db, rid), rid


def test_insert_and_get_round_trip(db, env):
    sid, st, rid = env
    iid = insert_item(db, source_id=sid, story_id=st, guid="g1",
                      url="https://src.example/1?utm=x", canonical_url="https://src.example/1",
                      title="Hello", title_norm="hello", author="alice",
                      published_at=T0, first_seen_at=T0 + timedelta(hours=1), run_id=rid)
    item = get_item(db, iid)
    assert (item.id, item.source_id, item.story_id, item.guid) == (iid, sid, st, "g1")
    assert item.url == "https://src.example/1?utm=x"
    assert item.canonical_url == "https://src.example/1"
    assert (item.title, item.title_norm, item.author) == ("Hello", "hello", "alice")
    assert item.published_at == "2026-11-20T12:00:00Z"
    assert item.first_seen_at == "2026-11-20T13:00:00Z"
    assert item.run_id == rid
    assert item.excerpt == ""
    assert item.content_text is None and item.content_status is None

    iid2 = insert_item(db, source_id=sid, story_id=st, guid=None,
                       url="https://src.example/2", canonical_url="https://src.example/2",
                       title="B", title_norm="b", author=None, published_at=None,
                       first_seen_at=T0, run_id=rid, excerpt="short")
    item2 = get_item(db, iid2)
    assert item2.published_at is None and item2.author is None and item2.guid is None
    assert item2.excerpt == "short"
    assert get_item(db, 9999) is None


def test_duplicate_canonical_url_returns_none(db, env):
    sid, st, rid = env
    other = _source(db, "other")
    assert _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/1") is not None
    assert _item(db, other, st, rid, guid="b", canonical_url="https://x.example/1") is None
    assert _count(db) == 1


def test_duplicate_source_guid_returns_none(db, env):
    sid, st, rid = env
    first = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/1")
    assert _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/2") is None
    assert _count(db) == 1
    # The id of the first insert is not returned for the duplicate (stale lastrowid).
    assert get_item(db, first).canonical_url == "https://x.example/1"


def test_same_guid_other_source_inserted(db, env):
    sid, st, rid = env
    other = _source(db, "other")
    first = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/1")
    second = _item(db, other, st, rid, guid="a", canonical_url="https://x.example/2")
    assert isinstance(second, int) and second != first


def test_null_guid_not_a_conflict(db, env):
    sid, st, rid = env
    first = _item(db, sid, st, rid, guid=None, canonical_url="https://x.example/1")
    second = _item(db, sid, st, rid, guid=None, canonical_url="https://x.example/2")
    assert isinstance(first, int) and isinstance(second, int) and first != second


def test_item_exists(db, env):
    sid, st, rid = env
    other = _source(db, "other")
    _item(db, sid, st, rid, guid="g1", canonical_url="https://x.example/1")
    _item(db, sid, st, rid, guid=None, canonical_url="https://x.example/2")
    assert item_exists(db, canonical_url="https://x.example/1", source_id=other, guid="zz")
    assert item_exists(db, canonical_url="https://x.example/new", source_id=sid, guid="g1")
    assert not item_exists(db, canonical_url="https://x.example/new", source_id=other, guid="g1")
    assert not item_exists(db, canonical_url="https://x.example/new", source_id=sid, guid=None)


def test_items_for_story_ordered_by_id(db, env):
    sid, st_a, rid = env
    st_b = _story(db, rid, title="B")
    ids = [_item(db, sid, st_a, rid, guid=g, canonical_url=f"https://x.example/{g}")
           for g in ("c", "a", "b")]
    b1 = _item(db, sid, st_b, rid, guid="d", canonical_url="https://x.example/d")
    assert [i.id for i in items_for_story(db, st_a)] == ids
    assert [i.id for i in items_for_story(db, st_b)] == [b1]
    assert items_for_story(db, 9999) == []


def test_set_content_and_invalid_status(db, env):
    sid, st, rid = env
    iid = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/1")
    set_content(db, iid, text="body", status="ok")
    item = get_item(db, iid)
    assert (item.content_text, item.content_status) == ("body", "ok")
    with pytest.raises(ValueError):
        set_content(db, iid, text="other", status="bogus")
    item = get_item(db, iid)
    assert (item.content_text, item.content_status) == ("body", "ok")
    set_content(db, iid, text=None, status="blocked")
    item = get_item(db, iid)
    assert (item.content_text, item.content_status) == (None, "blocked")
    with pytest.raises(KeyError):
        set_content(db, 9999, text="x", status="ok")


def test_prune_content_cutoff(db, env):
    sid, st, rid = env
    cutoff = T0 - timedelta(days=30)
    times = (T0 - timedelta(days=31), cutoff, T0)
    ids = [_item(db, sid, st, rid, guid=str(n), canonical_url=f"https://x.example/{n}",
                 first_seen_at=t) for n, t in enumerate(times)]
    for iid in ids:
        set_content(db, iid, text="text", status="ok")
    assert prune_content(db, older_than=cutoff) == 1
    old, at_cutoff, new = (get_item(db, i) for i in ids)
    assert old.content_text is None
    assert old.content_status == "ok"
    assert at_cutoff.content_text == "text" and new.content_text == "text"
    assert prune_content(db, older_than=cutoff) == 0


def test_writes_commit(db, env):
    sid, st, rid = env
    iid = _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/1")
    assert db.in_transaction is False
    assert _item(db, sid, st, rid, guid="a", canonical_url="https://x.example/1") is None
    assert db.in_transaction is False
    set_content(db, iid, text="body", status="ok")
    assert db.in_transaction is False
    prune_content(db, older_than=T0 + timedelta(days=1))
    assert db.in_transaction is False

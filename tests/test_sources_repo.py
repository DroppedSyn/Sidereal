"""Tests for ``src/sidereal/db/sources_repo.py``."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db.seed import seed_sources
from sidereal.db.sources_repo import (
    get_by_key,
    get_source,
    health,
    list_sources,
    record_broken,
    record_fetch_error,
    record_fetch_ok,
)
from sidereal.defaults import SourceSeed
from sidereal.timeutil import iso_z

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _add(db, key, *, enabled=True, options=None):
    seed_sources(db, [SourceSeed(
        key=key, name=key.upper(), kind="rss",
        url=f"https://{key}.example/feed", enabled=enabled,
        options=options or {},
    )])
    return get_by_key(db, key)


def test_list_sources_all_and_enabled_only(db):
    _add(db, "a")
    _add(db, "b", enabled=False)
    _add(db, "c")
    assert [r.key for r in list_sources(db)] == ["a", "b", "c"]
    assert [r.key for r in list_sources(db, enabled_only=True)] == ["a", "c"]
    assert list_sources(db)[1].enabled is False


def test_options_parsed(db):
    row = _add(db, "opts", options={"article_hosts": ["x.example"], "max_bytes": 5})
    assert row.options == {"article_hosts": ["x.example"], "max_bytes": 5}
    assert row.weight == 1.0
    assert row.max_items == 50
    assert row.consecutive_failures == 0
    assert row.etag is None


def test_get_by_key_and_get_source_missing(db):
    assert get_by_key(db, "nope") is None
    assert get_source(db, 999) is None
    row = _add(db, "x")
    assert get_source(db, row.id) == row


def test_fetch_error_increments(db):
    row = _add(db, "err")
    t1 = T0 + timedelta(minutes=1)
    t2 = T0 + timedelta(minutes=2)
    record_fetch_error(db, row.id, at=t1, error="first")
    record_fetch_error(db, row.id, at=t2, error="second")
    row = get_by_key(db, "err")
    assert row.consecutive_failures == 2
    assert row.last_error == "second"
    assert row.last_fetch_at == iso_z(t2)
    assert row.last_ok_at is None


def test_fetch_ok_resets_failures(db):
    row = _add(db, "reset")
    t1 = T0 + timedelta(minutes=1)
    t2 = T0 + timedelta(minutes=2)
    record_fetch_error(db, row.id, at=t1, error="first")
    record_fetch_error(db, row.id, at=t2, error="second")
    etag = '"e1"'
    lm = "Wed, 18 Nov 2026 10:00:00 GMT"
    record_fetch_ok(db, row.id, at=T0, etag=etag, last_modified=lm, entry_count=5)
    row = get_by_key(db, "reset")
    assert row.consecutive_failures == 0
    assert row.last_ok_at == row.last_fetch_at == iso_z(T0)
    assert row.etag == etag
    assert row.last_modified == lm
    assert row.last_error == "second"


def test_zero_item_runs_count_and_reset(db):
    row = _add(db, "zero")
    record_fetch_ok(db, row.id, at=T0, etag=None, last_modified=None, entry_count=0)
    row = get_by_key(db, "zero")
    assert row.zero_item_runs == 1
    record_fetch_ok(db, row.id, at=T0 + timedelta(minutes=1), etag=None,
                    last_modified=None, entry_count=0)
    row = get_by_key(db, "zero")
    assert row.zero_item_runs == 2
    record_fetch_ok(db, row.id, at=T0 + timedelta(minutes=2), etag=None,
                    last_modified=None, entry_count=None)
    row = get_by_key(db, "zero")
    assert row.zero_item_runs == 2
    record_fetch_ok(db, row.id, at=T0 + timedelta(minutes=3), etag=None,
                    last_modified=None, entry_count=3)
    row = get_by_key(db, "zero")
    assert row.zero_item_runs == 0


def test_record_unknown_source_raises(db):
    _add(db, "ok")
    with pytest.raises(KeyError):
        record_fetch_ok(db, 999, at=T0, etag=None, last_modified=None, entry_count=1)
    with pytest.raises(KeyError):
        record_fetch_error(db, 999, at=T0, error="boom")


def test_record_broken_prefix(db):
    row = _add(db, "broken")
    record_broken(db, row.id, at=T0, error="not a feed")
    row = get_by_key(db, "broken")
    assert row.last_error == "broken: not a feed"
    assert row.consecutive_failures == 1


def test_writes_commit(db):
    row = _add(db, "commit")
    record_fetch_ok(db, row.id, at=T0, etag=None, last_modified=None, entry_count=0)
    assert db.in_transaction is False
    record_fetch_error(db, row.id, at=T0, error="boom")
    assert db.in_transaction is False
    record_broken(db, row.id, at=T0, error="not a feed")
    assert db.in_transaction is False


def test_fetch_ok_none_overwrites_validators(db):
    row = _add(db, "validators")
    record_fetch_ok(db, row.id, at=T0, etag='"e1"', last_modified="x", entry_count=1)
    record_fetch_ok(db, row.id, at=T0, etag=None, last_modified=None, entry_count=1)
    row = get_by_key(db, "validators")
    assert row.etag is None
    assert row.last_modified is None


def test_fetch_error_keeps_ok_state(db):
    row = _add(db, "keep")
    record_fetch_ok(db, row.id, at=T0, etag='"e1"', last_modified="lm", entry_count=0)
    record_fetch_error(db, row.id, at=T0 + timedelta(minutes=1), error="boom")
    row = get_by_key(db, "keep")
    assert row.last_ok_at == iso_z(T0)
    assert row.etag == '"e1"'
    assert row.last_modified == "lm"
    assert row.zero_item_runs == 1


# --- health tests (pure: rows built with dataclasses.replace) ---

RECENT = T0 - timedelta(days=1)


def _row(db, **changes):
    base = replace(_add(db, "h"), created_at=iso_z(T0 - timedelta(days=30)))
    return replace(base, **changes)


def _health(row, last_new_item_at=RECENT):
    return health(row, now=T0, last_new_item_at=last_new_item_at)


def test_health_ok(db):
    assert _health(_row(db)) == "ok"


def test_health_failing_threshold(db):
    row = _row(db)
    assert _health(replace(row, consecutive_failures=2)) == "ok"
    assert _health(replace(row, consecutive_failures=3)) == "failing"


def test_health_empty_threshold(db):
    row = _row(db)
    assert _health(replace(row, zero_item_runs=5)) == "ok"
    assert _health(replace(row, zero_item_runs=6)) == "empty"


def test_health_stale_threshold(db):
    row = _row(db)
    assert _health(row, T0 - timedelta(days=6, hours=23)) == "ok"
    assert _health(row, T0 - timedelta(days=7)) == "stale"


def test_health_stale_when_never_new(db):
    row = _row(db)
    assert _health(row, None) == "stale"
    assert _health(replace(row, created_at=iso_z(T0 - timedelta(days=2))), None) == "ok"
    assert _health(replace(row, created_at=iso_z(T0 - timedelta(days=6, hours=23))), None) == "ok"
    assert _health(replace(row, created_at=iso_z(T0 - timedelta(days=7))), None) == "stale"


def test_health_new_item_overrides_old_created_at(db):
    # created 30 days ago but a new item yesterday: ok, not stale
    assert _health(_row(db), RECENT) == "ok"


def test_health_broken(db):
    row = _row(db, last_error="broken: not a feed")
    assert _health(replace(row, consecutive_failures=1)) == "broken"
    assert _health(replace(row, consecutive_failures=0)) == "ok"
    assert _health(replace(row, consecutive_failures=1, last_error="HTTPError: 500")) == "ok"


def test_health_precedence(db):
    stale = T0 - timedelta(days=10)
    row = _row(db, consecutive_failures=3, last_error="broken: x", zero_item_runs=6)
    assert _health(row, stale) == "broken"
    row = replace(row, last_error="HTTPError")
    assert _health(row, stale) == "failing"
    row = replace(row, consecutive_failures=0)
    assert _health(row, stale) == "empty"
    row = replace(row, zero_item_runs=0)
    assert _health(row, stale) == "stale"

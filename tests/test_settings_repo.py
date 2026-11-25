"""db/settings_repo.py (M27): overrides, focus areas and sources round trips."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sidereal.db import focus_repo, settings_repo, sources_repo
from sidereal.db.seed import seed_sources
from sidereal.defaults import SourceSeed
from tests.factories import make_run, make_story

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
FOCUS = dict(name="Test area", tier="secondary", description="d" * 40, keywords=["a", "b"],
             enabled=True)
SRC = dict(name="Feed", kind="rss", url="https://feeds.example.com/x", enabled=True,
           weight=1.2, max_items=20, options={"article_hosts": ["example.com"]})


def test_overrides_round_trip(db):
    assert settings_repo.get_overrides(db) == {}
    settings_repo.set_override(db, "scoring", {"top_cap": 4, "kev_bonus": 10.5})
    settings_repo.set_override(db, "budget", {"max_run_minutes": 30})
    settings_repo.set_override(db, "scoring", {"top_cap": 5})
    assert settings_repo.get_overrides(db) == {"budget": {"max_run_minutes": 30},
                                               "scoring": {"top_cap": 5}}
    settings_repo.set_override(db, "budget", {})
    assert settings_repo.get_overrides(db) == {"scoring": {"top_cap": 5}}


def test_overrides_commit(db, settings):
    from sidereal.db.connect import connect

    settings_repo.set_override(db, "triage", {"keep_min": 1})
    other = connect(settings.db_path)
    try:
        assert settings_repo.get_overrides(other) == {"triage": {"keep_min": 1}}
    finally:
        other.close()


def test_focus_add_update_delete(db):
    settings_repo.add_focus_area(db, key="t-area", **FOCUS)
    with pytest.raises(settings_repo.KeyTaken):
        settings_repo.add_focus_area(db, key="t-area", **FOCUS)
    settings_repo.update_focus_area(db, "t-area", name="Renamed", tier="primary",
                                    description="e" * 50, keywords=["x"], enabled=False)
    (row,) = [f for f in focus_repo.list_focus_areas(db, enabled_only=False) if f.key == "t-area"]
    assert (row.name, row.tier, row.description, row.keywords, row.enabled) == (
        "Renamed", "primary", "e" * 50, ("x",), False)
    settings_repo.delete_focus_area(db, "t-area")
    assert focus_repo.list_focus_areas(db, enabled_only=False) == []
    with pytest.raises(KeyError):
        settings_repo.update_focus_area(db, "t-area", **FOCUS)
    with pytest.raises(KeyError):
        settings_repo.delete_focus_area(db, "t-area")


def test_source_add_and_update(db):
    sid = settings_repo.add_source(db, key="feed", at=NOW, **SRC)
    row = sources_repo.get_source(db, sid)
    assert (row.key, row.kind, row.url, row.weight, row.max_items, row.options,
            row.created_at) == ("feed", "rss", SRC["url"], 1.2, 20,
                                {"article_hosts": ["example.com"]}, "2026-07-14T08:00:00Z")
    with pytest.raises(settings_repo.KeyTaken):
        settings_repo.add_source(db, key="feed", at=NOW, **SRC)
    settings_repo.update_source(db, sid, name="New", url=SRC["url"], enabled=False, weight=0.5,
                                max_items=5, options={})
    row = sources_repo.get_source(db, sid)
    assert (row.name, row.enabled, row.weight, row.max_items, row.options, row.kind) == (
        "New", False, 0.5, 5, {}, "rss")
    with pytest.raises(KeyError):
        settings_repo.update_source(db, 999, name="x", url="https://e.com/", enabled=True,
                                    weight=1.0, max_items=1, options={})


def test_url_change_clears_validators(db):
    seed_sources(db, [SourceSeed(key="s", name="S", kind="rss", url="https://a.example.com/")])
    row = sources_repo.get_by_key(db, "s")
    sources_repo.record_fetch_ok(db, row.id, at=NOW, etag='"e1"', last_modified="Mon",
                                 entry_count=3)
    keep = dict(name="S", enabled=True, weight=1.0, max_items=50, options={})
    settings_repo.update_source(db, row.id, url="https://a.example.com/", **keep)
    row = sources_repo.get_source(db, row.id)
    assert (row.etag, row.last_modified) == ('"e1"', "Mon")
    settings_repo.update_source(db, row.id, url="https://b.example.com/", **keep)
    row = sources_repo.get_source(db, row.id)
    assert (row.url, row.etag, row.last_modified) == ("https://b.example.com/", None, None)


def test_delete_source_and_item_count(db):
    sid = settings_repo.add_source(db, key="empty", at=NOW, **SRC)
    assert settings_repo.source_item_count(db, sid) == 0
    settings_repo.delete_source(db, sid)
    assert sources_repo.get_source(db, sid) is None
    with pytest.raises(KeyError):
        settings_repo.delete_source(db, sid)
    run = make_run(db, at=NOW)
    make_story(db, run_id=run, first_seen=NOW, tz="UTC", sources=("bleepingcomputer",))
    busy = sources_repo.get_by_key(db, "bleepingcomputer")
    assert settings_repo.source_item_count(db, busy.id) == 1

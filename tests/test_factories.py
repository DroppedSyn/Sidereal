"""Tests for ``tests/factories.py`` (demo data builder)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sidereal.db.assessments_repo import get_assessment
from sidereal.db.connect import connect
from sidereal.db.digests_repo import list_day_digests
from sidereal.db.items_repo import items_for_story
from sidereal.db.migrations import apply_migrations
from sidereal.db.runs_repo import get_run
from sidereal.db.sources_repo import get_by_key
from sidereal.db.stories_repo import get_story
from sidereal.timeutil import day_key, parse_iso_z
from tests.factories import (
    DEMO_TZ,
    ensure_source,
    main,
    make_run,
    make_story,
    seed_demo,
)

T0 = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _rows(db, sql):
    return [tuple(r) for r in db.execute(sql).fetchall()]


def test_ensure_source_idempotent(db):
    a = ensure_source(db, "bleepingcomputer")
    b = ensure_source(db, "bleepingcomputer", name="Other")
    assert a == b
    assert get_by_key(db, "bleepingcomputer").name == "BleepingComputer"
    assert get_by_key(db, "bleepingcomputer").weight == 1.0


def test_ensure_source_defaults_and_overrides(db):
    ensure_source(db, "custom-x")
    ensure_source(db, "w-src", name="W", weight=1.5)
    assert get_by_key(db, "custom-x").name == "custom-x"
    assert get_by_key(db, "custom-x").weight == 1.0
    assert get_by_key(db, "w-src").name == "W"
    assert get_by_key(db, "w-src").weight == 1.5
    assert get_by_key(db, "hn") is None
    ensure_source(db, "hn")
    assert get_by_key(db, "hn").weight == 0.7
    assert get_by_key(db, "hn").name == "Hacker News"


def test_make_run_finished(db):
    rid = make_run(db, at=T0)
    run = get_run(db, rid)
    assert (run.status, run.started_at, run.finished_at, run.stats, run.error) == (
        "ok", "2026-07-14T12:00:00Z", "2026-07-14T12:05:00Z", {}, None)


def test_make_run_running_and_failed(db):
    r1 = make_run(db, at=T0, status="running")
    assert get_run(db, r1).status == "running"
    assert get_run(db, r1).finished_at is None
    r2 = make_run(db, at=T0, status="failed", error="boom")
    assert get_run(db, r2).status == "failed"
    assert get_run(db, r2).error == "boom"


def test_make_story_defaults(db):
    rid = make_run(db, at=T0)
    sid = make_story(db, run_id=rid, first_seen=T0)
    s = get_story(db, sid)
    assert (s.day, s.state, s.bucket, s.score, s.title) == (
        "2026-07-14", "assessed", "relevant", 60.0, "Demo story")
    items = items_for_story(db, sid)
    assert len(items) == 1
    assert s.lead_item_id == items[0].id
    assert items[0].url == f"https://bleepingcomputer.example/{sid}/0"
    assert items[0].published_at == "2026-07-14T11:00:00Z"
    assert items[0].excerpt == "Original excerpt."
    a = get_assessment(db, sid)
    assert (a.summary, a.why, a.tags) == ("AI summary.", "Why it matters.", ["azure"])
    # raw mirrors the runner: the assess reply plus the resolved focus.
    assert a.raw == {"relevance": 2, "urgency": 2, "actionability": 2, "novelty": 2,
                     "focus": "azure-networking", "tags": ["azure"],
                     "exploited_in_wild": False, "summary": "AI summary.",
                     "why": "Why it matters."}


def test_make_story_exploited_flag_in_raw(db):
    rid = make_run(db, at=T0)
    sid = make_story(db, run_id=rid, first_seen=T0, flags={"exploited": True})
    assert get_assessment(db, sid).raw["exploited_in_wild"] is True
    assert get_story(db, sid).flags == {"exploited": True}


def test_make_story_day_uses_tz(db):
    rid = make_run(db, at=T0)
    late = datetime(2026, 7, 13, 23, 30, tzinfo=UTC)
    assert get_story(db, make_story(db, run_id=rid, first_seen=late)).day == "2026-07-14"
    assert get_story(db, make_story(db, run_id=rid, first_seen=late, tz="UTC")).day == "2026-07-13"


def test_make_story_sources_and_urls(db):
    rid = make_run(db, at=T0)
    sid = make_story(db, run_id=rid, first_seen=T0, sources=("a-src", "b-src"),
                     urls=("https://x.example/1", "javascript:alert(1)"))
    assert [i.url for i in items_for_story(db, sid)] == [
        "https://x.example/1", "javascript:alert(1)"]
    assert get_story(db, sid).lead_item_id == items_for_story(db, sid)[0].id


def test_urls_must_match_sources(db):
    rid = make_run(db, at=T0)
    with pytest.raises(ValueError, match="urls must match sources"):
        make_story(db, run_id=rid, first_seen=T0, sources=("a-src",), urls=())
    assert _rows(db, "SELECT COUNT(*) FROM stories") == [(0,)]


def test_assess_failed_story(db):
    rid = make_run(db, at=T0)
    sid = make_story(db, run_id=rid, first_seen=T0, state="assess_failed", bucket="side",
                     score=None)
    assert get_assessment(db, sid) is None
    s = get_story(db, sid)
    assert (s.state, s.bucket, s.score) == ("assess_failed", "side", None)


def test_filtered_story(db):
    rid = make_run(db, at=T0)
    sid = make_story(db, run_id=rid, first_seen=T0, state="filtered", bucket=None)
    s = get_story(db, sid)
    assert (s.state, s.bucket, s.score) == ("filtered", None, None)
    assert get_assessment(db, sid) is None


def test_seed_demo_counts(db):
    assert seed_demo(db) == {"runs": 16, "stories": 30, "digests": 2}
    assert _rows(db, "SELECT COUNT(*) FROM runs") == [(16,)]
    assert _rows(db, "SELECT COUNT(*) FROM stories") == [(30,)]
    assert _rows(db, "SELECT COUNT(*) FROM day_digests") == [(2,)]


def test_seed_demo_days(db):
    seed_demo(db)
    assert _rows(db, "SELECT day, COUNT(*) FROM stories GROUP BY day ORDER BY day") == [
        ("2026-07-12", 10), ("2026-07-13", 12), ("2026-07-14", 8)]


def test_seed_demo_buckets(db):
    seed_demo(db)
    assert _rows(db, "SELECT bucket, state, COUNT(*) FROM stories GROUP BY bucket, state"
                     " ORDER BY bucket, state") == [
        ("drop", "assessed", 5), ("relevant", "assessed", 10), ("side", "assess_failed", 5),
        ("side", "assessed", 5), ("top", "assessed", 5)]


def test_seed_demo_run_statuses(db):
    seed_demo(db)
    assert _rows(db, "SELECT status, COUNT(*) FROM runs GROUP BY status ORDER BY status") == [
        ("failed", 1), ("ok", 14), ("partial", 1)]
    assert _rows(db, "SELECT status, started_at, error FROM runs WHERE status != 'ok'"
                     " ORDER BY id") == [
        ("failed", "2026-07-12T20:00:00Z", "demo failure"),
        ("partial", "2026-07-13T12:00:00Z", None)]


def test_seed_demo_digests(db):
    seed_demo(db)
    digests = list_day_digests(db)
    assert [d.day for d in digests] == ["2026-07-13", "2026-07-12"]
    assert digests[0].story_ids == [r[0] for r in _rows(
        db, "SELECT id FROM stories WHERE day = '2026-07-13'"
            " AND bucket IN ('top', 'relevant') ORDER BY id")]
    assert len(digests[0].story_ids) == 6


def test_seed_demo_nothing_after_now(db):
    seed_demo(db)
    assert _rows(db, "SELECT MAX(started_at) FROM runs") == [("2026-07-14T12:00:00Z",)]
    assert _rows(db, "SELECT MAX(first_seen_at) FROM stories") == [("2026-07-14T12:11:00Z",)]


def test_seed_demo_days_match_first_seen(db):
    seed_demo(db)
    rows = _rows(db, "SELECT day, first_seen_at FROM stories")
    assert len(rows) == 30
    for day, first_seen_at in rows:
        assert day_key(parse_iso_z(first_seen_at), DEMO_TZ) == day


def test_seed_demo_other_now(db):
    assert seed_demo(db, now=datetime(2026, 7, 14, 0, 30, tzinfo=UTC)) == {
        "runs": 13, "stories": 24, "digests": 2}


def test_seed_demo_run_exactly_at_now(db):
    assert seed_demo(db, now=T0) == {"runs": 16, "stories": 30, "digests": 2}


def test_seed_demo_ids_follow_time(db):
    seed_demo(db)
    by_time = _rows(db, "SELECT id FROM stories ORDER BY first_seen_at, id")
    assert by_time == _rows(db, "SELECT id FROM stories ORDER BY id")


def test_seed_demo_deterministic(tmp_path):
    a = connect(tmp_path / "a.db")
    b = connect(tmp_path / "b.db")
    try:
        for conn in (a, b):
            apply_migrations(conn)
            seed_demo(conn)
        sql = ("SELECT s.id, s.title, s.day, s.first_seen_at, s.bucket, s.score, i.url"
               " FROM stories s JOIN items i ON i.story_id = s.id ORDER BY i.id")
        assert _rows(a, sql) == _rows(b, sql)
        assert len(_rows(a, sql)) == 40
    finally:
        a.close()
        b.close()


def test_main_seeds_new_file(tmp_path, capsys):
    path = tmp_path / "demo.db"
    assert main(["--seed-demo", str(path)]) == 0
    assert capsys.readouterr().out == f"seeded {path}: 16 runs, 30 stories, 2 digests\n"
    conn = connect(path)
    try:
        assert _rows(conn, "SELECT COUNT(*) FROM stories") == [(30,)]
    finally:
        conn.close()


def test_main_refuses_existing_file(tmp_path, capsys):
    path = tmp_path / "demo.db"
    path.write_text("x")
    assert main(["--seed-demo", str(path)]) == 2
    assert "refusing to overwrite" in capsys.readouterr().err
    assert path.read_text() == "x"

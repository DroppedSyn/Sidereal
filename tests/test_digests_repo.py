"""Tests for ``src/sidereal/db/digests_repo.py``."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sidereal.db.digests_repo import (
    DayDigestRow,
    get_day_digest,
    list_day_digests,
    save_day_digest,
)

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _save(db, day="2026-11-20", *, overview="ov", headline="hl", story_ids=(3, 1, 2),
          model="m1", run_id=7, at=T0):
    save_day_digest(db, day, overview=overview, headline=headline, story_ids=story_ids,
                    model=model, run_id=run_id, at=at)


def test_save_and_get_round_trip(db):
    _save(db)
    row = get_day_digest(db, "2026-11-20")
    assert row == DayDigestRow(
        day="2026-11-20",
        overview="ov",
        headline="hl",
        story_ids=[3, 1, 2],
        model="m1",
        run_id=7,
        updated_at="2026-11-20T12:00:00Z",
    )


def test_get_missing_is_none(db):
    assert get_day_digest(db, "2026-11-20") is None


def test_upsert_replaces_every_field(db):
    _save(db)
    _save(
        db,
        overview="ov2",
        headline="hl2",
        story_ids=[9],
        model="m2",
        run_id=8,
        at=T0 + timedelta(hours=1),
    )
    row = get_day_digest(db, "2026-11-20")
    assert row == DayDigestRow(
        day="2026-11-20",
        overview="ov2",
        headline="hl2",
        story_ids=[9],
        model="m2",
        run_id=8,
        updated_at="2026-11-20T13:00:00Z",
    )
    assert db.execute("SELECT COUNT(*) FROM day_digests").fetchone()[0] == 1


def test_days_are_independent(db):
    _save(db, "2026-11-20", overview="a")
    _save(db, "2026-11-21", overview="b")
    assert get_day_digest(db, "2026-11-20").overview == "a"
    assert get_day_digest(db, "2026-11-21").overview == "b"


def test_empty_story_ids(db):
    _save(db, story_ids=[])
    assert get_day_digest(db, "2026-11-20").story_ids == []


def test_story_ids_order_kept(db):
    _save(db, story_ids=(5, 2, 9))
    assert get_day_digest(db, "2026-11-20").story_ids == [5, 2, 9]


def test_save_commits(db):
    _save(db)
    assert db.in_transaction is False


def test_updated_at_utc_z(db):
    _save(
        db,
        at=datetime(2026, 11, 20, 13, 30, 5, tzinfo=timezone(timedelta(hours=1))),
    )
    assert get_day_digest(db, "2026-11-20").updated_at == "2026-11-20T12:30:05Z"


@pytest.mark.parametrize(
    "day",
    ["2026-1-20", "20-11-2026", "2026-11-20T00:00", "", "2026/11/20"],
)
def test_bad_day_rejected(db, day):
    with pytest.raises(ValueError, match="day must be YYYY-MM-DD"):
        _save(db, day)
    with pytest.raises(ValueError, match="day must be YYYY-MM-DD"):
        get_day_digest(db, day)
    assert db.execute("SELECT COUNT(*) FROM day_digests").fetchone()[0] == 0


def test_naive_time_rejected(db):
    with pytest.raises(ValueError, match="naive"):
        save_day_digest(
            db,
            "2026-11-20",
            overview="o",
            headline="h",
            story_ids=[],
            model="m",
            run_id=1,
            at=datetime(2026, 11, 20, 12, 0),
        )


def test_list_newest_first(db):
    _save(db, "2026-11-18")
    _save(db, "2026-11-20")
    _save(db, "2026-11-19")
    assert [r.day for r in list_day_digests(db)] == [
        "2026-11-20",
        "2026-11-19",
        "2026-11-18",
    ]


def test_list_empty(db):
    assert list_day_digests(db) == []


def test_list_limit(db):
    _save(db, "2026-11-18")
    _save(db, "2026-11-20")
    _save(db, "2026-11-19")
    assert [r.day for r in list_day_digests(db, limit=2)] == [
        "2026-11-20",
        "2026-11-19",
    ]
    assert [r.day for r in list_day_digests(db, limit=1)] == ["2026-11-20"]


def test_list_before_is_exclusive(db):
    _save(db, "2026-11-18")
    _save(db, "2026-11-20")
    _save(db, "2026-11-19")
    assert [r.day for r in list_day_digests(db, before="2026-11-20")] == [
        "2026-11-19",
        "2026-11-18",
    ]
    assert [r.day for r in list_day_digests(db, before="2026-11-19", limit=5)] == [
        "2026-11-18",
    ]
    assert list_day_digests(db, before="2026-11-18") == []


def test_list_returns_rows(db):
    _save(db)
    assert list_day_digests(db) == [get_day_digest(db, "2026-11-20")]


def test_list_bad_limit(db):
    with pytest.raises(ValueError, match="limit must be >= 1"):
        list_day_digests(db, limit=0)


def test_list_bad_before(db):
    with pytest.raises(ValueError, match="day must be YYYY-MM-DD"):
        list_day_digests(db, before="2026-11")


def test_row_is_frozen(db):
    _save(db)
    row = get_day_digest(db, "2026-11-20")
    with pytest.raises(dataclasses.FrozenInstanceError, match="overview"):
        row.overview = "x"


def test_list_before_respects_limit(db):
    _save(db, "2026-11-18")
    _save(db, "2026-11-20")
    _save(db, "2026-11-19")
    assert [r.day for r in list_day_digests(db, before="2026-11-21", limit=2)] == [
        "2026-11-20",
        "2026-11-19",
    ]

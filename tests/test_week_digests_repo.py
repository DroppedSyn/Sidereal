"""db/week_digests_repo.py (M29): upsert, read, list newest first."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db import week_digests_repo as repo
from tests.pipeline_helpers import seeded_db, start

AT = datetime(2026, 11, 29, 20, 0, tzinfo=UTC)


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def _save(conn, week, *, at=AT, ids=(1, 2), overview="Overview.", headline="Headline"):
    repo.save_week_digest(conn, week, overview=overview, headline=headline, story_ids=ids,
                          model="m", run_id=start(conn), at=at)


def test_save_and_get(conn):
    _save(conn, "2026-W53", ids=(5, 3))
    row = repo.get_week_digest(conn, "2026-W53")
    assert (row.week, row.start_day, row.end_day, row.overview, row.headline, row.story_ids,
            row.model) == ("2026-W53", "2026-12-28", "2027-01-03", "Overview.", "Headline",
                           [5, 3], "m")
    assert row.created_at == row.updated_at == "2026-11-29T20:00:00Z"
    assert repo.get_week_digest(conn, "2026-W52") is None


def test_upsert_replaces_fields_and_keeps_created_at(conn):
    _save(conn, "2026-W48")
    _save(conn, "2026-W48", at=AT + timedelta(days=1), ids=(9,), overview="New.",
          headline="New headline")
    row = repo.get_week_digest(conn, "2026-W48")
    assert (row.overview, row.headline, row.story_ids) == ("New.", "New headline", [9])
    assert (row.created_at, row.updated_at) == ("2026-11-29T20:00:00Z", "2026-11-30T20:00:00Z")
    assert len(repo.list_week_digests(conn)) == 1


def test_list_newest_first_with_exclusive_before_across_years(conn):
    for week in ("2026-W52", "2027-W01", "2026-W53", "2026-W09"):
        _save(conn, week)
    assert [r.week for r in repo.list_week_digests(conn)] == [
        "2027-W01", "2026-W53", "2026-W52", "2026-W09"]
    assert [r.week for r in repo.list_week_digests(conn, before="2027-W01", limit=2)] == [
        "2026-W53", "2026-W52"]


@pytest.mark.parametrize("bad", ["2025-W53", "2026-48", "x"])
def test_bad_week_raises_before_sql(conn, bad):
    with pytest.raises(ValueError):
        repo.get_week_digest(conn, bad)
    with pytest.raises(ValueError):
        _save(conn, bad)
    with pytest.raises(ValueError):
        repo.list_week_digests(conn, before=bad)


def test_limit_must_be_positive(conn):
    with pytest.raises(ValueError):
        repo.list_week_digests(conn, limit=0)

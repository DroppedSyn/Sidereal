"""Repository for the ``week_digests`` table (one LLM overview per ISO week, M29)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sidereal.timeutil import iso_z
from sidereal.weeks import week_days, week_start


@dataclass(frozen=True)
class WeekDigestRow:
    week: str
    start_day: str
    end_day: str
    overview: str
    headline: str
    story_ids: list[int]
    model: str
    run_id: int
    created_at: str
    updated_at: str


def _check_week(week: str) -> None:
    week_start(week)  # ValueError for anything that is not a real ISO week


def _row(row: sqlite3.Row) -> WeekDigestRow:
    return WeekDigestRow(
        week=row["week"], start_day=row["start_day"], end_day=row["end_day"],
        overview=row["overview"], headline=row["headline"],
        story_ids=json.loads(row["story_ids_json"]), model=row["model"],
        run_id=row["run_id"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def save_week_digest(conn: sqlite3.Connection, week: str, *, overview: str, headline: str,
                     story_ids: Sequence[int], model: str, run_id: int,
                     at: datetime) -> None:
    """Upsert the digest for *week*; ``created_at`` is kept from the first save."""
    _check_week(week)
    days = week_days(week)
    at_str = iso_z(at)
    with conn:
        conn.execute(
            "INSERT INTO week_digests (week, start_day, end_day, overview, headline,"
            " story_ids_json, model, run_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(week) DO UPDATE SET"
            " overview = excluded.overview, headline = excluded.headline,"
            " story_ids_json = excluded.story_ids_json, model = excluded.model,"
            " run_id = excluded.run_id, updated_at = excluded.updated_at",
            (week, days[0], days[-1], overview, headline,
             json.dumps([int(i) for i in story_ids]), model, run_id, at_str, at_str),
        )


def get_week_digest(conn: sqlite3.Connection, week: str) -> WeekDigestRow | None:
    _check_week(week)
    row = conn.execute("SELECT * FROM week_digests WHERE week = ?", (week,)).fetchone()
    return None if row is None else _row(row)


def list_week_digests(conn: sqlite3.Connection, *, limit: int = 52,
                      before: str | None = None) -> list[WeekDigestRow]:
    """Newest week first; ``before`` (a week key) is exclusive. Keys sort as text because
    the year and week are zero-padded."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")
    if before is not None:
        _check_week(before)
        rows = conn.execute(
            "SELECT * FROM week_digests WHERE week < ? ORDER BY week DESC LIMIT ?",
            (before, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM week_digests ORDER BY week DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r) for r in rows]

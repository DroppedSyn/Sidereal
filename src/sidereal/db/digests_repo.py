"""Repository for the ``day_digests`` table (one LLM overview per day, plan §7.3)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sidereal.timeutil import iso_z

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class DayDigestRow:
    day: str
    overview: str
    headline: str
    story_ids: list[int]
    model: str
    run_id: int
    updated_at: str


def _check_day(day: str) -> None:
    if not isinstance(day, str) or not _DAY.fullmatch(day):
        raise ValueError(f"day must be YYYY-MM-DD, got {day!r}")


def _row(row: sqlite3.Row | None) -> DayDigestRow | None:
    if row is None:
        return None
    return DayDigestRow(
        day=row["day"],
        overview=row["overview"],
        headline=row["headline"],
        story_ids=json.loads(row["story_ids_json"]),
        model=row["model"],
        run_id=row["run_id"],
        updated_at=row["updated_at"],
    )


def save_day_digest(
    conn: sqlite3.Connection,
    day: str,
    *,
    overview: str,
    headline: str,
    story_ids: Sequence[int],
    model: str,
    run_id: int,
    at: datetime,
) -> None:
    """Upsert the digest for ``day``."""
    _check_day(day)
    story_ids_json = json.dumps([int(i) for i in story_ids])
    at_str = iso_z(at)

    with conn:
        conn.execute(
            "INSERT INTO day_digests"
            " (day, overview, headline, story_ids_json, model, run_id, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(day) DO UPDATE SET"
            " overview = excluded.overview,"
            " headline = excluded.headline,"
            " story_ids_json = excluded.story_ids_json,"
            " model = excluded.model,"
            " run_id = excluded.run_id,"
            " updated_at = excluded.updated_at",
            (day, overview, headline, story_ids_json, model, run_id, at_str),
        )


def get_day_digest(conn: sqlite3.Connection, day: str) -> DayDigestRow | None:
    """Return the digest for ``day``, or ``None``."""
    _check_day(day)
    return _row(
        conn.execute(
            "SELECT * FROM day_digests WHERE day = ?", (day,)
        ).fetchone()
    )


def list_day_digests(
    conn: sqlite3.Connection,
    *,
    limit: int = 60,
    before: str | None = None,
) -> list[DayDigestRow]:
    """Return digests newest-first; ``before`` is exclusive."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")
    if before is not None:
        _check_day(before)
        rows = conn.execute(
            "SELECT * FROM day_digests WHERE day < ? ORDER BY day DESC LIMIT ?",
            (before, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM day_digests ORDER BY day DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row(r) for r in rows if r is not None]

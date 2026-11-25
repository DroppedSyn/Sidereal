"""Repository for the ``sources`` table."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sidereal.timeutil import iso_z, parse_iso_z

HEALTH_STATUSES = ("ok", "stale", "failing", "empty", "broken")
FAILING_AFTER = 3
EMPTY_AFTER = 6
STALE_AFTER = timedelta(days=7)
BROKEN_PREFIX = "broken: "


@dataclass(frozen=True)
class SourceRow:
    id: int
    key: str
    name: str
    kind: str
    url: str
    enabled: bool
    weight: float
    max_items: int
    options: dict[str, Any]
    etag: str | None
    last_modified: str | None
    last_fetch_at: str | None
    last_ok_at: str | None
    last_error: str | None
    consecutive_failures: int
    zero_item_runs: int
    created_at: str


def _row(row: sqlite3.Row | None) -> SourceRow | None:
    if row is None:
        return None
    return SourceRow(
        id=row["id"],
        key=row["key"],
        name=row["name"],
        kind=row["kind"],
        url=row["url"],
        enabled=bool(row["enabled"]),
        weight=row["weight"],
        max_items=row["max_items"],
        options=json.loads(row["options_json"]),
        etag=row["etag"],
        last_modified=row["last_modified"],
        last_fetch_at=row["last_fetch_at"],
        last_ok_at=row["last_ok_at"],
        last_error=row["last_error"],
        consecutive_failures=row["consecutive_failures"],
        zero_item_runs=row["zero_item_runs"],
        created_at=row["created_at"],
    )


def list_sources(conn: sqlite3.Connection, *, enabled_only: bool = False) -> list[SourceRow]:
    """Return all sources ordered by ``id``. With ``enabled_only=True`` only enabled rows."""
    if enabled_only:
        rows = conn.execute(
            "SELECT * FROM sources WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    return [_row(r) for r in rows]


def get_source(conn: sqlite3.Connection, source_id: int) -> SourceRow | None:
    """Return the source with the given ``id``, or ``None``."""
    return _row(conn.execute(
        "SELECT * FROM sources WHERE id = ?", (source_id,)
    ).fetchone())


def get_by_key(conn: sqlite3.Connection, key: str) -> SourceRow | None:
    """Return the source with the given ``key``, or ``None``."""
    return _row(conn.execute(
        "SELECT * FROM sources WHERE key = ?", (key,)
    ).fetchone())


def record_fetch_ok(conn: sqlite3.Connection, source_id: int,
                    *, at: datetime,
                    etag: str | None, last_modified: str | None,
                    entry_count: int | None) -> None:
    """Mark a successful fetch. Unknown ``source_id`` raises ``KeyError``.

    ``entry_count``: 0 counts a zero-entry run, > 0 resets the count, None (HTTP 304) leaves it.
    ``last_error`` is kept as history.
    """
    at_str = iso_z(at)
    with conn:
        cur = conn.execute(
            "UPDATE sources SET last_fetch_at = ?, last_ok_at = ?,"
            " consecutive_failures = 0, etag = ?, last_modified = ?,"
            " zero_item_runs = CASE WHEN ? IS NULL THEN zero_item_runs"
            " WHEN ? = 0 THEN zero_item_runs + 1 ELSE 0 END"
            " WHERE id = ?",
            (at_str, at_str, etag, last_modified, entry_count, entry_count, source_id),
        )
    if cur.rowcount == 0:
        raise KeyError(source_id)


def record_fetch_error(conn: sqlite3.Connection, source_id: int,
                       *, at: datetime, error: str) -> None:
    """Mark a failed fetch. Unknown ``source_id`` raises ``KeyError``."""
    with conn:
        cur = conn.execute(
            "UPDATE sources SET last_fetch_at = ?, last_error = ?,"
            " consecutive_failures = consecutive_failures + 1"
            " WHERE id = ?",
            (iso_z(at), error, source_id),
        )
    if cur.rowcount == 0:
        raise KeyError(source_id)


def record_broken(conn: sqlite3.Connection, source_id: int,
                  *, at: datetime, error: str) -> None:
    """Same as ``record_fetch_error`` but prefixes the error with ``broken: ``."""
    record_fetch_error(conn, source_id, at=at, error=BROKEN_PREFIX + error)


def last_item_times(conn: sqlite3.Connection) -> dict[int, datetime]:
    """``{source_id: newest item first_seen_at}`` for sources with any item (health input)."""
    rows = conn.execute(
        "SELECT source_id, max(first_seen_at) AS at FROM items GROUP BY source_id"
    ).fetchall()
    return {r["source_id"]: parse_iso_z(r["at"]) for r in rows}


def health(row: SourceRow, *, now: datetime,
           last_new_item_at: datetime | None) -> str:
    """Pure health classification. First matching rule wins."""
    if (row.consecutive_failures >= 1
            and row.last_error is not None
            and row.last_error.startswith(BROKEN_PREFIX)):
        return "broken"
    if row.consecutive_failures >= FAILING_AFTER:
        return "failing"
    if row.zero_item_runs >= EMPTY_AFTER:
        return "empty"
    if last_new_item_at is not None:
        if now - last_new_item_at >= STALE_AFTER:
            return "stale"
    else:
        created = parse_iso_z(row.created_at)
        if now - created >= STALE_AFTER:
            return "stale"
    return "ok"

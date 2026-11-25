"""Repository for the ``runs`` table."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sidereal.timeutil import iso_z

TRIGGERS = ("timer", "manual", "catchup")
FINAL_STATUSES = ("ok", "partial", "failed", "skipped")
COMPLETED_STATUSES = ("ok", "partial")
INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class RunRow:
    id: int
    started_at: str
    finished_at: str | None
    trigger: str
    status: str
    stats: dict[str, Any]
    error: str | None


def _row(row: sqlite3.Row | None) -> RunRow | None:
    if row is None:
        return None
    return RunRow(
        id=row["id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        trigger=row["trigger"],
        status=row["status"],
        stats=json.loads(row["stats_json"]),
        error=row["error"],
    )


def start_run(conn: sqlite3.Connection, *, trigger: str, at: datetime) -> int:
    """Insert a new ``running`` run. Returns the new id."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger: {trigger!r}")
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, trigger, status, stats_json)"
            " VALUES (?, ?, 'running', '{}')",
            (iso_z(at), trigger),
        )
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, *,
               status: str, stats: Mapping[str, Any],
               at: datetime, error: str | None = None) -> None:
    """Finalise a run. Unknown ``run_id`` raises ``KeyError``."""
    if status not in FINAL_STATUSES:
        raise ValueError(f"invalid status: {status!r}")
    with conn:
        cur = conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?,"
            " stats_json = ?, error = ?"
            " WHERE id = ?",
            (status, iso_z(at), json.dumps(stats, sort_keys=True),
             error, run_id),
        )
    if cur.rowcount == 0:
        raise KeyError(run_id)


def mark_skipped(conn: sqlite3.Connection, *, trigger: str,
                 at: datetime, reason: str) -> int:
    """Insert a pre-finished ``skipped`` row. Returns the id."""
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger: {trigger!r}")
    now_str = iso_z(at)
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, finished_at, trigger, status,"
            " stats_json, error)"
            " VALUES (?, ?, ?, 'skipped', '{}', ?)",
            (now_str, now_str, trigger, reason),
        )
    return cur.lastrowid


def recover_stale(conn: sqlite3.Connection, *, at: datetime) -> int:
    """Mark every ``running`` row as ``failed``/``interrupted``. Returns count."""
    now_str = iso_z(at)
    with conn:
        cur = conn.execute(
            "UPDATE runs SET status = 'failed', error = ?, finished_at = ?"
            " WHERE status = 'running'",
            (INTERRUPTED, now_str),
        )
    return cur.rowcount


def get_run(conn: sqlite3.Connection, run_id: int) -> RunRow | None:
    """Return the run with the given ``id``, or ``None``."""
    return _row(conn.execute(
        "SELECT * FROM runs WHERE id = ?", (run_id,)
    ).fetchone())


def list_runs(conn: sqlite3.Connection, *,
              limit: int = 50,
              before_id: int | None = None) -> list[RunRow]:
    """Return newest-first runs, at most ``limit``, optionally before ``before_id``."""
    rows = conn.execute(
        "SELECT * FROM runs"
        " WHERE (? IS NULL OR id < ?)"
        " ORDER BY id DESC LIMIT ?",
        (before_id, before_id, limit),
    ).fetchall()
    return [_row(r) for r in rows]


def last_ok_run(conn: sqlite3.Connection) -> RunRow | None:
    """Return the newest completed run (ok or partial), or ``None``."""
    return _row(conn.execute(
        "SELECT * FROM runs"
        " WHERE status IN ('ok', 'partial')"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone())

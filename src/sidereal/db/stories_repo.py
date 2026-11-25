"""Repository for the ``stories`` table."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sidereal.timeutil import iso_z

STATES = ("new", "filtered", "triaged_out", "assessed", "assess_failed")
BUCKETS = ("top", "relevant", "side", "drop")


@dataclass(frozen=True)
class StoryRow:
    id: int
    lead_item_id: int | None
    title: str
    day: str
    first_seen_at: str
    last_seen_at: str
    first_run_id: int
    state: str
    filter_reason: str | None
    triage_relevance: int | None
    score: float | None
    bucket: str | None
    cve_ids: list[str]
    flags: dict[str, Any]


@dataclass(frozen=True)
class RecentStory:
    id: int
    title: str
    cve_ids: list[str]
    title_norms: list[str]


def _story_row(row: sqlite3.Row | None) -> StoryRow | None:
    if row is None:
        return None
    return StoryRow(
        id=row["id"],
        lead_item_id=row["lead_item_id"],
        title=row["title"],
        day=row["day"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        first_run_id=row["first_run_id"],
        state=row["state"],
        filter_reason=row["filter_reason"],
        triage_relevance=row["triage_relevance"],
        score=row["score"],
        bucket=row["bucket"],
        cve_ids=json.loads(row["cve_ids_json"]),
        flags=json.loads(row["flags_json"]),
    )


def create_story(conn: sqlite3.Connection, *,
                 title: str, day: str, first_seen_at: datetime,
                 first_run_id: int,
                 cve_ids: Sequence[str] = (),
                 flags: Mapping[str, Any] | None = None) -> int:
    """Create a new story in state ``'new'``. Returns the id."""
    cve_json = json.dumps(list(cve_ids))
    flags_json = json.dumps(dict(flags or {}), sort_keys=True)
    with conn:
        cur = conn.execute(
            "INSERT INTO stories (title, day, first_seen_at, last_seen_at,"
            " first_run_id, state, cve_ids_json, flags_json)"
            " VALUES (?, ?, ?, ?, ?, 'new', ?, ?)",
            (title, day, iso_z(first_seen_at), iso_z(first_seen_at),
             first_run_id, cve_json, flags_json),
        )
    return cur.lastrowid


def get_story(conn: sqlite3.Connection, story_id: int) -> StoryRow | None:
    """Return the story with the given ``id``, or ``None``."""
    return _story_row(conn.execute(
        "SELECT * FROM stories WHERE id = ?", (story_id,)
    ).fetchone())


def attach_item(conn: sqlite3.Connection, story_id: int, *,
                item_id: int, seen_at: datetime,
                cve_ids: Sequence[str] = ()) -> None:
    """Attach an item to a story. Sets ``lead_item_id`` only on first attach.
    Merges CVE IDs (existing followed by new, no duplicates).
    Unknown story → ``KeyError``."""
    with conn:
        row = conn.execute(
            "SELECT cve_ids_json FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
        if row is None:
            raise KeyError(story_id)
        merged = json.loads(row["cve_ids_json"])
        for cve in cve_ids:
            if cve not in merged:
                merged.append(cve)
        conn.execute(
            "UPDATE stories SET lead_item_id = COALESCE(lead_item_id, ?),"
            " last_seen_at = MAX(last_seen_at, ?), cve_ids_json = ?"
            " WHERE id = ?",
            (item_id, iso_z(seen_at), json.dumps(merged), story_id),
        )


def recent_stories(conn: sqlite3.Connection, *,
                   since: datetime) -> list[RecentStory]:
    """Stories (any state) with ``last_seen_at >= since``, ordered by id, each
    with its items' ``title_norm``s in item-id order. One query."""
    rows = conn.execute(
        "SELECT s.id, s.title, s.cve_ids_json, i.title_norm"
        " FROM stories s LEFT JOIN items i ON i.story_id = s.id"
        " WHERE s.last_seen_at >= ?"
        " ORDER BY s.id, i.id",
        (iso_z(since),),
    ).fetchall()
    out: list[RecentStory] = []
    for row in rows:
        if not out or out[-1].id != row["id"]:
            out.append(RecentStory(id=row["id"], title=row["title"],
                                   cve_ids=json.loads(row["cve_ids_json"]),
                                   title_norms=[]))
        if row["title_norm"] is not None:
            out[-1].title_norms.append(row["title_norm"])
    return out


def pending_stories(conn: sqlite3.Connection, *,
                    limit: int | None = None) -> list[StoryRow]:
    """Stories in state ``'new'``, oldest first (``first_seen_at, id``).
    ``limit=None`` → all."""
    rows = conn.execute(
        "SELECT * FROM stories WHERE state = 'new'"
        " ORDER BY first_seen_at, id LIMIT ?",
        (-1 if limit is None else limit,),
    ).fetchall()
    return [_story_row(r) for r in rows]


def set_state(conn: sqlite3.Connection, story_id: int, state: str, *,
              reason: str | None = None) -> None:
    """Set ``state`` and ``filter_reason``. Unknown id → ``KeyError``."""
    if state not in STATES:
        raise ValueError(f"invalid state: {state!r}")
    with conn:
        cur = conn.execute(
            "UPDATE stories SET state = ?, filter_reason = ?"
            " WHERE id = ?",
            (state, reason, story_id),
        )
    if cur.rowcount == 0:
        raise KeyError(story_id)


def set_triage(conn: sqlite3.Connection, story_id: int,
               relevance: int) -> None:
    """Set ``triage_relevance``. Unknown id → ``KeyError``."""
    if relevance not in (0, 1, 2, 3):
        raise ValueError(f"relevance must be 0..3, got {relevance!r}")
    with conn:
        cur = conn.execute(
            "UPDATE stories SET triage_relevance = ? WHERE id = ?",
            (relevance, story_id),
        )
    if cur.rowcount == 0:
        raise KeyError(story_id)


def set_score(conn: sqlite3.Connection, story_id: int, *,
              score: float | None, bucket: str) -> None:
    """Set ``score`` and ``bucket``. Unknown id → ``KeyError``."""
    if bucket not in BUCKETS:
        raise ValueError(f"invalid bucket: {bucket!r}")
    with conn:
        cur = conn.execute(
            "UPDATE stories SET score = ?, bucket = ? WHERE id = ?",
            (score, bucket, story_id),
        )
    if cur.rowcount == 0:
        raise KeyError(story_id)


def stories_for_day(conn: sqlite3.Connection, day: str) -> list[StoryRow]:
    """Stories for a ``day``, ordered by ``id``."""
    rows = conn.execute(
        "SELECT * FROM stories WHERE day = ? ORDER BY id", (day,),
    ).fetchall()
    return [_story_row(r) for r in rows]


def stories_since(conn: sqlite3.Connection, since: datetime) -> list[StoryRow]:
    """Stories with ``first_seen_at >= since`` (inclusive), ordered by
    ``first_seen_at, id``."""
    since_str = iso_z(since)
    rows = conn.execute(
        "SELECT * FROM stories WHERE first_seen_at >= ?"
        " ORDER BY first_seen_at, id",
        (since_str,),
    ).fetchall()
    return [_story_row(r) for r in rows]


def delete_dropped_before(conn: sqlite3.Connection, *,
                          before: datetime) -> int:
    """Delete stories first seen strictly before ``before`` that were dropped
    (bucket ``'drop'``) or filtered/triaged out, with their assessments and
    items. Returns the number of stories deleted."""
    cutoff = (iso_z(before),)
    with conn:
        conn.execute(
            "DELETE FROM assessments WHERE story_id IN (SELECT id FROM stories"
            " WHERE first_seen_at < ? AND (bucket = 'drop'"
            " OR state IN ('filtered', 'triaged_out')))",
            cutoff,
        )
        conn.execute(
            "DELETE FROM items WHERE story_id IN (SELECT id FROM stories"
            " WHERE first_seen_at < ? AND (bucket = 'drop'"
            " OR state IN ('filtered', 'triaged_out')))",
            cutoff,
        )
        cur = conn.execute(
            "DELETE FROM stories"
            " WHERE first_seen_at < ? AND (bucket = 'drop'"
            " OR state IN ('filtered', 'triaged_out'))",
            cutoff,
        )
    return cur.rowcount


def merge_flags(conn: sqlite3.Connection, story_id: int,
                flags: Mapping[str, Any]) -> None:
    """Merge ``flags`` into ``flags_json`` (given keys overwrite). Unknown id → ``KeyError``."""
    with conn:
        row = conn.execute(
            "SELECT flags_json FROM stories WHERE id = ?", (story_id,)
        ).fetchone()
        if row is None:
            raise KeyError(story_id)
        merged = {**json.loads(row["flags_json"]), **dict(flags)}
        conn.execute(
            "UPDATE stories SET flags_json = ? WHERE id = ?",
            (json.dumps(merged, sort_keys=True), story_id),
        )


def scored_stories(conn: sqlite3.Connection, *,
                   day: str | None = None) -> list[StoryRow]:
    """Stories in state ``assessed`` or ``assess_failed`` (all days, or one ``day``), by id."""
    rows = conn.execute(
        "SELECT * FROM stories WHERE state IN ('assessed', 'assess_failed')"
        " AND (? IS NULL OR day = ?) ORDER BY id",
        (day, day),
    ).fetchall()
    return [_story_row(r) for r in rows]

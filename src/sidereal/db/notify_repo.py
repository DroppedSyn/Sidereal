"""Repository for the ``notifications`` table (M28, migration 0005).

``pending_top`` lists TOP stories first seen since a cutoff that have no row for the channel
and are not hidden; ``mark_sent`` records a successful send (idempotent). Secrets never come
near this module: rows hold story ids, the channel name, the run id and a time.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sidereal.timeutil import iso_z

CHANNELS = ("email", "discord")

_PENDING = (
    "SELECT s.id, s.title, s.score, s.first_seen_at, li.url AS lead_url,"
    " COALESCE(a.why, '') AS why"
    " FROM stories s"
    " LEFT JOIN items li ON li.id = s.lead_item_id"
    " LEFT JOIN assessments a ON a.story_id = s.id"
    " WHERE s.bucket = 'top' AND s.first_seen_at >= ?"
    " AND NOT EXISTS (SELECT 1 FROM notifications n"
    "                 WHERE n.story_id = s.id AND n.channel = ?)"
    " AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.story_id = s.id AND f.kind = 'hide')"
    " ORDER BY s.score DESC, s.id"
    " LIMIT ?"
)
_SOURCES = (
    "SELECT DISTINCT src.name FROM items i JOIN sources src ON src.id = i.source_id"
    " WHERE i.story_id = ? ORDER BY i.id"
)
_FIRST_URL = "SELECT url FROM items WHERE story_id = ? ORDER BY id LIMIT 1"
_MARK = (
    "INSERT OR IGNORE INTO notifications (story_id, channel, run_id, sent_at)"
    " VALUES (?, ?, ?, ?)"
)
_SENT = "SELECT story_id FROM notifications WHERE channel = ? ORDER BY story_id"


@dataclass(frozen=True)
class PendingStory:
    story_id: int
    title: str
    score: float | None
    url: str  # lead item's url (else the first item's), straight from items.url
    sources: tuple[str, ...]  # source names in item order
    why: str  # assessment "why" ("" if none)


def _check(channel: str) -> None:
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel: {channel!r}")


def pending_top(conn: sqlite3.Connection, channel: str, *, since: datetime,
                limit: int = 50) -> list[PendingStory]:
    """TOP stories first seen at or after ``since`` not yet sent on ``channel``, best first."""
    _check(channel)
    out = []
    for row in conn.execute(_PENDING, (iso_z(since), channel, limit)).fetchall():
        url = row["lead_url"]
        if url is None:
            first = conn.execute(_FIRST_URL, (row["id"],)).fetchone()
            url = first["url"] if first else ""
        sources = tuple(r[0] for r in conn.execute(_SOURCES, (row["id"],)).fetchall())
        out.append(PendingStory(story_id=row["id"], title=row["title"], score=row["score"],
                                url=url, sources=sources, why=row["why"]))
    return out


def mark_sent(conn: sqlite3.Connection, story_ids: Iterable[int], channel: str, *,
              run_id: int | None, at: datetime) -> int:
    """Record ``story_ids`` as sent on ``channel``; already recorded ones are left alone.
    Returns the number of new rows."""
    _check(channel)
    with conn:
        cur = conn.executemany(_MARK, [(sid, channel, run_id, iso_z(at)) for sid in story_ids])
    return cur.rowcount


def sent_ids(conn: sqlite3.Connection, channel: str) -> list[int]:
    _check(channel)
    return [r[0] for r in conn.execute(_SENT, (channel,)).fetchall()]

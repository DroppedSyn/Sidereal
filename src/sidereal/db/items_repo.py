"""Repository for the ``items`` table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from sidereal.timeutil import iso_z

CONTENT_STATUSES = ("ok", "blocked", "failed", "skipped")


@dataclass(frozen=True)
class ItemRow:
    id: int
    source_id: int
    story_id: int
    guid: str | None
    url: str
    canonical_url: str
    title: str
    title_norm: str
    author: str | None
    published_at: str | None
    first_seen_at: str
    run_id: int
    excerpt: str
    content_text: str | None
    content_status: str | None


def item_exists(conn: sqlite3.Connection, *,
                canonical_url: str, source_id: int,
                guid: str | None) -> bool:
    """True if a row has this ``canonical_url``, or (guid is not None and a row
    has this ``source_id`` and ``guid``)."""
    row = conn.execute(
        "SELECT 1 FROM items"
        " WHERE canonical_url = ?"
        " OR (? IS NOT NULL AND source_id = ? AND guid = ?)",
        (canonical_url, guid, source_id, guid),
    ).fetchone()
    return row is not None


def insert_item(conn: sqlite3.Connection, *,
                source_id: int, story_id: int, guid: str | None,
                url: str, canonical_url: str,
                title: str, title_norm: str, author: str | None,
                published_at: datetime | None,
                first_seen_at: datetime, run_id: int,
                excerpt: str = "") -> int | None:
    """Insert an item. Returns the id or ``None`` on conflict."""
    pub_str = iso_z(published_at) if published_at is not None else None
    with conn:
        cur = conn.execute(
            "INSERT INTO items (source_id, story_id, guid, url,"
            " canonical_url, title, title_norm, author,"
            " published_at, first_seen_at, run_id, excerpt)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT DO NOTHING",
            (source_id, story_id, guid, url, canonical_url,
             title, title_norm, author, pub_str,
             iso_z(first_seen_at), run_id, excerpt),
        )
    if cur.rowcount == 0:
        return None
    return cur.lastrowid


def _row(row: sqlite3.Row | None) -> ItemRow | None:
    if row is None:
        return None
    return ItemRow(**{name: row[name] for name in ItemRow.__dataclass_fields__})


def get_item(conn: sqlite3.Connection, item_id: int) -> ItemRow | None:
    """Return the item with the given ``id``, or ``None``."""
    return _row(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())


def items_for_story(conn: sqlite3.Connection, story_id: int) -> list[ItemRow]:
    """Return the items of ``story_id``, ordered by ``id``."""
    rows = conn.execute(
        "SELECT * FROM items WHERE story_id = ? ORDER BY id", (story_id,)
    ).fetchall()
    return [_row(r) for r in rows]


def set_content(conn: sqlite3.Connection, item_id: int, *,
                text: str | None, status: str) -> None:
    """Set ``content_text`` and ``content_status``. Unknown id → ``KeyError``."""
    if status not in CONTENT_STATUSES:
        raise ValueError(f"invalid content_status: {status!r}")
    with conn:
        cur = conn.execute(
            "UPDATE items SET content_text = ?, content_status = ?"
            " WHERE id = ?",
            (text, status, item_id),
        )
    if cur.rowcount == 0:
        raise KeyError(item_id)


def prune_content(conn: sqlite3.Connection, *,
                  older_than: datetime) -> int:
    """Clear ``content_text`` for items strictly older than ``older_than``.
    Returns the number of rows updated."""
    cutoff = iso_z(older_than)
    with conn:
        cur = conn.execute(
            "UPDATE items SET content_text = NULL"
            " WHERE content_text IS NOT NULL"
            " AND first_seen_at < ?",
            (cutoff,),
        )
    return cur.rowcount

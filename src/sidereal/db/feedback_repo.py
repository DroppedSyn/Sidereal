"""Repository for the feedback and mutes tables (M24)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sidereal.timeutil import iso_z

VOTES = ("up", "down")
MUTE_KINDS = ("source", "keyword")
MAX_MUTE_LEN = 200


@dataclass(frozen=True)
class StoryFeedback:
    vote: str | None  # "up" | "down" | None
    read: bool
    hidden: bool


NO_FEEDBACK = StoryFeedback(vote=None, read=False, hidden=False)


@dataclass(frozen=True)
class MuteRow:
    id: int
    kind: str  # "source" | "keyword"
    value: str
    created_at: str  # iso_z text


@dataclass(frozen=True)
class VotedStory:
    story_id: int
    vote: str  # "up" | "down"
    source_keys: tuple[str, ...]  # distinct source keys of the story's items, sorted
    focus: str | None  # assessment raw_json["focus"] if a str, else None
    tags: tuple[str, ...]  # assessment tags_json in stored order; () without assessment


def _require_story(conn: sqlite3.Connection, story_id: int) -> None:
    if conn.execute("SELECT 1 FROM stories WHERE id = ?", (story_id,)).fetchone() is None:
        raise KeyError(story_id)


def set_vote(conn: sqlite3.Connection, story_id: int, vote: str | None, *,
             at: datetime) -> None:
    """Set (or with None clear) the story's vote; up and down are exclusive."""
    if vote is not None and vote not in VOTES:
        raise ValueError(f"invalid vote: {vote!r}")
    _require_story(conn, story_id)
    with conn:
        conn.execute("DELETE FROM feedback WHERE story_id = ? AND kind IN ('up', 'down')",
                     (story_id,))
        if vote is not None:
            conn.execute("INSERT INTO feedback (story_id, kind, at) VALUES (?, ?, ?)",
                         (story_id, vote, iso_z(at)))


def set_read(conn: sqlite3.Connection, story_id: int, read: bool, *, at: datetime) -> None:
    """Mark read (keeps the first read time) or unread."""
    _require_story(conn, story_id)
    with conn:
        if read:
            conn.execute("INSERT OR IGNORE INTO feedback (story_id, kind, at)"
                         " VALUES (?, 'read', ?)", (story_id, iso_z(at)))
        else:
            conn.execute("DELETE FROM feedback WHERE story_id = ? AND kind = 'read'",
                         (story_id,))


def set_hidden(conn: sqlite3.Connection, story_id: int, hidden: bool, *,
               at: datetime) -> None:
    """Hide (keeps the first hide time) or unhide a story."""
    _require_story(conn, story_id)
    with conn:
        if hidden:
            conn.execute("INSERT OR IGNORE INTO feedback (story_id, kind, at)"
                         " VALUES (?, 'hide', ?)", (story_id, iso_z(at)))
        else:
            conn.execute("DELETE FROM feedback WHERE story_id = ? AND kind = 'hide'",
                         (story_id,))


def mark_day_read(conn: sqlite3.Connection, day: str, *, at: datetime) -> int:
    """Mark the day's top/relevant/side stories read; returns how many were newly marked."""
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO feedback (story_id, kind, at)"
            " SELECT id, 'read', ? FROM stories"
            " WHERE day = ? AND bucket IN ('top', 'relevant', 'side')",
            (iso_z(at), day),
        )
    return cur.rowcount


def story_feedback(conn: sqlite3.Connection,
                   story_ids: Sequence[int]) -> dict[int, StoryFeedback]:
    """Feedback for every id passed; ids without rows get ``NO_FEEDBACK``."""
    ids = [int(i) for i in story_ids]
    if not ids:
        return {}
    kinds: dict[int, set[str]] = {i: set() for i in ids}
    rows = conn.execute(
        "SELECT story_id, kind FROM feedback"
        " WHERE story_id IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),),
    ).fetchall()
    for row in rows:
        kinds[row["story_id"]].add(row["kind"])
    out: dict[int, StoryFeedback] = {}
    for sid, ks in kinds.items():
        vote = "up" if "up" in ks else "down" if "down" in ks else None
        out[sid] = StoryFeedback(vote=vote, read="read" in ks, hidden="hide" in ks)
    return out


def get_feedback(conn: sqlite3.Connection, story_id: int) -> StoryFeedback:
    """Feedback of one story (``NO_FEEDBACK`` if none)."""
    return story_feedback(conn, [story_id])[story_id]


def voted_stories(conn: sqlite3.Connection) -> list[VotedStory]:
    """Every voted story with its sources, focus and tags (input for the boost), by id."""
    votes = conn.execute(
        "SELECT f.story_id, f.kind, a.raw_json, a.tags_json FROM feedback f"
        " LEFT JOIN assessments a ON a.story_id = f.story_id"
        " WHERE f.kind IN ('up', 'down') ORDER BY f.story_id"
    ).fetchall()
    keys: dict[int, list[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT i.story_id, s.key FROM items i JOIN sources s ON s.id = i.source_id"
        " JOIN feedback f ON f.story_id = i.story_id AND f.kind IN ('up', 'down')"
        " ORDER BY i.story_id, s.key"
    ).fetchall():
        keys.setdefault(row["story_id"], []).append(row["key"])
    out: list[VotedStory] = []
    for row in votes:
        focus: str | None = None
        if row["raw_json"] is not None:
            raw = json.loads(row["raw_json"])
            value = raw.get("focus") if isinstance(raw, dict) else None
            focus = value if isinstance(value, str) else None
        tags = tuple(json.loads(row["tags_json"])) if row["tags_json"] is not None else ()
        out.append(VotedStory(story_id=row["story_id"], vote=row["kind"],
                              source_keys=tuple(keys.get(row["story_id"], ())),
                              focus=focus, tags=tags))
    return out


def _mute(row: sqlite3.Row) -> MuteRow:
    return MuteRow(id=row["id"], kind=row["kind"], value=row["value"],
                   created_at=row["created_at"])


def add_mute(conn: sqlite3.Connection, kind: str, value: str, *, at: datetime) -> MuteRow:
    """Add a mute (idempotent: a duplicate returns the existing row)."""
    if kind not in MUTE_KINDS:
        raise ValueError(f"invalid mute kind: {kind!r}")
    value = " ".join(value.split())
    if kind == "keyword":
        value = value.lower()
    if not value:
        raise ValueError("mute value must not be empty")
    if len(value) > MAX_MUTE_LEN:
        raise ValueError(f"mute value longer than {MAX_MUTE_LEN} characters")
    with conn:
        conn.execute("INSERT OR IGNORE INTO mutes (kind, value, created_at) VALUES (?, ?, ?)",
                     (kind, value, iso_z(at)))
    row = conn.execute("SELECT * FROM mutes WHERE kind = ? AND value = ?",
                       (kind, value)).fetchone()
    return _mute(row)


def list_mutes(conn: sqlite3.Connection) -> list[MuteRow]:
    """All mutes ordered by kind, then value."""
    return [_mute(r) for r in
            conn.execute("SELECT * FROM mutes ORDER BY kind, value").fetchall()]


def remove_mute(conn: sqlite3.Connection, mute_id: int) -> bool:
    """Delete a mute; False if the id is unknown."""
    with conn:
        cur = conn.execute("DELETE FROM mutes WHERE id = ?", (mute_id,))
    return cur.rowcount == 1


def muted_values(conn: sqlite3.Connection) -> tuple[frozenset[str], tuple[str, ...]]:
    """(muted source keys, muted keywords sorted) for the prefilter's ``Mutes``."""
    sources: set[str] = set()
    keywords: list[str] = []
    for row in conn.execute("SELECT kind, value FROM mutes ORDER BY value").fetchall():
        if row["kind"] == "source":
            sources.add(row["value"])
        else:
            keywords.append(row["value"])
    return frozenset(sources), tuple(keywords)

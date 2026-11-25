"""Read-only queries for the Gazette and Daily views (plan §10.1). No writes."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sidereal.db.runs_repo import RunRow
from sidereal.timeutil import iso_z
from sidereal.urls import is_http_url

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class SourceRef:
    key: str
    name: str
    url: str | None  # url of this source's first item (by item id); None unless http(s)


@dataclass(frozen=True)
class StoryView:
    id: int
    title: str
    day: str
    first_seen_at: str
    state: str
    bucket: str  # stories.bucket, or "side" when state is assess_failed and bucket is NULL
    score: float | None
    flags: dict[str, Any]
    cve_ids: list[str]
    summary: str | None  # from assessments; None without an assessment
    why: str | None
    tags: list[str]  # [] without an assessment
    focus: str | None  # assessments.raw_json["focus"] if it is a str, else None
    lead_url: str | None  # lead item's url; None unless http(s)
    published_at: str | None  # lead item's published_at
    excerpt: str  # lead item's excerpt; "" without items
    sources: list[SourceRef]  # distinct sources for this story, in item order


@dataclass(frozen=True)
class DaySummaryRow:
    day: str
    top: int
    relevant: int
    side: int  # includes assess_failed stories with a NULL bucket
    drop: int
    headline: str | None  # day_digests.headline, None without a digest


_SELECT = (
    "SELECT s.id, s.title, s.day, s.first_seen_at, s.state, s.bucket, s.score,"
    " s.flags_json, s.cve_ids_json, s.lead_item_id,"
    " a.summary, a.why, a.tags_json, a.raw_json,"
    " i.id AS item_id, i.url AS item_url, i.published_at AS item_published_at,"
    " i.excerpt AS item_excerpt, so.key AS source_key, so.name AS source_name"
    " FROM stories s"
    " LEFT JOIN assessments a ON a.story_id = s.id"
    " LEFT JOIN items i ON i.story_id = s.id"
    " LEFT JOIN sources so ON so.id = i.source_id"
)
_VISIBLE = " AND (s.bucket IS NOT NULL OR s.state = 'assess_failed')"
_NOT_HIDDEN = (
    " AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.story_id = s.id AND f.kind = 'hide')"
)
_GAZETTE_SQL = (_SELECT + " WHERE s.first_seen_at >= ?" + _VISIBLE + _NOT_HIDDEN
                + " ORDER BY s.id, i.id")
_DAY_SQL = _SELECT + " WHERE s.day = ?" + _VISIBLE + _NOT_HIDDEN + " ORDER BY s.id, i.id"
_COUNTS = (
    "SELECT d.day AS day,"
    " COALESCE(SUM(s.bucket = 'top'), 0) AS top,"
    " COALESCE(SUM(s.bucket = 'relevant'), 0) AS relevant,"
    " COALESCE(SUM(s.bucket = 'side' OR (s.bucket IS NULL AND s.state = 'assess_failed')), 0)"
    " AS side,"
    " COALESCE(SUM(s.bucket = 'drop'), 0) AS dropped,"
    " MAX(dd.headline) AS headline"
)
_ALL_DAYS = " FROM (SELECT day FROM stories UNION SELECT day FROM day_digests) AS d"
_DAYS_BEFORE = (
    " FROM (SELECT day FROM stories WHERE day < ?"
    " UNION SELECT day FROM day_digests WHERE day < ?) AS d"
)
_COUNTS_TAIL = (
    " LEFT JOIN stories s ON s.day = d.day AND NOT EXISTS"
    " (SELECT 1 FROM feedback f WHERE f.story_id = s.id AND f.kind = 'hide')"
    " LEFT JOIN day_digests dd ON dd.day = d.day"
    " GROUP BY d.day ORDER BY d.day DESC LIMIT ?"
)
_SUMMARIES_SQL = _COUNTS + _ALL_DAYS + _COUNTS_TAIL
_SUMMARIES_BEFORE_SQL = _COUNTS + _DAYS_BEFORE + _COUNTS_TAIL
_RUNS_SQL = (
    "SELECT * FROM runs WHERE started_at >= ? AND started_at < ? ORDER BY started_at, id"
)


def _check_day(day: str) -> None:
    if not isinstance(day, str) or not _DAY.fullmatch(day):
        raise ValueError(f"day must be YYYY-MM-DD, got {day!r}")


def _safe_url(url: str | None) -> str | None:
    return url if url is not None and is_http_url(url) else None


def _story_view(rows: list[sqlite3.Row]) -> StoryView:
    """One story from its rows (ordered by item id; one row with a NULL item without items)."""
    head = rows[0]
    items = [r for r in rows if r["item_id"] is not None]
    lead = next((r for r in items if r["item_id"] == head["lead_item_id"]), None)
    if lead is None and items:
        lead = items[0]
    raw = json.loads(head["raw_json"]) if head["raw_json"] is not None else {}
    focus = raw.get("focus") if isinstance(raw, dict) else None
    sources: list[SourceRef] = []
    seen: set[str] = set()
    for it in items:
        if it["source_key"] not in seen:
            seen.add(it["source_key"])
            sources.append(SourceRef(key=it["source_key"], name=it["source_name"],
                                     url=_safe_url(it["item_url"])))
    return StoryView(
        id=head["id"], title=head["title"], day=head["day"],
        first_seen_at=head["first_seen_at"], state=head["state"],
        bucket=head["bucket"] if head["bucket"] is not None else "side",
        score=head["score"], flags=json.loads(head["flags_json"]),
        cve_ids=json.loads(head["cve_ids_json"]),
        summary=head["summary"], why=head["why"],
        tags=json.loads(head["tags_json"]) if head["tags_json"] is not None else [],
        focus=focus if isinstance(focus, str) else None,
        lead_url=_safe_url(lead["item_url"]) if lead is not None else None,
        published_at=lead["item_published_at"] if lead is not None else None,
        excerpt=lead["item_excerpt"] if lead is not None else "",
        sources=sources,
    )


def _views(rows: list[sqlite3.Row]) -> list[StoryView]:
    """Group rows (ordered by story id, then item id) into one view per story."""
    groups: list[list[sqlite3.Row]] = []
    for row in rows:
        if groups and groups[-1][0]["id"] == row["id"]:
            groups[-1].append(row)
        else:
            groups.append([row])
    return [_story_view(g) for g in groups]


def gazette_views(conn: sqlite3.Connection, *, since: datetime) -> list[StoryView]:
    """Visible, not hidden stories with ``first_seen_at >= since`` (inclusive), by id."""
    return _views(conn.execute(_GAZETTE_SQL, (iso_z(since),)).fetchall())


def day_views(conn: sqlite3.Connection, day: str) -> list[StoryView]:
    """Visible, not hidden stories for ``day``, by id."""
    _check_day(day)
    return _views(conn.execute(_DAY_SQL, (day,)).fetchall())


def day_summaries(conn: sqlite3.Connection, *,
                  limit: int = 60,
                  before: str | None = None) -> list[DaySummaryRow]:
    """Days with any story or digest, newest first, with bucket counts (hidden stories
    not counted)."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")
    if before is not None:
        _check_day(before)
        rows = conn.execute(_SUMMARIES_BEFORE_SQL, (before, before, limit)).fetchall()
    else:
        rows = conn.execute(_SUMMARIES_SQL, (limit,)).fetchall()
    return [DaySummaryRow(day=r["day"], top=r["top"], relevant=r["relevant"],
                          side=r["side"], drop=r["dropped"], headline=r["headline"])
            for r in rows]


def runs_between(conn: sqlite3.Connection, *,
                 start: datetime, end: datetime) -> list[RunRow]:
    """Runs with ``start <= started_at < end``, ordered by ``started_at, id``."""
    rows = conn.execute(_RUNS_SQL, (iso_z(start), iso_z(end))).fetchall()
    return [RunRow(id=r["id"], started_at=r["started_at"],
                    finished_at=r["finished_at"], trigger=r["trigger"],
                    status=r["status"], stats=json.loads(r["stats_json"]),
                    error=r["error"])
            for r in rows]


# --- Story detail, sources page (M15b) ---

@dataclass(frozen=True)
class ItemView:
    id: int
    source_key: str
    source_name: str
    title: str
    url: str | None  # None unless http(s)
    author: str | None
    published_at: str | None
    first_seen_at: str
    excerpt: str


@dataclass(frozen=True)
class AssessmentView:
    model: str
    prompt_version: str
    relevance: int
    urgency: int
    actionability: int
    novelty: int
    exploited_in_wild: bool  # raw_json["exploited_in_wild"] is True
    created_at: str


@dataclass(frozen=True)
class StoryDetailView:
    story: StoryView
    items: list[ItemView]  # by item id
    assessment: AssessmentView | None


_STORY_SQL = _SELECT + " WHERE s.id = ?" + _VISIBLE + " ORDER BY s.id, i.id"
_ITEMS_SQL = (
    "SELECT i.id, i.title, i.url, i.author, i.published_at, i.first_seen_at, i.excerpt,"
    " so.key AS source_key, so.name AS source_name"
    " FROM items i JOIN sources so ON so.id = i.source_id"
    " WHERE i.story_id = ? ORDER BY i.id"
)
_ASSESSMENT_SQL = (
    "SELECT model, prompt_version, relevance, urgency, actionability, novelty, raw_json,"
    " created_at FROM assessments WHERE story_id = ?"
)
_SOURCE_COUNTS_SQL = (
    "SELECT source_id, COUNT(*) AS n FROM items WHERE first_seen_at >= ? GROUP BY source_id"
)


def story_detail(conn: sqlite3.Connection, story_id: int) -> StoryDetailView | None:
    """A visible story with all its items and assessment; None if unknown or not visible.
    Never reads ``content_text``."""
    rows = conn.execute(_STORY_SQL, (story_id,)).fetchall()
    if not rows:
        return None
    items = [ItemView(id=r["id"], source_key=r["source_key"], source_name=r["source_name"],
                      title=r["title"], url=_safe_url(r["url"]), author=r["author"],
                      published_at=r["published_at"], first_seen_at=r["first_seen_at"],
                      excerpt=r["excerpt"])
             for r in conn.execute(_ITEMS_SQL, (story_id,)).fetchall()]
    a = conn.execute(_ASSESSMENT_SQL, (story_id,)).fetchone()
    assessment = None
    if a is not None:
        raw = json.loads(a["raw_json"])
        exploited = isinstance(raw, dict) and raw.get("exploited_in_wild") is True
        assessment = AssessmentView(
            model=a["model"], prompt_version=a["prompt_version"], relevance=a["relevance"],
            urgency=a["urgency"], actionability=a["actionability"], novelty=a["novelty"],
            exploited_in_wild=exploited, created_at=a["created_at"])
    return StoryDetailView(story=_story_view(rows), items=items, assessment=assessment)


def item_counts_since(conn: sqlite3.Connection, *, since: datetime) -> dict[int, int]:
    """``{source_id: items first seen at or after since}``; sources without any are absent."""
    rows = conn.execute(_SOURCE_COUNTS_SQL, (iso_z(since),)).fetchall()
    return {r["source_id"]: r["n"] for r in rows}

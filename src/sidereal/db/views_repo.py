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
_GAZETTE_SQL = _SELECT + " WHERE s.first_seen_at >= ?" + _VISIBLE + " ORDER BY s.id, i.id"
_DAY_SQL = _SELECT + " WHERE s.day = ?" + _VISIBLE + " ORDER BY s.id, i.id"
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
    " LEFT JOIN stories s ON s.day = d.day"
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
    """Visible stories with ``first_seen_at >= since`` (inclusive), by id."""
    return _views(conn.execute(_GAZETTE_SQL, (iso_z(since),)).fetchall())


def day_views(conn: sqlite3.Connection, day: str) -> list[StoryView]:
    """Visible stories for ``day``, by id."""
    _check_day(day)
    return _views(conn.execute(_DAY_SQL, (day,)).fetchall())


def day_summaries(conn: sqlite3.Connection, *,
                  limit: int = 60,
                  before: str | None = None) -> list[DaySummaryRow]:
    """Days with any story or digest, newest first, with bucket counts."""
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

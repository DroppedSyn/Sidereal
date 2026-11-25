"""Response models for /api/gazette and /api/days (plan §10.1). Field names are the API contract."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Bucket = Literal["top", "relevant", "side", "drop"]


class SourceOut(BaseModel):
    key: str
    name: str
    url: str | None  # http(s) only, else None (plan rule 2)


class Story(BaseModel):
    id: int
    title: str
    day: str
    first_seen_at: str
    published_at: str | None
    bucket: Bucket
    score: float | None  # None = assessment failed
    summary: str | None
    why: str | None
    tags: list[str]
    focus: str | None
    flags: dict[str, Any]
    sources: list[SourceOut]
    lead_url: str | None  # http(s) only, else None
    excerpt: str
    read: bool = False  # feedback arrives in M24


class Sections(BaseModel):
    top: list[Story]
    relevant: list[Story]
    side: list[Story]
    drop: list[Story]  # empty unless include_drop


class Counts(BaseModel):
    top: int
    relevant: int
    side: int
    drop: int  # counted even when the drop section is hidden


class Gazette(BaseModel):
    generated_at: str
    window_start: str
    sections: Sections
    counts: Counts


class DayCounts(BaseModel):
    top: int
    relevant: int
    side: int


class DaySummary(BaseModel):
    day: str
    label: str
    counts: DayCounts
    run_count: int
    headline: str | None


class DayRun(BaseModel):
    id: int
    started_at: str
    finished_at: str | None
    trigger: str
    status: str


class DayDetail(BaseModel):
    day: str
    label: str
    overview: str | None
    headline: str | None
    runs: list[DayRun]
    sections: Sections
    counts: Counts

"""API response models (plan §10.1). Field names are the API contract."""

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
    read: bool = False  # feedback (M24)
    vote: Literal["up", "down"] | None = None
    hidden: bool = False  # only ever true on the story detail: lists leave hidden stories out


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


class StoryItem(BaseModel):
    id: int
    source_key: str
    source_name: str
    title: str
    url: str | None  # http(s) only, else None
    author: str | None
    published_at: str | None
    first_seen_at: str
    excerpt: str


class Rubric(BaseModel):
    relevance: int
    urgency: int
    actionability: int
    novelty: int
    exploited_in_wild: bool


class AssessmentOut(BaseModel):
    model: str
    prompt_version: str
    rubric: Rubric
    created_at: str


class StoryDetail(Story):
    """A Story plus all its items and the assessment details (never article text)."""
    cve_ids: list[str]
    items: list[StoryItem]
    assessment: AssessmentOut | None  # None for assess_failed


class RunOut(BaseModel):
    id: int
    started_at: str
    finished_at: str | None
    trigger: str
    status: str
    duration_s: float | None  # None while running
    stats: dict[str, Any]
    error: str | None


class RunStarted(BaseModel):
    status: Literal["started"]
    unit: str


class SourceStatus(BaseModel):
    id: int
    key: str
    name: str
    kind: str
    url: str | None  # feed url, http(s) only
    enabled: bool
    weight: float
    health: Literal["ok", "stale", "failing", "empty", "broken"]
    last_fetch_at: str | None
    last_ok_at: str | None
    last_error: str | None
    consecutive_failures: int
    last_item_at: str | None
    items_7d: int

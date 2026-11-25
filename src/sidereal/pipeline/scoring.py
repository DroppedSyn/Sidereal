"""Story scoring, bucketing, caps and ordering (plan §8, §7.4). Pure: no DB, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from sidereal.config import ScoringSettings

DEFAULT = ScoringSettings()

BUCKETS = ("top", "relevant", "side", "drop")
FEEDBACK_MAX = 10.0  # feedback boost clamped to [-FEEDBACK_MAX, +FEEDBACK_MAX]
RECENCY_END_HOURS = 24.0  # recency reaches cfg.recency_floor here


@dataclass(frozen=True)
class Rubric:
    relevance: int  # 0..3
    urgency: int
    actionability: int
    novelty: int
    exploited_in_wild: bool = False


@dataclass(frozen=True)
class StorySignals:
    kev: bool = False
    max_cvss: float | None = None
    source_weights: tuple[float, ...] = (1.0,)  # one per distinct source
    focus_tier: str | None = None  # "primary" | "secondary" | "side" | None
    feedback_boost: float = 0.0


@dataclass(frozen=True)
class Scored:
    story_id: int
    score: float | None  # None = assess_failed
    bucket: str
    first_seen: datetime  # aware UTC


def _max_weight(s: StorySignals) -> float:
    return max(s.source_weights) if s.source_weights else 1.0


def score_story(r: Rubric, s: StorySignals, cfg: ScoringSettings = DEFAULT) -> float:
    """Score 0..100 from the rubric and the story's signals (unrounded)."""
    weighted = (
        cfg.w_relevance * r.relevance
        + cfg.w_urgency * r.urgency
        + cfg.w_actionability * r.actionability
        + cfg.w_novelty * r.novelty
    )
    score = 100.0 * weighted / 3.0
    score += cfg.source_bonus_factor * (_max_weight(s) - 1.0)
    if s.kev:
        score += cfg.kev_bonus
    if r.exploited_in_wild:
        score += cfg.exploited_bonus
    if s.max_cvss is not None:
        if s.max_cvss >= 9.0:
            score += cfg.cvss9_bonus
        elif s.max_cvss >= 7.0:
            score += cfg.cvss7_bonus
    extra_sources = len(s.source_weights) - 1
    if extra_sources > 0:
        score += min(cfg.corroboration_bonus * extra_sources, cfg.corroboration_max)
    if s.focus_tier == "primary":
        score += cfg.primary_bonus
    elif s.focus_tier == "side":
        score -= cfg.side_penalty
    score += max(-FEEDBACK_MAX, min(FEEDBACK_MAX, s.feedback_boost))
    return max(0.0, min(100.0, score))


def bucket_for(
    score: float | None,
    r: Rubric | None,
    s: StorySignals,
    cfg: ScoringSettings = DEFAULT,
) -> str:
    """Bucket before caps: thresholds plus the hard rules."""
    if score is None or r is None:
        return "side"  # assess_failed
    if r.relevance == 0:
        return "drop"
    if score >= cfg.top_threshold:
        bucket = "top"
    elif score >= cfg.relevant_threshold:
        bucket = "relevant"
    elif score >= cfg.side_threshold:
        bucket = "side"
    else:
        bucket = "drop"
    if bucket == "top" and _max_weight(s) < 1.0:
        corroborated = len(s.source_weights) >= 2
        if not (r.relevance >= 2 and (corroborated or r.urgency == 3)):
            bucket = "relevant"
    return bucket


def _sort_key(x: Scored) -> tuple[int, float, int]:
    if x.score is None:
        return (1, 0.0, x.story_id)
    return (0, -x.score, x.story_id)


def place(stories: list[Scored], cfg: ScoringSettings = DEFAULT) -> dict[str, list[Scored]]:
    """Apply per-view caps; overflow moves down one bucket by score. Never promotes."""
    by_bucket: dict[str, list[Scored]] = {b: [] for b in BUCKETS}
    for x in stories:
        by_bucket[x.bucket].append(x)

    top = sorted(by_bucket["top"], key=_sort_key)
    relevant_pool = by_bucket["relevant"] + [
        replace(x, bucket="relevant") for x in top[cfg.top_cap :]
    ]
    relevant = sorted(relevant_pool, key=_sort_key)
    side_pool = by_bucket["side"] + [
        replace(x, bucket="side") for x in relevant[cfg.relevant_cap :]
    ]
    return {
        "top": top[: cfg.top_cap],
        "relevant": relevant[: cfg.relevant_cap],
        "side": sorted(side_pool, key=_sort_key),
        "drop": sorted(by_bucket["drop"], key=_sort_key),
    }


def recency_factor(first_seen: datetime, now: datetime, cfg: ScoringSettings = DEFAULT) -> float:
    """1.0 below recency_full_hours, linear to recency_floor at RECENCY_END_HOURS, floor beyond."""
    hours = (now - first_seen).total_seconds() / 3600.0
    if hours < cfg.recency_full_hours:
        return 1.0
    if hours >= RECENCY_END_HOURS:
        return cfg.recency_floor
    span = RECENCY_END_HOURS - cfg.recency_full_hours
    return 1.0 - (1.0 - cfg.recency_floor) * (hours - cfg.recency_full_hours) / span


def gazette_order(
    stories: list[Scored], now: datetime, cfg: ScoringSettings = DEFAULT
) -> list[Scored]:
    """Gazette order: score × recency desc, None scores last, ties by story_id."""

    def key(x: Scored) -> tuple[int, float, int]:
        if x.score is None:
            return (1, 0.0, x.story_id)
        return (0, -x.score * recency_factor(x.first_seen, now, cfg), x.story_id)

    return sorted(stories, key=key)

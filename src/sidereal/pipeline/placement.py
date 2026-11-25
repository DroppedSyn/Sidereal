"""Score and bucket a story from its stored assessment (plan §8). The model never decides
placement: only ``scoring.score_story`` / ``scoring.bucket_for`` over the validated rubric
numbers and code-known signals do (rule 1). Also ``rescore``: recompute every stored
placement without the LLM (``sidereal rescore``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sidereal.config import ScoringSettings
from sidereal.db import (
    Connection,
    assessments_repo,
    feedback_repo,
    focus_repo,
    sources_repo,
    stories_repo,
)
from sidereal.db.assessments_repo import AssessmentRow
from sidereal.pipeline.common import StoryBundle, bundle
from sidereal.pipeline.scoring import (
    BUCKETS,
    NO_BOOSTS,
    FeedbackBoosts,
    Rubric,
    StorySignals,
    Vote,
    bucket_for,
    feedback_boost,
    feedback_tables,
    score_story,
)


def focus_tiers(conn: Connection) -> dict[str, str]:
    """``{focus key: tier}`` over every focus area (a disabled area keeps its tier)."""
    return {f.key: f.tier for f in focus_repo.list_focus_areas(conn, enabled_only=False)}


def feedback_boosts(conn: Connection) -> FeedbackBoosts:
    """Per-source and per-topic boosts from every vote (M24), computed once per pass."""
    return feedback_tables(Vote(v.vote, v.source_keys, v.focus, v.tags)
                           for v in feedback_repo.voted_stories(conn))


def _cvss(flags: Mapping[str, Any]) -> float | None:
    value = flags.get("cvss")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def signals_for(b: StoryBundle, focus_key: str | None,
                tiers: Mapping[str, str], *, boosts: FeedbackBoosts = NO_BOOSTS,
                tags: Sequence[str] = ()) -> StorySignals:
    flags = b.story.flags
    return StorySignals(
        kev=flags.get("kev") is True,
        max_cvss=_cvss(flags),
        source_weights=b.source_weights or (1.0,),
        focus_tier=tiers.get(focus_key) if focus_key else None,
        feedback_boost=feedback_boost(boosts, sources=b.source_keys, focus=focus_key,
                                      tags=tags),
    )


def rubric_of(a: AssessmentRow) -> Rubric:
    return Rubric(a.relevance, a.urgency, a.actionability, a.novelty,
                  exploited_in_wild=a.raw.get("exploited_in_wild") is True)


def place_assessed(conn: Connection, b: StoryBundle, a: AssessmentRow,
                   tiers: Mapping[str, str], cfg: ScoringSettings, *,
                   boosts: FeedbackBoosts = NO_BOOSTS) -> str:
    """Compute and store score + bucket for an assessed story; returns the bucket."""
    focus = a.raw.get("focus")
    rubric = rubric_of(a)
    signals = signals_for(b, focus if isinstance(focus, str) else None, tiers,
                          boosts=boosts, tags=a.tags)
    score = score_story(rubric, signals, cfg)
    bucket = bucket_for(score, rubric, signals, cfg)
    stories_repo.set_score(conn, b.story.id, score=score, bucket=bucket)
    return bucket


def mark_failed(conn: Connection, story_id: int) -> str:
    """``assess_failed`` → shown in "On the side" with no score (§8)."""
    stories_repo.set_score(conn, story_id, score=None, bucket="side")
    stories_repo.set_state(conn, story_id, "assess_failed")
    return "side"


def rescore(conn: Connection, cfg: ScoringSettings, *,
            day: str | None = None) -> dict[str, Any]:
    """Recompute score and bucket of every assessed / assess_failed story (one ``day`` or all)
    from stored assessments; no LLM. Returns ``{"rescored", "buckets", "days"}``."""
    tiers = focus_tiers(conn)
    boosts = feedback_boosts(conn)
    sources = {s.id: s for s in sources_repo.list_sources(conn)}
    counts = dict.fromkeys(BUCKETS, 0)
    days: set[str] = set()
    n = 0
    for story in stories_repo.scored_stories(conn, day=day):
        a = assessments_repo.get_assessment(conn, story.id)
        if story.state == "assess_failed" or a is None:
            bucket = mark_failed(conn, story.id)
        else:
            bucket = place_assessed(conn, bundle(conn, story, sources), a, tiers, cfg,
                                    boosts=boosts)
        counts[bucket] += 1
        days.add(story.day)
        n += 1
    return {"rescored": n, "buckets": counts, "days": sorted(days)}


def refresh(conn: Connection, story_ids: list[int], cfg: ScoringSettings) -> set[str]:
    """Re-place already assessed stories that gained items this run (corroboration, KEV flag);
    returns their days. Other states are left alone."""
    tiers = focus_tiers(conn)
    boosts = feedback_boosts(conn)
    sources = {s.id: s for s in sources_repo.list_sources(conn)}
    days: set[str] = set()
    for sid in story_ids:
        story = stories_repo.get_story(conn, sid)
        a = assessments_repo.get_assessment(conn, sid)
        if story is None or story.state != "assessed" or a is None:
            continue
        place_assessed(conn, bundle(conn, story, sources), a, tiers, cfg, boosts=boosts)
        days.add(story.day)
    return days


REOPEN_STATES = ("filtered", "triaged_out")


def reopen(conn: Connection, story_ids: list[int]) -> int:
    """Put filtered / triaged-out stories that gained items this run back to ``new``, so the
    prefilter and triage see them again: a joining item can carry an always-keep signal (a
    Microsoft KEV entry, a trusted source, a primary keyword) or a source that is not muted.
    A stored triage relevance below ``keep_min`` sends the story to triage again. Returns the
    number reopened."""
    n = 0
    for sid in story_ids:
        story = stories_repo.get_story(conn, sid)
        if story is not None and story.state in REOPEN_STATES:
            stories_repo.set_state(conn, sid, "new")
            n += 1
    return n

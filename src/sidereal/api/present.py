"""View rows → API sections: caps, ordering, counts (plan §8, §10.1). Pure: no DB, no I/O."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from sidereal.api.schemas import (
    AssessmentOut,
    Counts,
    DayCounts,
    Rubric,
    Sections,
    SourceOut,
    Story,
    StoryDetail,
    StoryItem,
)
from sidereal.config import ScoringSettings
from sidereal.db.feedback_repo import NO_FEEDBACK, StoryFeedback
from sidereal.db.views_repo import StoryDetailView, StoryView
from sidereal.pipeline.scoring import Scored, gazette_order, place
from sidereal.timeutil import parse_iso_z
from sidereal.urls import is_http_url

ASSESS_FAILED = "assess_failed"


def _http(url: str | None) -> str | None:
    """Rule 2, checked again at the API edge: only http(s) links leave the server."""
    return url if url is not None and is_http_url(url) else None


def _failed(v: StoryView) -> bool:
    return v.state == ASSESS_FAILED


def story_out(v: StoryView, *, bucket: str | None = None,
              fb: StoryFeedback = NO_FEEDBACK) -> Story:
    """One API Story; *bucket* (the placed one) overrides the stored bucket; *fb* is the
    owner's feedback (vote, read, hidden)."""
    failed = _failed(v)
    return Story(
        id=v.id, title=v.title, day=v.day, first_seen_at=v.first_seen_at,
        published_at=v.published_at,
        bucket=bucket if bucket is not None else ("side" if failed else v.bucket),
        score=None if failed else v.score,
        summary=v.summary, why=v.why, tags=list(v.tags), focus=v.focus,
        flags=dict(v.flags),
        sources=[SourceOut(key=s.key, name=s.name, url=_http(s.url)) for s in v.sources],
        lead_url=_http(v.lead_url), excerpt=v.excerpt, read=fb.read, vote=fb.vote,
        hidden=fb.hidden,
    )


def _scored(v: StoryView) -> Scored:
    """assess_failed always goes to "On the side" without a score (plan §1 rule 1)."""
    failed = _failed(v)
    return Scored(story_id=v.id, score=None if failed else v.score,
                  bucket="side" if failed else v.bucket,
                  first_seen=parse_iso_z(v.first_seen_at))


def build_sections(views: Sequence[StoryView], cfg: ScoringSettings, *,
                   now: datetime | None, include_drop: bool,
                   feedback: Mapping[int, StoryFeedback] | None = None,
                   ) -> tuple[Sections, Counts]:
    """Per-view caps via ``place``; Gazette order (score × recency) when *now* is set,
    else place's score order (Daily). Drop is always counted, listed only on request.
    Hidden stories (per *feedback*) are left out before placement (defence in depth: the
    view queries already skip them)."""
    fbs = feedback or {}
    views = [v for v in views if not fbs.get(v.id, NO_FEEDBACK).hidden]
    by_id = {v.id: v for v in views}
    placed = place([_scored(v) for v in views], cfg)
    out: dict[str, list[Story]] = {}
    for name, lst in placed.items():
        ordered = gazette_order(lst, now, cfg) if now is not None else lst
        out[name] = [story_out(by_id[s.story_id], bucket=s.bucket,
                               fb=fbs.get(s.story_id, NO_FEEDBACK)) for s in ordered]
    sections = Sections(top=out["top"], relevant=out["relevant"], side=out["side"],
                        drop=out["drop"] if include_drop else [])
    counts = Counts(top=len(placed["top"]), relevant=len(placed["relevant"]),
                    side=len(placed["side"]), drop=len(placed["drop"]))
    return sections, counts


def placed_counts(top: int, relevant: int, side: int, cfg: ScoringSettings) -> DayCounts:
    """The counts ``place`` would give from raw bucket counts (the day list has no rows)."""
    shown_top = min(top, cfg.top_cap)
    pool = relevant + (top - shown_top)
    shown_relevant = min(pool, cfg.relevant_cap)
    return DayCounts(top=shown_top, relevant=shown_relevant,
                     side=side + (pool - shown_relevant))


def story_detail_out(d: StoryDetailView, fb: StoryFeedback = NO_FEEDBACK) -> StoryDetail:
    """GET /api/stories/{id}: the Story plus items and assessment; links http(s) only."""
    a = d.assessment
    assessment = None if a is None or _failed(d.story) else AssessmentOut(
        model=a.model, prompt_version=a.prompt_version, created_at=a.created_at,
        rubric=Rubric(relevance=a.relevance, urgency=a.urgency, actionability=a.actionability,
                      novelty=a.novelty, exploited_in_wild=a.exploited_in_wild))
    items = [StoryItem(id=i.id, source_key=i.source_key, source_name=i.source_name,
                       title=i.title, url=_http(i.url), author=i.author,
                       published_at=i.published_at, first_seen_at=i.first_seen_at,
                       excerpt=i.excerpt)
             for i in d.items]
    base = story_out(d.story, fb=fb).model_dump()
    return StoryDetail(**base, cve_ids=list(d.story.cve_ids), items=items,
                       assessment=assessment)

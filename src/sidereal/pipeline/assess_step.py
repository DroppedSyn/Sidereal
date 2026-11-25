"""Judgement (plan §0.1 steps 5-9): prefilter → triage → enrich → assess → score/bucket.

Stories in state ``new`` are the queue. Prefilter drops (``filtered``) or always-keeps; the
rest are triaged in the §7.2 order, sliced to ``max_triage_per_run``. Kept stories (always,
earlier-triaged ones still ``new`` with a keeping relevance, then this run's triage keeps) are
enriched and assessed up to ``max_assess_per_run``; everything not reached stays ``new`` for
the next run. ``LLMUnavailable`` stops the step (the runner marks the run ``partial``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sidereal.config import Settings
from sidereal.db import (
    Connection,
    assessments_repo,
    focus_repo,
    items_repo,
    sources_repo,
    stories_repo,
)
from sidereal.llm import assess, prompts, triage
from sidereal.llm.ollama import LLMOutputInvalid, LLMUnavailable, OllamaClient
from sidereal.net.fetch import Fetcher
from sidereal.pipeline import enrich, placement
from sidereal.pipeline.common import Deadline, StoryBundle, bundle, short_error
from sidereal.pipeline.prefilter import (
    Candidate,
    Decision,
    FocusArea,
    Mutes,
    order_for_triage,
    prefilter,
)
from sidereal.pipeline.scoring import BUCKETS
from sidereal.timeutil import day_key, iso_z

log = logging.getLogger(__name__)


@dataclass
class AssessStepResult:
    stats: dict[str, Any] = field(default_factory=dict)
    days: set[str] = field(default_factory=set)  # days whose placements changed
    llm_error: str | None = None  # set when Ollama became unavailable


_TRIAGE_ZERO = {"calls": 0, "kept": 0, "dropped": 0, "defaulted": 0, "unfinished": 0,
                "invalid_batches": 0}


@dataclass(frozen=True)
class _Prompts:
    triage: prompts.PromptTemplate
    assess: prompts.PromptTemplate
    focus_text: str
    focus_keys: tuple[str, ...]
    today: str


def candidate(b: StoryBundle) -> Candidate:
    vendor = b.story.flags.get("kev_vendor") if b.story.flags.get("kev") is True else None
    return Candidate(
        story_id=b.story.id, title=b.story.title, source_keys=b.source_keys,
        max_source_weight=max(b.source_weights, default=1.0), published=b.published,
        first_seen=b.first_seen, kev_vendor=vendor if isinstance(vendor, str) else None,
    )


def _triage_line(b: StoryBundle) -> prompts.TriageLine:
    return prompts.TriageLine(id=b.story.id, title=b.story.title,
                              source=", ".join(s.name for s in b.sources),
                              excerpt=b.lead.excerpt if b.lead else "")


async def _triage(conn: Connection, ollama: OllamaClient, settings: Settings,
                  queue: Sequence[StoryBundle], p: _Prompts,
                  deadline: Deadline) -> tuple[list[int], dict[str, Any]]:
    """Triage ``queue`` (already ordered and sliced); store relevance and ``triaged_out``.
    Returns the kept ids in queue order. ``LLMUnavailable`` propagates (nothing stored)."""
    if not queue:
        return [], dict(_TRIAGE_ZERO)
    by_id = {b.story.id: b for b in queue}

    def render(ids: Sequence[int]) -> tuple[str, str]:
        items = prompts.render_triage_items(_triage_line(by_id[i]) for i in ids)
        return prompts.render(p.triage, focus_areas=p.focus_text, today=p.today,
                              count=len(ids), items=items)

    out = await triage.run_batches(
        ollama, list(by_id), render=render, model=settings.models.triage,
        keep_min=settings.triage.keep_min, batch_size=settings.budget.triage_batch_size,
        deadline=deadline, keep_alive=settings.models.keep_alive)
    for sid, rel in out.relevance.items():
        stories_repo.set_triage(conn, sid, rel)
    for sid in out.dropped:
        stories_repo.set_state(conn, sid, "triaged_out", reason="triage")
    stats = {"calls": out.calls, "kept": len(out.kept), "dropped": len(out.dropped),
             "defaulted": len(out.defaulted), "unfinished": len(out.unfinished),
             "invalid_batches": out.invalid_batches}
    return list(out.kept), stats


async def _enrich(conn: Connection, fetcher: Fetcher, queue: Sequence[StoryBundle],
                  deadline: Deadline) -> tuple[dict[int, str], dict[str, int]]:
    """Fetch article text for each queued story's lead item not tried before. Returns
    ``{item_id: text}`` for fresh successes. Deadline skips are not stored (retried later)."""
    targets = []
    for b in queue:
        if b.lead is None or b.lead.content_status is not None:
            continue
        src = next((s for s in b.sources if s.id == b.lead.source_id), None)
        try:
            hosts = enrich.allowlist_for(src.options if src else {})
        except ValueError:
            hosts = ()
        targets.append(enrich.ArticleTarget(b.lead.id, b.lead.url,
                                            src.key if src else "", hosts))
    stats = dict.fromkeys(enrich.STATUSES, 0)
    if not targets:
        return {}, stats
    try:
        outcomes = await enrich.enrich_many(targets, fetcher, deadline=deadline)
    except Exception as exc:  # enrichment is optional: assess from the excerpt
        log.warning("enrich failed as a whole: %s", type(exc).__name__)
        return {}, stats
    texts: dict[int, str] = {}
    for o in outcomes:
        stats[o.status] += 1
        if o.status == "skipped" and (o.error or "").startswith("Deadline"):
            continue
        items_repo.set_content(conn, o.item_id, text=o.text, status=o.status)
        if o.status == "ok" and o.text:
            texts[o.item_id] = o.text
    return texts, stats


def _render_assess(b: StoryBundle, p: _Prompts, settings: Settings,
                   content: str | None) -> tuple[str, str]:
    pub = b.published
    article = prompts.render_article(
        title=b.story.title, sources=[s.name for s in b.sources],
        published=iso_z(pub) if pub else "unknown",
        excerpt=b.lead.excerpt if b.lead else "", content=content,
        excerpt_chars=settings.budget.assess_excerpt_chars,
        content_chars=settings.budget.assess_content_chars)
    return prompts.render(p.assess, focus_areas=p.focus_text,
                          focus_keys=prompts.render_focus_keys(p.focus_keys),
                          today=p.today, article=article)


async def _assess_one(conn: Connection, ollama: OllamaClient, settings: Settings,
                      b: StoryBundle, p: _Prompts, content: str | None, tiers: dict[str, str],
                      *, now: datetime) -> tuple[str, int | None]:
    """Assess and place one story; returns ``(bucket, duration_ms or None if failed)``."""
    system, user = _render_assess(b, p, settings, content)
    try:
        res = await assess.assess_story(ollama, model=settings.models.assess, system=system,
                                        user=user, focus_keys=p.focus_keys,
                                        keep_alive=settings.models.keep_alive)
    except LLMOutputInvalid as exc:
        log.warning("assess story %d: %s", b.story.id, type(exc).__name__)
        return placement.mark_failed(conn, b.story.id), None
    r = res.rubric
    assessments_repo.save_assessment(
        conn, b.story.id, model=settings.models.assess,
        prompt_version=prompts.prompt_version(p.assess), relevance=r.relevance,
        urgency=r.urgency, actionability=r.actionability, novelty=r.novelty, tags=res.tags,
        summary=res.summary, why=res.why, raw={**res.raw, "focus": res.focus},
        duration_ms=res.duration_ms, at=now)
    if r.exploited_in_wild:
        stories_repo.merge_flags(conn, b.story.id, {"exploited": True})
    saved = assessments_repo.get_assessment(conn, b.story.id)
    assert saved is not None
    bucket = placement.place_assessed(conn, b, saved, tiers, settings.scoring)
    stories_repo.set_state(conn, b.story.id, "assessed")
    return bucket, res.duration_ms


def _select(conn: Connection, bundles: Sequence[StoryBundle], settings: Settings,
            focus: Sequence[FocusArea], now: datetime):
    """Prefilter every pending story; store ``filtered``. Returns id lists (always,
    pretriaged, to_triage sliced to ``max_triage_per_run``), each in §7.2 order, and stats."""
    always, pre, tri = [], [], []
    filtered = 0
    keep_min = settings.triage.keep_min
    for b in bundles:
        c = candidate(b)
        d: Decision = prefilter(c, focus, Mutes(), now=now,
                                max_age_hours=settings.ingest.max_age_hours)
        if not d.keep:
            stories_repo.set_state(conn, b.story.id, "filtered", reason=d.reason)
            filtered += 1
        elif d.always:
            always.append((c, d))
        elif b.story.triage_relevance is not None and b.story.triage_relevance >= keep_min:
            pre.append((c, d))
        else:
            tri.append((c, d))
    order = [[c.story_id for c, _ in order_for_triage(x, now=now)] for x in (always, pre, tri)]
    cap = settings.budget.max_triage_per_run
    stats = {"kept": len(always) + len(pre) + len(tri), "filtered": filtered,
             "always": len(always), "deferred": max(0, len(order[2]) - cap)}
    return order[0], order[1], order[2][:cap], stats


async def run_assess(conn: Connection, ollama: OllamaClient, fetcher: Fetcher,
                     settings: Settings, *, now: datetime, deadline: Deadline,
                     max_assess: int | None = None) -> AssessStepResult:
    res = AssessStepResult()
    sources = {s.id: s for s in sources_repo.list_sources(conn)}
    focus_rows = focus_repo.list_focus_areas(conn)
    focus = [FocusArea(f.key, f.tier, f.keywords) for f in focus_rows]
    bundles = {s.id: bundle(conn, s, sources) for s in stories_repo.pending_stories(conn)}
    always, pre, to_triage, res.stats["prefilter"] = _select(
        conn, list(bundles.values()), settings, focus, now)
    p = _Prompts(
        triage=prompts.load_prompt("triage"), assess=prompts.load_prompt("assess"),
        focus_text=prompts.render_focus_areas(
            prompts.FocusLine(f.key, f.tier, f.description) for f in focus_rows),
        focus_keys=tuple(f.key for f in focus_rows), today=day_key(now, settings.schedule.tz))
    tiers = placement.focus_tiers(conn)
    buckets = dict.fromkeys(BUCKETS, 0)
    res.stats.update(buckets=buckets, assess={"ok": 0, "failed": 0, "deferred": 0,
                                              "avg_ms": 0})
    try:
        kept, res.stats["triage"] = await _triage(
            conn, ollama, settings, [bundles[i] for i in to_triage], p, deadline)
    except LLMUnavailable as exc:
        res.llm_error = short_error(exc)
        kept, res.stats["triage"] = [], dict(_TRIAGE_ZERO)
    queue_ids = always + pre + kept
    cap = settings.budget.max_assess_per_run if max_assess is None else max_assess
    queue = [bundles[i] for i in queue_ids[:cap]]
    texts, res.stats["enrich"] = (await _enrich(conn, fetcher, queue, deadline)
                                  if res.llm_error is None
                                  else ({}, dict.fromkeys(enrich.STATUSES, 0)))
    durations: list[int] = []
    done = 0
    for b in queue if res.llm_error is None else []:
        if deadline():
            break
        lead_id = b.lead.id if b.lead else None
        content = texts.get(lead_id) if lead_id is not None else None
        if content is None and b.lead is not None and b.lead.content_status == "ok":
            content = b.lead.content_text
        try:
            bucket, ms = await _assess_one(conn, ollama, settings, b, p, content, tiers, now=now)
        except LLMUnavailable as exc:
            res.llm_error = short_error(exc)
            break
        done += 1
        buckets[bucket] += 1
        res.days.add(b.story.day)
        if ms is None:
            res.stats["assess"]["failed"] += 1
        else:
            res.stats["assess"]["ok"] += 1
            durations.append(ms)
    res.stats["assess"]["deferred"] = len(queue_ids) - done
    res.stats["assess"]["avg_ms"] = sum(durations) // len(durations) if durations else 0
    log.info("assess: %d ok, %d failed, %d deferred", res.stats["assess"]["ok"],
             res.stats["assess"]["failed"], res.stats["assess"]["deferred"])
    return res

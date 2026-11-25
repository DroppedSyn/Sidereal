"""Pipeline runner (plan §9): one run = gate → ingest → judgement → digests, recorded in
``runs``. A thin coordinator: the steps live in ``ingest``, ``assess_step``, ``placement``,
``digest_step``, ``week_step`` (M29) and ``notify.dispatcher``. The caller (``sidereal run``)
holds the run lock (rule 10) and owns the ``Fetcher`` / ``OllamaClient``; nothing here opens
network clients itself.

Status: ``ok``; ``partial`` when a source failed, the deadline cut the run short, Ollama
became unavailable, a digest was left for later or a notification channel failed; ``failed``
on any unexpected exception (each step commits its own work, so what was stored stays).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sidereal.config import Settings
from sidereal.db import Connection, runs_repo, sources_repo
from sidereal.db.runs_repo import RunRow
from sidereal.llm.gate import Gate
from sidereal.llm.ollama import LLMError, LLMUnavailable, OllamaClient
from sidereal.net.fetch import Fetcher
from sidereal.notify.dispatcher import dispatch as notify_dispatch
from sidereal.overrides import effective_settings
from sidereal.pipeline import digest_step, ingest, placement, retention, week_step
from sidereal.pipeline.assess_step import run_assess
from sidereal.pipeline.common import Deadline, short_error
from sidereal.timeutil import day_key, utc_now

log = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 300.0  # a probe that times out counts as "not busy" in the gate: be generous
DIGEST_LOOKBACK_DAYS = 3  # recent days re-checked every run (a failed digest is retried)


def make_gate(settings: Settings, ollama: OllamaClient) -> Gate:
    """The §7.5 gate: pi-bridge runs dir + a 1-token probe on the triage model."""
    return Gate.from_settings(settings.gate, probe=lambda: ollama.probe(
        settings.models.triage, timeout_s=PROBE_TIMEOUT_S, keep_alive=settings.models.keep_alive))


def select_sources(conn: Connection, only_source: str | None) -> list:
    """Enabled sources, or just ``only_source`` (enabled or not); unknown key → ValueError."""
    if only_source is None:
        return sources_repo.list_sources(conn, enabled_only=True)
    row = sources_repo.get_by_key(conn, only_source)
    if row is None:
        raise ValueError(f"unknown source key {only_source!r}")
    return [row]


def _digest_days(now: datetime, tz: str, touched: set[str]) -> set[str]:
    recent = {day_key(now - timedelta(days=k), tz) for k in range(DIGEST_LOOKBACK_DAYS)}
    return touched | recent


async def _unload(settings: Settings, ollama: OllamaClient) -> None:
    """After the run, unload our models (the client never unloads ``never_unload`` ones)."""
    m = settings.models
    for model in dict.fromkeys((m.triage, m.assess, m.digest)):
        try:
            await ollama.unload(model)
        except LLMError as exc:
            log.warning("unload %s failed: %s", model, type(exc).__name__)


async def run_once(settings: Settings, conn: Connection, *, fetcher: Fetcher,
                   ollama: OllamaClient, trigger: str = "manual", now: datetime | None = None,
                   gate: Gate | None = None, only_source: str | None = None,
                   max_assess: int | None = None,
                   clock: Callable[[], float] = time.monotonic) -> RunRow:
    """One full run. ``gate=None`` skips the gate (``--no-gate``). ``now`` is the run's
    timestamp (first-seen time, day key, age caps); durations and the deadline use ``clock``.
    A bad ``only_source`` / ``trigger`` raises ValueError before any run row is written."""
    if trigger not in runs_repo.TRIGGERS:
        raise ValueError(f"unknown trigger: {trigger!r}")
    sources = select_sources(conn, only_source)
    settings = effective_settings(settings, conn)  # settings-UI overrides (M27)
    t0 = clock()
    now = now or utc_now()
    recovered = runs_repo.recover_stale(conn, at=now)
    first_run = runs_repo.last_ok_run(conn) is None
    run_id = runs_repo.start_run(conn, trigger=trigger, at=now)
    stats: dict[str, Any] = {"durations_s": {}}
    if recovered:
        stats["recovered_runs"] = recovered
    reasons: list[str] = []
    llm_used = False
    status = "ok"
    try:
        g = await gate.wait() if gate is not None else None
        stats["gate_wait_s"] = round(g.waited_s, 1) if g else 0.0
        stats["gate"] = g.reason if g else "skipped"
        deadline = Deadline(settings.budget.max_run_minutes * 60, clock=clock)
        tz = settings.schedule.tz

        t = clock()
        ing = await ingest.ingest(
            conn, sources, fetcher, run_id=run_id, now=now, tz=tz,
            max_age_hours=settings.ingest.backfill_hours if first_run
            else settings.ingest.max_age_hours,
            window_hours=settings.ingest.dedupe_window_hours)
        stats.update(ing.stats)
        stats["durations_s"]["fetch"] = round(clock() - t, 1)
        if ing.stats["sources"]["failed"]:
            reasons.append(f"{ing.stats['sources']['failed']} source(s) failed")
        days = placement.refresh(conn, ing.joined_story_ids, settings.scoring)
        stats["stories"]["reopened"] = placement.reopen(conn, ing.joined_story_ids)

        t = clock()
        asr = await run_assess(conn, ollama, fetcher, settings, now=now, deadline=deadline,
                               max_assess=max_assess)
        stats.update(asr.stats)
        stats["durations_s"]["assess"] = round(clock() - t, 1)
        days |= asr.days
        llm_used = bool(stats["triage"]["calls"] or asr.days)

        t = clock()
        if asr.llm_error is None:
            try:
                stats["digest"] = await digest_step.update_days(
                    conn, ollama, settings, _digest_days(now, tz, days), run_id=run_id,
                    now=now, deadline=deadline)
                llm_used = llm_used or bool(stats["digest"]["written"] + stats["digest"]["failed"])
                stats["week_digest"] = await week_step.update_weeks(
                    conn, ollama, settings, week_step.weeks_to_check(now, tz), run_id=run_id,
                    now=now, deadline=deadline)
                wd = stats["week_digest"]
                llm_used = llm_used or bool(wd["written"] + wd["failed"])
            except LLMUnavailable as exc:
                asr.llm_error = short_error(exc)
                llm_used = True
        stats["durations_s"]["digest"] = round(clock() - t, 1)
        if settings.notify.channels:  # never fails the run: errors land in stats["notify"]
            stats["notify"] = await notify_dispatch(conn, settings, fetcher=fetcher, now=now,
                                                    run_id=run_id)
            failed = sorted(k for k, v in stats["notify"].items() if "error" in v)
            if failed:
                reasons.append(f"notify failed: {', '.join(failed)}")
        try:  # §12.4 lifecycle; a failure here leaves the run partial, not failed
            stats["retention"] = retention.apply_retention(conn, settings.retention, now=now)
        except Exception as exc:
            log.exception("run %d: retention failed", run_id)
            reasons.append(f"retention failed: {short_error(exc)}")
        if asr.llm_error is not None:
            reasons.append(f"ollama unavailable: {asr.llm_error}")
        if deadline.hit:
            reasons.append("deadline reached")
        if stats.get("digest", {}).get("skipped") or stats.get("digest", {}).get("failed"):
            reasons.append("digest left for the next run")
        if stats.get("week_digest", {}).get("skipped") or stats.get("week_digest", {}).get(
                "failed"):
            reasons.append("weekly digest left for the next run")
        status = "partial" if reasons else "ok"
    except Exception as exc:  # unexpected: record and keep what the steps committed
        log.exception("run %d failed", run_id)
        status = "failed"
        reasons = [short_error(exc)]
    if llm_used:
        await _unload(settings, ollama)
    elapsed = clock() - t0
    stats["durations_s"]["total"] = round(elapsed, 1)
    runs_repo.finish_run(conn, run_id, status=status, stats=stats,
                         at=now + timedelta(seconds=elapsed),
                         error="; ".join(reasons) or None)
    log.info("run %d finished: %s", run_id, status)
    row = runs_repo.get_run(conn, run_id)
    assert row is not None
    return row


async def dry_run(settings: Settings, conn: Connection, *, fetcher: Fetcher,
                  now: datetime | None = None, only_source: str | None = None) -> dict[str, Any]:
    """``sidereal run --dry-run``: fetch + normalise + dedupe, write nothing, return counts."""
    now = now or utc_now()
    first_run = runs_repo.last_ok_run(conn) is None
    outcomes = await ingest.fetch_all(
        select_sources(conn, only_source), fetcher, now,
        max_age_hours=settings.ingest.backfill_hours if first_run
        else settings.ingest.max_age_hours)
    items, skipped = ingest.normalize_all(outcomes)
    fresh, assignments, known = ingest.plan_stories(
        conn, items, now=now, window_hours=settings.ingest.dedupe_window_hours)
    failed = [o.source.key for o in outcomes if o.result is None]
    return {
        "sources": {"ok": len(outcomes) - len(failed), "failed": len(failed),
                    "failed_keys": failed},
        "items": {"fetched": len(items) + skipped, "skipped": skipped,
                  "duplicate": known + sum(a.kind == "duplicate" for a in assignments),
                  "new": sum(a.kind != "duplicate" for a in assignments)},
        "stories": {"new": len({a.new_group for a in assignments if a.kind == "new"}),
                    "joined": len({a.story_id for a in assignments if a.kind == "existing"})},
    }

"""Ingest (plan §0.1 steps 2-4, §6.3, §6.5, §6.7): fetch every source, record its health,
normalise the items, drop known ones, cluster the rest into stories and store them.

``fetch_all`` and ``normalize`` write nothing (``sidereal run --dry-run`` composes them with
``plan_stories``); ``store`` does the writes. Each repo call is its own transaction, so a crash
keeps what was stored; a rerun inserts nothing twice (``item_exists`` + UNIQUE constraints).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import sidereal.sources  # noqa: F401  (registers every adapter kind)
from sidereal.db import Connection, items_repo, sources_repo, stories_repo
from sidereal.db.sources_repo import SourceRow
from sidereal.net.fetch import Fetcher
from sidereal.pipeline.common import short_error
from sidereal.pipeline.dedupe import (
    Assignment,
    KnownStory,
    NewItem,
    assign_stories,
    normalize_title,
    rollup_title,
)
from sidereal.sources.base import REGISTRY, FetchResult, RawItem, SourceBroken
from sidereal.textclean import clean_title, excerpt
from sidereal.timeutil import day_key
from sidereal.urls import canonicalize

log = logging.getLogger(__name__)

FETCH_CONCURRENCY = 6  # sources in flight (plan §9.2); the Fetcher limits 2 per host
EXCERPT_CHARS = 1500


@dataclass(frozen=True)
class SourceOutcome:
    source: SourceRow
    result: FetchResult | None  # None when the fetch failed
    error: str | None = None
    broken: bool = False


@dataclass(frozen=True)
class Normalized:
    source: SourceRow
    guid: str | None
    url: str
    canonical_url: str
    title: str
    title_norm: str
    author: str | None
    published: datetime | None
    excerpt: str
    cve_ids: tuple[str, ...]
    kev_vendor: str | None  # set for CISA KEV items (flags.kev)


@dataclass
class IngestResult:
    stats: dict[str, Any] = field(default_factory=dict)
    new_story_ids: list[int] = field(default_factory=list)
    joined_story_ids: list[int] = field(default_factory=list)  # existing stories that grew


async def _fetch_one(source: SourceRow, fetcher: Fetcher, now: datetime,
                     max_age_hours: float, sem: asyncio.Semaphore) -> SourceOutcome:
    async with sem:
        adapter_cls = REGISTRY.get(source.kind)
        if adapter_cls is None:
            return SourceOutcome(source, None, f"UnknownKind: {source.kind!r}")
        try:
            result = await adapter_cls().fetch(source, fetcher, now, max_age_hours=max_age_hours)
        except SourceBroken as exc:
            return SourceOutcome(source, None, short_error(exc), broken=True)
        except Exception as exc:  # one failing source never fails the run (§9.2)
            return SourceOutcome(source, None, short_error(exc))
        return SourceOutcome(source, result)


async def fetch_all(sources: Sequence[SourceRow], fetcher: Fetcher, now: datetime, *,
                    max_age_hours: float,
                    concurrency: int = FETCH_CONCURRENCY) -> list[SourceOutcome]:
    """Fetch every source concurrently; outcomes in input order. Never raises per source."""
    sem = asyncio.Semaphore(concurrency)
    return list(await asyncio.gather(
        *(_fetch_one(s, fetcher, now, max_age_hours, sem) for s in sources)
    ))


def record_health(conn: Connection, outcomes: Sequence[SourceOutcome],
                  *, at: datetime) -> dict[str, Any]:
    """Source health after the fetch (§6.5); returns the ``sources`` stats."""
    stats: dict[str, Any] = {"ok": 0, "failed": 0, "not_modified": 0, "failed_keys": []}
    for o in outcomes:
        sid = o.source.id
        if o.result is None:
            err = o.error or "unknown error"
            if o.broken:
                sources_repo.record_broken(conn, sid, at=at, error=err)
            else:
                sources_repo.record_fetch_error(conn, sid, at=at, error=err)
            stats["failed"] += 1
            stats["failed_keys"].append(o.source.key)
            log.warning("source %s failed: %s", o.source.key, err)
            continue
        r = o.result
        stats["ok"] += 1
        if r.not_modified:
            stats["not_modified"] += 1
            # a 304 need not repeat the validators: keep the stored ones then
            etag = r.etag if r.etag is not None else o.source.etag
            modified = r.last_modified if r.last_modified is not None else o.source.last_modified
            sources_repo.record_fetch_ok(conn, sid, at=at, etag=etag, last_modified=modified,
                                         entry_count=None)
        else:
            sources_repo.record_fetch_ok(conn, sid, at=at, etag=r.etag,
                                         last_modified=r.last_modified,
                                         entry_count=len(r.items))
    return stats


def normalize(source: SourceRow, raw: RawItem) -> Normalized | None:
    """Plain-text title/excerpt, canonical URL (§6.3); None when the URL is unusable."""
    try:
        canonical = canonicalize(raw.url)
    except ValueError:
        return None
    title = clean_title(raw.title) or canonical
    extra = raw.extra or {}
    cves = tuple(str(c) for c in extra.get("cve_ids") or ())
    vendor = str(extra.get("vendor") or "") if extra.get("kev") else None
    return Normalized(
        source=source, guid=raw.guid, url=raw.url.strip(), canonical_url=canonical,
        title=title, title_norm=normalize_title(title), author=raw.author,
        published=raw.published, excerpt=excerpt(raw.excerpt_html or "", EXCERPT_CHARS),
        cve_ids=cves, kev_vendor=vendor,
    )


def normalize_all(outcomes: Sequence[SourceOutcome]) -> tuple[list[Normalized], int]:
    """Normalised items of every successful fetch in source order, and the skipped count."""
    out: list[Normalized] = []
    skipped = 0
    for o in outcomes:
        for raw in o.result.items if o.result is not None else ():
            n = normalize(o.source, raw)
            if n is None:
                skipped += 1
            else:
                out.append(n)
    return out, skipped


def _exists(conn: Connection, n: Normalized) -> bool:
    return items_repo.item_exists(conn, canonical_url=n.canonical_url,
                                  source_id=n.source.id, guid=n.guid)


def plan_stories(conn: Connection, items: Sequence[Normalized], *, now: datetime,
                 window_hours: float) -> tuple[list[Normalized], list[Assignment], int]:
    """Drop items already stored, then cluster the rest against the recent stories.
    Returns ``(fresh items, assignments keyed by index into fresh, known duplicates)``.
    Reads only."""
    fresh = [n for n in items if not _exists(conn, n)]
    known = [
        KnownStory(r.id, tuple(r.title_norms), tuple(r.cve_ids))
        for r in stories_repo.recent_stories(conn, since=now - timedelta(hours=window_hours))
    ]
    new_items = [
        NewItem(key=i, source_key=n.source.key, guid=n.guid, canonical_url=n.canonical_url,
                title=n.title, cve_ids=n.cve_ids, published=n.published,
                is_msrc=n.source.kind == "msrc")
        for i, n in enumerate(fresh)
    ]
    return fresh, assign_stories(new_items, known), len(items) - len(fresh)


def _group_cves(fresh: Sequence[Normalized], assignments: Sequence[Assignment]) -> dict[int, list]:
    cves: dict[int, list[str]] = {}
    for a in assignments:
        if a.kind == "new" and a.new_group is not None:
            bucket = cves.setdefault(a.new_group, [])
            bucket.extend(c for c in fresh[a.item_key].cve_ids if c not in bucket)
    return cves


def store(conn: Connection, fresh: Sequence[Normalized],
          assignments: Sequence[Assignment], *, run_id: int, now: datetime,
          tz: str) -> IngestResult:
    """Create stories and insert items per the assignments (``item_exists`` is checked again
    before a story is created, so no empty story is left behind)."""
    res = IngestResult()
    group_story: dict[int, int] = {}
    group_cves = _group_cves(fresh, assignments)
    duplicate = inserted = 0
    day = day_key(now, tz)
    for a in assignments:
        n = fresh[a.item_key]
        if a.kind == "duplicate":
            duplicate += 1
            continue
        if a.kind == "existing":
            story_id = a.story_id
        else:
            story_id = group_story.get(a.new_group)
            if story_id is None:
                if _exists(conn, n):
                    duplicate += 1
                    continue
                if a.rollup_date is not None:
                    cves = group_cves.get(a.new_group, [])
                    title, story_cves = rollup_title(a.rollup_date, len(cves)), cves
                else:
                    title, story_cves = n.title, list(n.cve_ids)
                story_id = stories_repo.create_story(
                    conn, title=title, day=day, first_seen_at=now, first_run_id=run_id,
                    cve_ids=story_cves)
                group_story[a.new_group] = story_id
                res.new_story_ids.append(story_id)
        item_id = items_repo.insert_item(
            conn, source_id=n.source.id, story_id=story_id, guid=n.guid, url=n.url,
            canonical_url=n.canonical_url, title=n.title, title_norm=n.title_norm,
            author=n.author, published_at=n.published, first_seen_at=now, run_id=run_id,
            excerpt=n.excerpt)
        if item_id is None:  # UNIQUE conflict: stored meanwhile
            duplicate += 1
            continue
        inserted += 1
        stories_repo.attach_item(conn, story_id, item_id=item_id, seen_at=now,
                                 cve_ids=n.cve_ids)
        if n.kev_vendor is not None:
            stories_repo.merge_flags(conn, story_id, {"kev": True, "kev_vendor": n.kev_vendor})
        if a.kind == "existing" and story_id not in res.joined_story_ids:
            res.joined_story_ids.append(story_id)
    res.stats = {"inserted": inserted, "duplicate": duplicate}
    return res


async def ingest(conn: Connection, sources: Sequence[SourceRow], fetcher: Fetcher, *,
                 run_id: int, now: datetime, tz: str, max_age_hours: float,
                 window_hours: float) -> IngestResult:
    """Fetch, record health, normalise, dedupe, store. Returns stats for ``sources``,
    ``items`` and ``stories``."""
    outcomes = await fetch_all(sources, fetcher, now, max_age_hours=max_age_hours)
    src_stats = record_health(conn, outcomes, at=now)
    items, skipped = normalize_all(outcomes)
    fresh, assignments, known_dupes = plan_stories(conn, items, now=now,
                                                   window_hours=window_hours)
    res = store(conn, fresh, assignments, run_id=run_id, now=now, tz=tz)
    res.stats = {
        "sources": src_stats,
        "items": {"fetched": len(items) + skipped, "new": res.stats["inserted"],
                  "duplicate": known_dupes + res.stats["duplicate"], "skipped": skipped},
        "stories": {"new": len(res.new_story_ids), "joined": len(res.joined_story_ids)},
    }
    log.info("ingest: %d sources ok, %d failed; %d items new, %d duplicate; %d stories new",
             src_stats["ok"], src_stats["failed"], res.stats["items"]["new"],
             res.stats["items"]["duplicate"], len(res.new_story_ids))
    return res

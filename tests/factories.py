"""Demo data builder over the repos (plan §14): API tests, E2E and screenshots.

Run ``.venv/bin/python tests/factories.py --seed-demo <path>`` to write a demo database.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sidereal.db.assessments_repo import save_assessment
from sidereal.db.connect import connect
from sidereal.db.digests_repo import save_day_digest
from sidereal.db.items_repo import insert_item
from sidereal.db.migrations import apply_migrations
from sidereal.db.runs_repo import finish_run, start_run
from sidereal.db.seed import seed_sources
from sidereal.db.sources_repo import get_by_key
from sidereal.db.stories_repo import attach_item, create_story, set_score, set_state
from sidereal.defaults import SourceSeed
from sidereal.timeutil import day_key

DEMO_NOW = datetime(2026, 7, 14, 14, 30, tzinfo=UTC)  # a Tuesday, 15:30 in London (BST)
DEMO_TZ = "Europe/London"
KNOWN_SOURCES: dict[str, tuple[str, float]] = {
    "msrc-update-guide": ("MSRC Security Update Guide", 1.3),
    "azure-updates": ("Azure Updates", 1.3),
    "bleepingcomputer": ("BleepingComputer", 1.0),
    "hn": ("Hacker News", 0.7),
}
DEMO_TEMPLATES: tuple[dict[str, Any], ...] = (
    {"title": "Exploited Entra ID flaw patched", "state": "assessed", "bucket": "top",
     "score": 84.0, "sources": ("msrc-update-guide", "bleepingcomputer"),
     "focus": "entra-identity", "tags": ("entra", "cve"),
     "flags": {"kev": True, "exploited": True, "cvss": 9.8}, "cve_ids": ("CVE-2026-21001",)},
    {"title": "Azure Virtual WAN adds routing intent for IPv6", "state": "assessed",
     "bucket": "relevant", "score": 63.0, "sources": ("azure-updates",),
     "focus": "azure-networking", "tags": ("vwan",), "flags": {}, "cve_ids": ()},
    {"title": "Fortinet VPN appliances targeted in new campaign", "state": "assessed",
     "bucket": "relevant", "score": 52.5, "sources": ("bleepingcomputer", "hn"),
     "focus": "network-security", "tags": ("vpn",), "flags": {"exploited": True}, "cve_ids": ()},
    {"title": "Cloud egress pricing changes", "state": "assessed", "bucket": "side",
     "score": 31.0, "sources": ("hn",), "focus": "industry", "tags": ("pricing",),
     "flags": {}, "cve_ids": ()},
    {"title": "Defender for Cloud release notes", "state": "assess_failed", "bucket": "side",
     "score": None, "sources": ("azure-updates",), "focus": "none", "tags": (),
     "flags": {}, "cve_ids": ()},
    {"title": "Show HN: a terminal spreadsheet", "state": "assessed", "bucket": "drop",
     "score": 12.0, "sources": ("hn",), "focus": "none", "tags": (), "flags": {},
     "cve_ids": ()},
)


def ensure_source(conn: sqlite3.Connection, key: str, *, name: str | None = None,
                  weight: float | None = None) -> int:
    """Return the id of source *key*, creating it (rss, ``https://<key>.example``) if missing."""
    row = get_by_key(conn, key)
    if row is not None:
        return row.id
    default_name, default_weight = KNOWN_SOURCES.get(key, (key, 1.0))
    seed_sources(conn, [SourceSeed(
        key=key, name=name if name is not None else default_name, kind="rss",
        url=f"https://{key}.example/feed",
        weight=weight if weight is not None else default_weight,
    )])
    row = get_by_key(conn, key)
    assert row is not None
    return row.id


def make_run(conn: sqlite3.Connection, *, at: datetime, status: str = "ok",
             trigger: str = "timer", stats: Mapping[str, Any] | None = None,
             error: str | None = None) -> int:
    """Start a run at *at*; unless ``running``, finish it 5 minutes later."""
    rid = start_run(conn, trigger=trigger, at=at)
    if status != "running":
        finish_run(conn, rid, status=status, stats=dict(stats or {}),
                   at=at + timedelta(minutes=5), error=error)
    return rid


def make_story(conn: sqlite3.Connection, *, run_id: int, first_seen: datetime,
               title: str = "Demo story", tz: str = DEMO_TZ, state: str = "assessed",
               bucket: str | None = "relevant", score: float | None = 60.0,
               sources: Sequence[str] = ("bleepingcomputer",),
               urls: Sequence[str] | None = None, published: datetime | None = None,
               excerpt: str = "Original excerpt.", summary: str = "AI summary.",
               why: str = "Why it matters.", tags: Sequence[str] = ("azure",),
               focus: str = "azure-networking", flags: Mapping[str, Any] | None = None,
               cve_ids: Sequence[str] = ()) -> int:
    """Create a story with one item per source, stored the way the runner stores it."""
    if urls is not None and len(urls) != len(sources):
        raise ValueError("urls must match sources")
    sid = create_story(conn, title=title, day=day_key(first_seen, tz), first_seen_at=first_seen,
                       first_run_id=run_id, cve_ids=cve_ids, flags=flags)
    for i, key in enumerate(sources):
        src = ensure_source(conn, key)
        url = urls[i] if urls is not None else f"https://{key}.example/{sid}/{i}"
        iid = insert_item(
            conn, source_id=src, story_id=sid, guid=f"{key}:{sid}:{i}", url=url,
            canonical_url=f"https://{key}.example/c/{sid}/{i}", title=title,
            title_norm=title.lower(), author=None,
            published_at=published if published is not None else first_seen - timedelta(hours=1),
            first_seen_at=first_seen, run_id=run_id, excerpt=excerpt)
        assert iid is not None
        attach_item(conn, sid, item_id=iid, seen_at=first_seen)
    set_state(conn, sid, state)
    if state == "assessed":
        # raw mirrors assess_step: the model's reply plus the resolved focus.
        raw = {"relevance": 2, "urgency": 2, "actionability": 2, "novelty": 2,
               "focus": focus, "tags": list(tags),
               "exploited_in_wild": (flags or {}).get("exploited") is True,
               "summary": summary, "why": why}
        save_assessment(conn, sid, model="demo-model", prompt_version="assess.v1",
                        relevance=2, urgency=2, actionability=2, novelty=2, tags=tags,
                        summary=summary, why=why, raw=raw, duration_ms=1000, at=first_seen)
    if bucket is not None:
        set_score(conn, sid, score=score, bucket=bucket)
    return sid


def seed_demo(conn: sqlite3.Connection, *, now: datetime = DEMO_NOW,
              tz: str = DEMO_TZ) -> dict[str, int]:
    """Seed 3 local days of runs (local 01:00 + 4 h·k, up to *now*), stories and digests."""
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    counter = runs = stories = digests = 0
    for offset in (2, 1, 0):  # oldest day first
        d = today - timedelta(days=offset)
        picked: list[int] = []  # top/relevant story ids of the day
        last_run: int | None = None
        for k in range(6):  # local 01:00, 05:00, ... 21:00
            at = datetime.combine(d, time(1 + 4 * k), tzinfo=zone).astimezone(UTC)
            if at > now:
                break
            if (offset, k) == (2, 5):
                status = "failed"
            elif (offset, k) == (1, 3):
                status = "partial"
            else:
                status = "ok"
            last_run = make_run(conn, at=at, status=status, stats={"demo": True},
                                error="demo failure" if status == "failed" else None)
            runs += 1
            if status == "failed":
                continue
            for j in range(2):
                t = DEMO_TEMPLATES[counter % len(DEMO_TEMPLATES)]
                fields = {name: value for name, value in t.items() if name != "title"}
                sid = make_story(conn, run_id=last_run, first_seen=at + timedelta(minutes=10 + j),
                                 tz=tz, title=f"{t['title']} #{counter + 1}", **fields)
                counter += 1
                stories += 1
                if t["bucket"] in ("top", "relevant"):
                    picked.append(sid)
        if offset > 0 and last_run is not None:
            save_day_digest(conn, d.isoformat(), overview=f"Demo overview for {d.isoformat()}.",
                            headline=f"Demo headline for {d.isoformat()}", story_ids=picked,
                            model="demo-model", run_id=last_run, at=now)
            digests += 1
    return {"runs": runs, "stories": stories, "digests": digests}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factories")
    parser.add_argument("--seed-demo", metavar="PATH", type=Path, required=True)
    args = parser.parse_args(argv)
    path: Path = args.seed_demo
    if path.exists():
        sys.stderr.write(f"refusing to overwrite {path}\n")
        return 2
    conn = connect(path)
    apply_migrations(conn)
    counts = seed_demo(conn)
    conn.close()
    sys.stdout.write(f"seeded {path}: {counts['runs']} runs, {counts['stories']} stories, "
                     f"{counts['digests']} digests\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

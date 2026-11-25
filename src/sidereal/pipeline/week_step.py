"""Weekly digest (plan §16 M29): the week's TOP + best Relevant stories, one LLM overview.

When: the plan's "Sunday run builds week_digests". Every run on a local Sunday checks the
current ISO week, and every run checks the previous week, so the first run after Monday 00:00
local rewrites last week's digest when stories placed after the last Sunday run changed its
set (and writes it at all if no Sunday run got to it). A digest is written only when the set
is non-empty and differs (unordered) from the stored ``story_ids``, as day digests (M13b).

What: per local day of the week, ``place()`` over that day's assessed/assess_failed stories
(the Daily view's caps), hidden stories left out first; all TOP by score, then Relevant by
score, at most ``WEEK_MAX_STORIES``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sidereal.config import Settings
from sidereal.db import Connection, assessments_repo, feedback_repo, stories_repo
from sidereal.db import week_digests_repo as repo
from sidereal.llm import prompts, week_digest
from sidereal.llm.ollama import LLMOutputInvalid, OllamaClient
from sidereal.pipeline.scoring import Scored, place
from sidereal.timeutil import parse_iso_z
from sidereal.weeks import local_today, week_days, week_key, week_label

log = logging.getLogger(__name__)

WEEK_MAX_STORIES = 25
SUNDAY = 7  # date.isoweekday()


@dataclass(frozen=True)
class WeekEntry:
    bucket: str  # placed bucket: top | relevant
    story_id: int
    day: str
    score: float | None


def weeks_to_check(now: datetime, tz: str) -> list[str]:
    """The previous ISO week, plus the current one when it is Sunday in *tz*."""
    today = local_today(now, tz)
    weeks = [week_key(today - timedelta(days=7))]
    if today.isoweekday() == SUNDAY:
        weeks.append(week_key(today))
    return weeks


def week_set(conn: Connection, week: str, settings: Settings) -> list[WeekEntry]:
    """The week's digest set in digest order (TOP first, then by score, then id)."""
    rows = [s for day in week_days(week) for s in stories_repo.stories_for_day(conn, day)
            if s.bucket is not None and s.state in ("assessed", "assess_failed")]
    feedback = feedback_repo.story_feedback(conn, [s.id for s in rows])
    rows = [s for s in rows if not feedback[s.id].hidden]
    by_id = {s.id: s for s in rows}
    entries: list[WeekEntry] = []
    for day in week_days(week):
        placed = place([Scored(s.id, s.score, s.bucket, parse_iso_z(s.first_seen_at))
                        for s in rows if s.day == day], settings.scoring)
        entries += [WeekEntry(p.bucket, p.story_id, day, by_id[p.story_id].score)
                    for p in placed["top"] + placed["relevant"]]
    entries.sort(key=lambda e: (e.bucket != "top", -(e.score or 0.0), e.story_id))
    return entries[:WEEK_MAX_STORIES]


def _lines(conn: Connection, entries: list[WeekEntry]) -> list[prompts.DigestLine]:
    lines = []
    for e in entries:
        story = stories_repo.get_story(conn, e.story_id)
        a = assessments_repo.get_assessment(conn, e.story_id)
        if story is not None:
            lines.append(prompts.DigestLine(bucket=e.bucket, title=story.title,
                                            summary=a.summary if a else "", day=e.day))
    return lines


async def update_weeks(conn: Connection, ollama: OllamaClient, settings: Settings,
                       weeks: list[str], *, run_id: int, now: datetime,
                       deadline: Callable[[], bool] | None = None) -> dict[str, int]:
    """Write the digest of each week whose set changed. ``LLMUnavailable`` propagates; an
    invalid reply or an empty field after URL stripping is ``failed`` (retried next run)."""
    stats = {"written": 0, "unchanged": 0, "failed": 0, "skipped": 0}
    template = None
    for week in sorted(set(weeks)):
        entries = week_set(conn, week, settings)
        ids = [e.story_id for e in entries]
        existing = repo.get_week_digest(conn, week)
        if not ids or (existing is not None and set(existing.story_ids) == set(ids)):
            stats["unchanged"] += 1
            continue
        if deadline is not None and deadline():
            stats["skipped"] += 1
            continue
        template = template or prompts.load_prompt("week_digest")
        system, user = prompts.render(
            template, week_label=week_label(week),
            stories=prompts.render_digest_stories(_lines(conn, entries), with_day=True))
        try:
            res = await week_digest.write_week_digest(
                ollama, model=settings.models.digest, system=system, user=user,
                keep_alive=settings.models.keep_alive)
        except LLMOutputInvalid as exc:
            log.warning("week digest %s: %s", week, type(exc).__name__)
            stats["failed"] += 1
            continue
        if not res.overview or not res.headline:
            log.warning("week digest %s: empty field after URL stripping", week)
            stats["failed"] += 1
            continue
        repo.save_week_digest(conn, week, overview=res.overview, headline=res.headline,
                              story_ids=ids, model=settings.models.digest, run_id=run_id,
                              at=now)
        stats["written"] += 1
    return stats

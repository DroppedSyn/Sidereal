"""Day digests (plan §0.1 step 10, §7.3): regenerate a day's overview only when its placed
TOP + Relevant set differs from the set the stored digest was built from."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime

from sidereal.config import Settings
from sidereal.db import Connection, assessments_repo, digests_repo, feedback_repo, stories_repo
from sidereal.llm import digest, prompts
from sidereal.llm.ollama import LLMOutputInvalid, OllamaClient
from sidereal.pipeline.scoring import Scored, place
from sidereal.timeutil import day_label, parse_iso_z

log = logging.getLogger(__name__)


def digest_set(conn: Connection, day: str, settings: Settings) -> list[tuple[str, int]]:
    """``[(bucket, story_id)]`` of the day's placed TOP then Relevant stories (caps applied,
    score order), as the Daily view shows them: hidden stories are left out before placement."""
    rows = [s for s in stories_repo.stories_for_day(conn, day)
            if s.bucket is not None and s.state in ("assessed", "assess_failed")]
    feedback = feedback_repo.story_feedback(conn, [s.id for s in rows])
    scored = [Scored(s.id, s.score, s.bucket, parse_iso_z(s.first_seen_at))
              for s in rows if not feedback[s.id].hidden]
    placed = place(scored, settings.scoring)
    return [(x.bucket, x.story_id) for x in placed["top"] + placed["relevant"]]


def _lines(conn: Connection, entries: list[tuple[str, int]]) -> list[prompts.DigestLine]:
    lines = []
    for bucket, sid in entries:
        story = stories_repo.get_story(conn, sid)
        a = assessments_repo.get_assessment(conn, sid)
        if story is not None:
            lines.append(prompts.DigestLine(bucket=bucket, title=story.title,
                                            summary=a.summary if a else ""))
    return lines


async def update_days(conn: Connection, ollama: OllamaClient, settings: Settings,
                      days: Iterable[str], *, run_id: int, now: datetime,
                      deadline: Callable[[], bool] | None = None) -> dict[str, int]:
    """Write the digest of each day whose TOP/Relevant set changed. A day with an empty set
    keeps whatever digest it has. ``LLMUnavailable`` propagates; an invalid reply or an
    empty field after URL stripping counts as ``failed`` and is retried by the next run."""
    stats = {"written": 0, "unchanged": 0, "failed": 0, "skipped": 0}
    template = None
    for day in sorted(set(days)):
        entries = digest_set(conn, day, settings)
        ids = [sid for _, sid in entries]
        existing = digests_repo.get_day_digest(conn, day)
        if not ids or (existing is not None and set(existing.story_ids) == set(ids)):
            stats["unchanged"] += 1
            continue
        if deadline is not None and deadline():
            stats["skipped"] += 1
            continue
        template = template or prompts.load_prompt("day_digest")
        system, user = prompts.render(
            template, day_label=day_label(day),
            stories=prompts.render_digest_stories(_lines(conn, entries)))
        try:
            res = await digest.write_digest(ollama, model=settings.models.digest, system=system,
                                            user=user, keep_alive=settings.models.keep_alive)
        except LLMOutputInvalid as exc:
            log.warning("digest %s: %s", day, type(exc).__name__)
            stats["failed"] += 1
            continue
        if not res.overview or not res.headline:
            log.warning("digest %s: empty field after URL stripping", day)
            stats["failed"] += 1
            continue
        digests_repo.save_day_digest(conn, day, overview=res.overview, headline=res.headline,
                                     story_ids=ids, model=settings.models.digest,
                                     run_id=run_id, at=now)
        stats["written"] += 1
    return stats

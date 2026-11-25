"""pipeline/digest_step.py (M13b): a day's digest is rewritten only when its set changed."""

from __future__ import annotations

import httpx
import pytest

from sidereal.db import assessments_repo, digests_repo, stories_repo
from sidereal.llm.ollama import LLMUnavailable
from sidereal.pipeline import digest_step
from tests.pipeline_helpers import NOW, add_story, chats, ollama_for, seeded_db, smart_ollama, start

DAY = "2026-11-25"


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def placed(conn, bucket, score, *, day=DAY, state="assessed", summary="sum"):
    sid = add_story(conn, start(conn), day=day, title=f"Story {bucket} {score}")
    stories_repo.set_score(conn, sid, score=score, bucket=bucket)
    stories_repo.set_state(conn, sid, state)
    if state == "assessed":
        assessments_repo.save_assessment(
            conn, sid, model="m", prompt_version="assess.v1", relevance=3, urgency=1,
            actionability=1, novelty=1, tags=[], summary=summary, why="w", raw={},
            duration_ms=1, at=NOW)
    return sid


async def update(conn, settings, fake, days=(DAY,), **kw):
    return await digest_step.update_days(conn, ollama_for(fake, settings), settings, days,
                                         run_id=start(conn), now=NOW, **kw)


def test_digest_set_is_placed_top_then_relevant(conn, settings):
    rel = placed(conn, "relevant", 50.0)
    top = placed(conn, "top", 80.0)
    placed(conn, "side", 30.0)
    placed(conn, "top", 75.0, day="2026-11-24")
    capped = settings.model_copy(update={"scoring": settings.scoring.model_copy(
        update={"top_cap": 0})})
    assert digest_step.digest_set(conn, DAY, settings) == [("top", top), ("relevant", rel)]
    assert digest_step.digest_set(conn, DAY, capped) == [("relevant", top), ("relevant", rel)]


async def test_writes_once_then_unchanged_then_rewrites_on_change(conn, settings):
    top = placed(conn, "top", 80.0, summary="Top summary")
    fake = smart_ollama()
    assert await update(conn, settings, fake) == {"written": 1, "unchanged": 0, "failed": 0,
                                                  "skipped": 0}
    d = digests_repo.get_day_digest(conn, DAY)
    assert (d.overview, d.headline, d.story_ids, d.model) == (
        "The day in brief.", "A headline", [top], settings.models.digest)
    user = chats(fake, "digest")[0]["messages"][1]["content"]
    assert "[TOP] Story top 80.0: Top summary" in user and "Wednesday - 25.11.2026" in user
    stories_repo.set_score(conn, top, score=82.0, bucket="top")  # same set, new score
    assert (await update(conn, settings, fake))["unchanged"] == 1
    assert len(chats(fake, "digest")) == 1
    placed(conn, "relevant", 55.0)
    assert (await update(conn, settings, fake))["written"] == 1
    assert len(chats(fake, "digest")) == 2


async def test_empty_set_writes_nothing(conn, settings):
    placed(conn, "side", 30.0)
    placed(conn, "side", None, state="assess_failed")
    fake = smart_ollama()
    assert (await update(conn, settings, fake))["unchanged"] == 1
    assert chats(fake, "digest") == [] and digests_repo.get_day_digest(conn, DAY) is None


async def test_invalid_or_url_only_reply_is_not_saved(conn, settings):
    placed(conn, "top", 80.0)
    bad = smart_ollama(digest={"overview": "", "headline": "x"})
    assert (await update(conn, settings, bad))["failed"] == 1
    urls = smart_ollama(digest={"overview": "https://evil.example/x", "headline": "Head"})
    assert (await update(conn, settings, urls))["failed"] == 1
    assert digests_repo.get_day_digest(conn, DAY) is None


async def test_deadline_skips_and_unavailable_propagates(conn, settings):
    placed(conn, "top", 80.0)
    fake = smart_ollama()
    assert (await update(conn, settings, fake, deadline=lambda: True))["skipped"] == 1
    assert chats(fake, "digest") == []
    fake.errors["/api/chat"] = httpx.ConnectError("down")
    with pytest.raises(LLMUnavailable):
        await update(conn, settings, fake)

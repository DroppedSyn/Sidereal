"""pipeline/week_step.py (M29): which weeks a run checks, the week's set, write on change."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sidereal.db import assessments_repo, feedback_repo, stories_repo
from sidereal.db import week_digests_repo as repo
from sidereal.pipeline import week_step
from sidereal.pipeline.runner import run_once
from tests.pipeline_helpers import (
    NOW,
    FeedServer,
    add_story,
    chats,
    ollama_for,
    seeded_db,
    smart_ollama,
    start,
)

WEEK = "2026-W48"  # Monday 23.11.2026 .. Sunday 29.11.2026


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def placed(conn, bucket, score, *, day="2026-11-25", state="assessed", summary="Sum",
           title=None):
    sid = add_story(conn, start(conn), day=day, title=title or f"Story {bucket} {score} {day}")
    stories_repo.set_score(conn, sid, score=score, bucket=bucket)
    stories_repo.set_state(conn, sid, state)
    if state == "assessed":
        assessments_repo.save_assessment(
            conn, sid, model="m", prompt_version="assess.v1", relevance=3, urgency=1,
            actionability=1, novelty=1, tags=[], summary=summary, why="w", raw={},
            duration_ms=1, at=NOW)
    return sid


def ids(conn, settings, week=WEEK):
    return [e.story_id for e in week_step.week_set(conn, week, settings)]


async def update(conn, settings, fake, weeks=(WEEK,), **kw):
    return await week_step.update_weeks(conn, ollama_for(fake, settings), settings, list(weeks),
                                        run_id=start(conn), now=NOW, **kw)


def week_chats(fake):
    return [b for b in chats(fake, "digest") if "Stories for Week" in b["messages"][1]["content"]]


# --- which weeks -------------------------------------------------------------------------

@pytest.mark.parametrize(("now", "weeks"), [
    (datetime(2026, 11, 25, 12, 0, tzinfo=UTC), ["2026-W47"]),  # Wednesday
    (datetime(2026, 11, 29, 12, 0, tzinfo=UTC), ["2026-W47", "2026-W48"]),  # Sunday
    (datetime(2026, 11, 30, 0, 30, tzinfo=UTC), ["2026-W48"]),  # first run after Monday 00:00
    # DST start week: Sunday 29.03.2026 23:30 UTC is already Monday 00:30 in London.
    (datetime(2026, 3, 29, 23, 30, tzinfo=UTC), ["2026-W13"]),
    (datetime(2026, 3, 29, 22, 30, tzinfo=UTC), ["2026-W12", "2026-W13"]),
    # DST end week: Sunday 25.10.2026 23:30 UTC is still Sunday 23:30 in London.
    (datetime(2026, 10, 25, 23, 30, tzinfo=UTC), ["2026-W42", "2026-W43"]),
    # Year boundary: Sunday 03.01.2027 closes 2026-W53, Monday 04.01.2027 opens 2027-W01.
    (datetime(2027, 1, 3, 18, 0, tzinfo=UTC), ["2026-W52", "2026-W53"]),
    (datetime(2027, 1, 4, 6, 0, tzinfo=UTC), ["2026-W53"]),
])
def test_weeks_to_check_by_local_date(now, weeks):
    assert week_step.weeks_to_check(now, "Europe/London") == weeks


def test_weeks_to_check_west_of_utc():
    # Monday 04:00 UTC is Sunday 23:00 in New York: the current week is still 2026-W53.
    now = datetime(2027, 1, 4, 4, 0, tzinfo=UTC)
    assert week_step.weeks_to_check(now, "America/New_York") == ["2026-W52", "2026-W53"]


# --- the set ------------------------------------------------------------------------------

def test_set_is_the_weeks_top_then_relevant_by_score(conn, settings):
    rel_mon = placed(conn, "relevant", 55.0, day="2026-11-23")
    top_sun = placed(conn, "top", 70.0, day="2026-11-29")
    top_wed = placed(conn, "top", 90.0)
    rel_wed = placed(conn, "relevant", 65.0)
    placed(conn, "side", 40.0)
    placed(conn, "drop", 10.0)
    placed(conn, "top", 99.0, day="2026-11-22")  # previous week (Sunday)
    placed(conn, "top", 99.0, day="2026-11-30")  # next week (Monday)
    assert ids(conn, settings) == [top_wed, top_sun, rel_wed, rel_mon]
    entries = week_step.week_set(conn, WEEK, settings)
    assert [(e.bucket, e.day) for e in entries] == [
        ("top", "2026-11-25"), ("top", "2026-11-29"), ("relevant", "2026-11-25"),
        ("relevant", "2026-11-23")]


def test_set_leaves_out_hidden_stories(conn, settings):
    keep = placed(conn, "top", 80.0)
    hidden = placed(conn, "top", 85.0)
    hidden_rel = placed(conn, "relevant", 60.0)
    feedback_repo.set_hidden(conn, hidden, True, at=NOW)
    feedback_repo.set_hidden(conn, hidden_rel, True, at=NOW)
    assert ids(conn, settings) == [keep]


def test_hidden_story_does_not_take_a_daily_cap_slot(conn, settings):
    capped = settings.model_copy(update={"scoring": settings.scoring.model_copy(
        update={"top_cap": 1, "relevant_cap": 0})})
    hidden = placed(conn, "top", 90.0)
    second = placed(conn, "top", 80.0)
    feedback_repo.set_hidden(conn, hidden, True, at=NOW)
    assert ids(conn, capped) == [second]


def test_daily_caps_apply_per_day(conn, settings):
    capped = settings.model_copy(update={"scoring": settings.scoring.model_copy(
        update={"top_cap": 1, "relevant_cap": 1})})
    a = placed(conn, "top", 90.0, day="2026-11-24")
    b = placed(conn, "top", 80.0, day="2026-11-24")  # overflows into Relevant
    placed(conn, "top", 70.0, day="2026-11-24")  # overflows to side: not in the set
    c = placed(conn, "top", 60.0, day="2026-11-26")
    entries = week_step.week_set(conn, WEEK, capped)
    assert [(e.bucket, e.story_id) for e in entries] == [("top", a), ("top", c), ("relevant", b)]


def test_set_capped_at_25(conn, settings):
    for k in range(30):
        placed(conn, "relevant", 30.0 + k, day=f"2026-11-{23 + k % 7}")
    top = placed(conn, "top", 75.0, day="2026-11-29")
    got = ids(conn, settings)
    assert len(got) == week_step.WEEK_MAX_STORIES == 25
    assert got[0] == top


def test_set_of_week_53_spans_the_new_year(conn, settings):
    a = placed(conn, "top", 80.0, day="2026-12-28")
    b = placed(conn, "top", 70.0, day="2027-01-03")
    placed(conn, "top", 90.0, day="2027-01-04")
    assert ids(conn, settings, "2026-W53") == [a, b]


# --- writing ------------------------------------------------------------------------------

async def test_writes_once_then_unchanged_then_rewrites_on_change(conn, settings):
    placed(conn, "top", 80.0, day="2026-11-23", title="Entra flaw fixed", summary="Patched.")
    fake = smart_ollama(digest={"overview": "First.", "headline": "H1"})
    assert await update(conn, settings, fake) == {"written": 1, "unchanged": 0, "failed": 0,
                                                  "skipped": 0}
    user = week_chats(fake)[0]["messages"][1]["content"]
    assert "Stories for Week 48 · 23.11.2026 – 29.11.2026" in user
    assert "[TOP] 2026-11-23 — Entra flaw fixed: Patched." in user
    assert "<untrusted_article>" in user
    row = repo.get_week_digest(conn, WEEK)
    assert (row.overview, row.headline, row.model) == ("First.", "H1", settings.models.digest)

    assert (await update(conn, settings, fake))["unchanged"] == 1
    assert len(week_chats(fake)) == 1

    new = placed(conn, "relevant", 60.0, day="2026-11-29")
    assert (await update(conn, settings, fake))["written"] == 1
    assert len(week_chats(fake)) == 2
    assert new in repo.get_week_digest(conn, WEEK).story_ids


async def test_score_change_within_the_same_set_is_unchanged(conn, settings):
    sid = placed(conn, "top", 80.0)
    fake = smart_ollama()
    await update(conn, settings, fake)
    stories_repo.set_score(conn, sid, score=81.0, bucket="top")
    assert (await update(conn, settings, fake))["unchanged"] == 1
    assert len(week_chats(fake)) == 1


async def test_hiding_a_story_changes_the_set(conn, settings):
    placed(conn, "top", 80.0)
    gone = placed(conn, "relevant", 60.0)
    fake = smart_ollama()
    await update(conn, settings, fake)
    feedback_repo.set_hidden(conn, gone, True, at=NOW)
    assert (await update(conn, settings, fake))["written"] == 1
    assert gone not in repo.get_week_digest(conn, WEEK).story_ids
    assert "Story relevant 60.0" not in week_chats(fake)[1]["messages"][1]["content"]


async def test_empty_week_writes_nothing_and_keeps_an_old_digest(conn, settings):
    fake = smart_ollama()
    assert (await update(conn, settings, fake))["unchanged"] == 1
    assert week_chats(fake) == [] and repo.get_week_digest(conn, WEEK) is None


async def test_urls_are_stripped_before_saving(conn, settings):
    placed(conn, "top", 80.0)
    fake = smart_ollama(digest={"overview": "See https://evil.example/p now.\n\nMore.",
                                "headline": "Read http://x.example/a"})
    await update(conn, settings, fake)
    row = repo.get_week_digest(conn, WEEK)
    assert (row.overview, row.headline) == ("See now.\n\nMore.", "Read")


async def test_url_only_reply_fails_and_saves_nothing(conn, settings):
    placed(conn, "top", 80.0)
    fake = smart_ollama(digest={"overview": "https://a.example/", "headline": "Fine"})
    assert (await update(conn, settings, fake))["failed"] == 1
    assert repo.get_week_digest(conn, WEEK) is None


async def test_invalid_reply_is_failed(conn, settings):
    placed(conn, "top", 80.0)
    fake = smart_ollama(digest={"overview": "", "headline": "x"})
    assert (await update(conn, settings, fake))["failed"] == 1


async def test_deadline_skips(conn, settings):
    placed(conn, "top", 80.0)
    fake = smart_ollama()
    assert (await update(conn, settings, fake, deadline=lambda: True))["skipped"] == 1
    assert week_chats(fake) == []


# --- in a run -----------------------------------------------------------------------------

async def test_sunday_run_writes_the_current_week(conn, settings):
    sid = placed(conn, "top", 80.0, day="2026-11-29")
    fake = smart_ollama()
    sunday = datetime(2026, 11, 29, 9, 0, tzinfo=UTC)
    row = await run_once(settings, conn, fetcher=FeedServer(conn).fetcher(),
                         ollama=ollama_for(fake, settings), now=sunday)
    assert row.stats["week_digest"]["written"] == 1
    assert sid in repo.get_week_digest(conn, WEEK).story_ids


async def test_weekday_run_does_not_write_the_current_week(conn, settings):
    placed(conn, "top", 80.0, day="2026-11-25")
    fake = smart_ollama()
    row = await run_once(settings, conn, fetcher=FeedServer(conn).fetcher(),
                         ollama=ollama_for(fake, settings), now=NOW)
    assert row.stats["week_digest"] == {"written": 0, "unchanged": 1, "failed": 0, "skipped": 0}
    assert repo.get_week_digest(conn, WEEK) is None

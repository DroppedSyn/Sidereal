"""M24 wiring in the pipeline: votes feed the boost on placement and rescore; mutes reach the
prefilter inside ``assess_step``."""

from __future__ import annotations

import pytest

from sidereal.config import ScoringSettings
from sidereal.db import assessments_repo, feedback_repo, stories_repo
from sidereal.pipeline import assess_step, placement
from sidereal.pipeline.common import Deadline
from sidereal.pipeline.scoring import Rubric, StorySignals, score_story
from tests.pipeline_helpers import (
    NOW,
    FeedServer,
    add_story,
    ollama_for,
    seeded_db,
    smart_ollama,
    start,
)

CFG = ScoringSettings()
PLAIN = "Local bakery wins regional bread award again"  # no focus keyword: goes to triage


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def assessed(conn, *, source="bleepingcomputer", focus="none", tags=(), rel=2,
             extra_sources=()):
    sid = add_story(conn, start(conn), source=source, extra_sources=extra_sources)
    assessments_repo.save_assessment(
        conn, sid, model="m", prompt_version="assess.v1", relevance=rel, urgency=2,
        actionability=2, novelty=2, tags=list(tags), summary="s", why="w",
        raw={"focus": focus}, duration_ms=1, at=NOW)
    stories_repo.set_state(conn, sid, "assessed")
    return sid


def vote(conn, sid, v):
    feedback_repo.set_vote(conn, sid, v, at=NOW)


def plain_score(rel=2):
    return score_story(Rubric(rel, 2, 2, 2), StorySignals(source_weights=(1.0,)), CFG)


def test_rescore_without_feedback_has_no_boost(conn):
    sid = assessed(conn)
    placement.rescore(conn, CFG)
    assert stories_repo.get_story(conn, sid).score == pytest.approx(plain_score())


def test_rescore_applies_source_boost(conn):
    target = assessed(conn)
    voted = [assessed(conn) for _ in range(3)]
    for v in voted:
        vote(conn, v, "up")
    other = assessed(conn, source="krebs")  # krebs weight 0.9, no votes
    placement.rescore(conn, CFG)
    boost = 10 * 3 / (3 + 5)
    assert stories_repo.get_story(conn, target).score == pytest.approx(plain_score() + boost)
    krebs = score_story(Rubric(2, 2, 2, 2), StorySignals(source_weights=(0.9,)), CFG)
    assert stories_repo.get_story(conn, other).score == pytest.approx(krebs)


def test_rescore_applies_focus_and_tag_boost(conn):
    target = assessed(conn, source="krebs", focus="entra-identity", tags=("mfa",))
    for _ in range(2):
        vote(conn, assessed(conn, source="thehackernews", focus="entra-identity", tags=("mfa",)),
             "down")
    placement.rescore(conn, CFG)
    topic = -10 * 2 / 7  # focus and tag both -2/7 × 10; their mean is the same
    sig = StorySignals(source_weights=(0.9,), focus_tier="primary")
    expected = score_story(Rubric(2, 2, 2, 2), sig, CFG) + topic
    assert stories_repo.get_story(conn, target).score == pytest.approx(expected)


def test_rescore_boost_can_move_bucket(conn):
    # 2/2/2/2 → 66.7 relevant; +10 (clamped) lifts it over the top threshold 72
    target = assessed(conn, focus="none", tags=("x",))
    for _ in range(40):
        vote(conn, assessed(conn, tags=("x",)), "up")
    placement.rescore(conn, CFG)
    row = stories_repo.get_story(conn, target)
    assert row.score == pytest.approx(plain_score() + 10.0)  # 8.9 + 8.9 clamped to 10
    assert row.bucket == "top"


def test_clearing_votes_removes_boost(conn):
    target = assessed(conn)
    v = assessed(conn)
    vote(conn, v, "up")
    placement.rescore(conn, CFG)
    assert stories_repo.get_story(conn, target).score > plain_score()
    vote(conn, v, None)
    placement.rescore(conn, CFG)
    assert stories_repo.get_story(conn, target).score == pytest.approx(plain_score())


def test_refresh_applies_boost(conn):
    target = assessed(conn)
    vote(conn, assessed(conn), "down")
    placement.refresh(conn, [target], CFG)
    assert stories_repo.get_story(conn, target).score == pytest.approx(plain_score() - 10 / 6)


async def run(conn, settings, fake=None):
    fake = fake or smart_ollama()
    res = await assess_step.run_assess(conn, ollama_for(fake, settings),
                                       FeedServer(conn).fetcher(), settings, now=NOW,
                                       deadline=Deadline(None))
    return res, fake


async def test_assess_step_places_with_boost(settings, conn):
    for _ in range(5):
        vote(conn, assessed(conn), "up")
    sid = add_story(conn, start(conn), title=PLAIN)
    await run(conn, settings)
    row = stories_repo.get_story(conn, sid)
    assert row.state == "assessed"
    a = assessments_repo.get_assessment(conn, sid)
    sig = StorySignals(source_weights=(1.0,),
                       focus_tier=placement.focus_tiers(conn)[a.raw["focus"]])
    expected = score_story(placement.rubric_of(a), sig, CFG) + 5.0  # 10 × 5/10
    assert row.score == pytest.approx(expected)


async def test_muted_source_is_filtered(settings, conn):
    feedback_repo.add_mute(conn, "source", "bleepingcomputer", at=NOW)
    muted = add_story(conn, start(conn), title=PLAIN)
    both = add_story(conn, start(conn), title=PLAIN + " two", extra_sources=("krebs",))
    res, _ = await run(conn, settings)
    row = stories_repo.get_story(conn, muted)
    assert (row.state, row.filter_reason) == ("filtered", "muted_source")
    assert stories_repo.get_story(conn, both).state == "assessed"  # one source still unmuted
    assert res.stats["prefilter"]["filtered"] == 1


async def test_muted_keyword_is_filtered(settings, conn):
    feedback_repo.add_mute(conn, "keyword", "Bakery", at=NOW)
    muted = add_story(conn, start(conn), title=PLAIN)
    kept = add_story(conn, start(conn), title="Regional bread award goes to a mill")
    await run(conn, settings)
    row = stories_repo.get_story(conn, muted)
    assert (row.state, row.filter_reason) == ("filtered", "muted_keyword")
    assert stories_repo.get_story(conn, kept).state == "assessed"


async def test_no_mutes_nothing_filtered(settings, conn):
    sid = add_story(conn, start(conn), title=PLAIN)
    await run(conn, settings)
    assert stories_repo.get_story(conn, sid).state == "assessed"

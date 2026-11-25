"""pipeline/placement.py (M13b): score + bucket from stored assessments, never from the model."""

from __future__ import annotations

import pytest

from sidereal.config import ScoringSettings
from sidereal.db import assessments_repo, sources_repo, stories_repo
from sidereal.pipeline import placement
from sidereal.pipeline.common import bundle
from sidereal.pipeline.scoring import Rubric, StorySignals, bucket_for, score_story
from tests.pipeline_helpers import NOW, add_story, seeded_db, start

CFG = ScoringSettings()


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def assess(conn, sid, rel=3, urg=2, act=2, nov=2, **raw):
    assessments_repo.save_assessment(
        conn, sid, model="m", prompt_version="assess.v1", relevance=rel, urgency=urg,
        actionability=act, novelty=nov, tags=[], summary="s", why="w",
        raw={"focus": "none", **raw}, duration_ms=1, at=NOW)
    stories_repo.set_state(conn, sid, "assessed")
    return assessments_repo.get_assessment(conn, sid)


def place(conn, sid):
    sources = {s.id: s for s in sources_repo.list_sources(conn)}
    story = stories_repo.get_story(conn, sid)
    a = assessments_repo.get_assessment(conn, sid)
    bucket = placement.place_assessed(conn, bundle(conn, story, sources), a,
                                      placement.focus_tiers(conn), CFG)
    return bucket, stories_repo.get_story(conn, sid)


def test_model_bucket_and_score_in_reply_are_ignored(conn):
    sid = add_story(conn, start(conn))
    assess(conn, sid, rel=0, urg=3, act=3, nov=3, bucket="top", score=99)
    bucket, story = place(conn, sid)
    assert bucket == story.bucket == "drop"  # relevance 0 → drop, whatever the reply says
    assert story.score == score_story(Rubric(0, 3, 3, 3), StorySignals(source_weights=(1.0,)))


def test_signals_from_flags_sources_and_focus(conn):
    sid = add_story(conn, start(conn), source="tc-entra", extra_sources=("krebs",),
                    flags={"kev": True, "cvss": 9.8})
    assess(conn, sid, rel=2, urg=1, act=1, nov=1, focus="entra-identity",
           exploited_in_wild=True)
    bucket, story = place(conn, sid)
    sig = StorySignals(kev=True, max_cvss=9.8, source_weights=(1.4, 0.9), focus_tier="primary")
    r = Rubric(2, 1, 1, 1, exploited_in_wild=True)
    assert story.score == pytest.approx(score_story(r, sig))
    assert bucket == bucket_for(story.score, r, sig)


def test_low_weight_single_source_not_top(conn):
    sid = add_story(conn, start(conn), source="schneier")  # weight 0.6
    assess(conn, sid, rel=1, urg=3, act=3, nov=3, exploited_in_wild=True)
    _, story = place(conn, sid)
    assert story.score >= CFG.top_threshold and story.bucket == "relevant"


def test_bad_flag_values_are_not_signals(conn):
    sid = add_story(conn, start(conn), flags={"kev": "yes", "cvss": True})
    b = bundle(conn, stories_repo.get_story(conn, sid),
               {s.id: s for s in sources_repo.list_sources(conn)})
    sig = placement.signals_for(b, "unknown-key", {"x": "primary"})
    assert sig == StorySignals(kev=False, max_cvss=None, source_weights=(1.0,), focus_tier=None)


def test_mark_failed_is_side_without_score(conn):
    sid = add_story(conn, start(conn))
    assert placement.mark_failed(conn, sid) == "side"
    story = stories_repo.get_story(conn, sid)
    assert (story.state, story.bucket, story.score) == ("assess_failed", "side", None)


def test_rescore_recomputes_from_stored_assessments(conn):
    run = start(conn)
    a = add_story(conn, run, day="2026-11-24")
    b = add_story(conn, run, day="2026-11-25")
    c = add_story(conn, run, day="2026-11-25")
    pending = add_story(conn, run, day="2026-11-25")
    assess(conn, a, rel=3, urg=3, act=3, nov=3)
    assess(conn, b, rel=3, urg=3, act=3, nov=3)
    placement.mark_failed(conn, c)
    out = placement.rescore(conn, CFG)
    assert out["rescored"] == 3 and out["days"] == ["2026-11-24", "2026-11-25"]
    assert out["buckets"] == {"top": 2, "relevant": 0, "side": 1, "drop": 0}
    strict = CFG.model_copy(update={"top_threshold": 101.0})
    out = placement.rescore(conn, strict, day="2026-11-25")
    assert out["rescored"] == 2 and out["buckets"]["relevant"] == 1
    assert stories_repo.get_story(conn, b).bucket == "relevant"
    assert stories_repo.get_story(conn, a).bucket == "top"  # other day untouched
    assert stories_repo.get_story(conn, pending).bucket is None


def test_refresh_only_touches_assessed_stories(conn):
    run = start(conn)
    done = add_story(conn, run, day="2026-11-23")
    new = add_story(conn, run)
    assess(conn, done)
    days = placement.refresh(conn, [done, new, 9999], CFG)
    assert days == {"2026-11-23"}
    assert stories_repo.get_story(conn, done).bucket is not None
    assert stories_repo.get_story(conn, new).bucket is None

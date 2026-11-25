from datetime import UTC, datetime, timedelta

import pytest
from pytest import approx

from sidereal.config import ScoringSettings
from sidereal.pipeline.scoring import (
    Rubric,
    Scored,
    StorySignals,
    bucket_for,
    gazette_order,
    place,
    recency_factor,
    score_story,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
NEUTRAL = 46.666666666666664
PLUS10 = 56.666666666666664  # neutral + 10


def rubric(**kw):
    return Rubric(**{"relevance": 2, "urgency": 1, "actionability": 1, "novelty": 1, **kw})


def signals(**kw):
    return StorySignals(**{"focus_tier": "secondary", **kw})


def scored(story_id, score, bucket, hours_ago=1.0):
    return Scored(story_id, score, bucket, NOW - timedelta(hours=hours_ago))


def ids(xs):
    return [x.story_id for x in xs]


def test_base_formula():
    full = rubric(relevance=3, urgency=3, actionability=3, novelty=3)
    assert score_story(full, signals()) == approx(100.0)
    low = rubric(relevance=2, urgency=1, actionability=1, novelty=0)
    assert score_story(low, signals()) == approx(41.666666666666664)
    mixed = rubric(relevance=3, urgency=2, actionability=1, novelty=2)
    assert score_story(mixed, signals()) == approx(73.33333333333334)
    rel_only = rubric(relevance=1, urgency=0, actionability=0, novelty=0)
    assert score_story(rel_only, signals()) == approx(13.333333333333334)
    assert score_story(rubric(), signals()) == approx(NEUTRAL)


def test_kev_bonus():
    assert score_story(rubric(), signals(kev=True)) == approx(58.666666666666664)


def test_exploited_bonus():
    assert score_story(rubric(exploited_in_wild=True), signals()) == approx(54.666666666666664)


@pytest.mark.parametrize(
    ("cvss", "expected"),
    [
        (9.0, 54.666666666666664),
        (8.9, 50.666666666666664),
        (7.0, 50.666666666666664),
        (6.9, 46.666666666666664),
        (None, 46.666666666666664),
    ],
)
def test_cvss_bonus(cvss, expected):
    assert score_story(rubric(), signals(max_cvss=cvss)) == approx(expected)


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, 46.666666666666664),
        (2, 50.666666666666664),
        (3, 54.666666666666664),
        (4, 58.666666666666664),
        (5, 58.666666666666664),
    ],
)
def test_corroboration_bonus(n, expected):
    assert score_story(rubric(), signals(source_weights=(1.0,) * n)) == approx(expected)


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("primary", 51.666666666666664),
        ("secondary", 46.666666666666664),
        ("side", 41.666666666666664),
        (None, 46.666666666666664),
    ],
)
def test_focus_tier(tier, expected):
    assert score_story(rubric(), signals(focus_tier=tier)) == approx(expected)


def test_source_bonus():
    assert score_story(rubric(), signals(source_weights=(1.5,))) == approx(51.666666666666664)
    assert score_story(rubric(), signals(source_weights=(0.5,))) == approx(41.666666666666664)
    both = signals(source_weights=(0.5, 1.5))
    assert score_story(rubric(), both) == approx(55.666666666666664)
    assert score_story(rubric(), signals(source_weights=())) == approx(NEUTRAL)


def test_feedback_boost_clamped():
    assert score_story(rubric(), signals(feedback_boost=3)) == approx(49.666666666666664)
    assert score_story(rubric(), signals(feedback_boost=25)) == approx(56.666666666666664)
    assert score_story(rubric(), signals(feedback_boost=-25)) == approx(36.666666666666664)


def test_clamp_high():
    r = rubric(relevance=3, urgency=3, actionability=3, novelty=3, exploited_in_wild=True)
    assert score_story(r, signals(kev=True, focus_tier="primary")) == 100.0


def test_clamp_low():
    r = rubric(relevance=0, urgency=0, actionability=0, novelty=0)
    s = signals(source_weights=(0.5,), focus_tier="side", feedback_boost=-10)
    assert score_story(r, s) == 0.0


def test_config_values_used():
    cfg = ScoringSettings(kev_bonus=20.0)
    assert score_story(rubric(), signals(kev=True), cfg) == approx(66.66666666666666)
    assert bucket_for(75.0, rubric(), signals(), ScoringSettings(top_threshold=80.0)) == "relevant"


@pytest.mark.parametrize(
    ("cfg", "s", "expected"),
    [
        (ScoringSettings(w_relevance=0.55), signals(), PLUS10),
        (ScoringSettings(w_urgency=0.55), signals(), PLUS10),
        (ScoringSettings(w_actionability=0.50), signals(), PLUS10),
        (ScoringSettings(w_novelty=0.45), signals(), PLUS10),
        (ScoringSettings(source_bonus_factor=20.0), signals(source_weights=(1.5,)), PLUS10),
        (ScoringSettings(cvss9_bonus=10.0), signals(max_cvss=9.5), PLUS10),
        (ScoringSettings(cvss7_bonus=10.0), signals(max_cvss=7.5), PLUS10),
        (ScoringSettings(corroboration_bonus=10.0), signals(source_weights=(1.0, 1.0)), PLUS10),
        (ScoringSettings(corroboration_max=6.0), signals(source_weights=(1.0,) * 4), NEUTRAL + 6),
        (ScoringSettings(primary_bonus=10.0), signals(focus_tier="primary"), PLUS10),
        (ScoringSettings(side_penalty=10.0), signals(focus_tier="side"), 36.666666666666664),
    ],
)
def test_score_config_fields_used(cfg, s, expected):
    assert score_story(rubric(), s, cfg) == approx(expected)


def test_exploited_bonus_config_used():
    cfg = ScoringSettings(exploited_bonus=10.0)
    assert score_story(rubric(exploited_in_wild=True), signals(), cfg) == approx(56.666666666666664)


def test_bucket_and_cap_config_used():
    cfg = ScoringSettings(relevant_threshold=40.0)
    assert bucket_for(45.0, rubric(), signals(), cfg) == "relevant"
    assert bucket_for(20.0, rubric(), signals(), ScoringSettings(side_threshold=15.0)) == "side"
    top = [scored(i, 91 - i, "top") for i in range(1, 6)]
    out = place(top, ScoringSettings(top_cap=2, relevant_cap=1))
    assert ids(out["top"]) == [1, 2]
    assert ids(out["relevant"]) == [3]
    assert ids(out["side"]) == [4, 5]


def test_recency_config_used():
    cfg = ScoringSettings(recency_full_hours=12.0, recency_floor=0.5)
    assert recency_factor(NOW - timedelta(hours=11), NOW, cfg) == approx(1.0)
    assert recency_factor(NOW - timedelta(hours=18), NOW, cfg) == approx(0.75)
    assert recency_factor(NOW - timedelta(hours=30), NOW, cfg) == approx(0.5)


def test_relevance_zero_drops_high_score():
    assert bucket_for(100.0, rubric(relevance=0), signals()) == "drop"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (72.0, "top"),
        (71.99, "relevant"),
        (48.0, "relevant"),
        (47.99, "side"),
        (25.0, "side"),
        (24.99, "drop"),
        (0.0, "drop"),
        (100.0, "top"),
    ],
)
def test_bucket_boundaries(score, expected):
    assert bucket_for(score, rubric(), signals()) == expected


def test_low_weight_single_source_capped_below_top():
    r = rubric(relevance=3, urgency=2)
    s = signals(source_weights=(0.8,))
    assert bucket_for(90.0, r, s) == "relevant"
    assert bucket_for(50.0, r, s) == "relevant"


def test_low_weight_allowed_top():
    assert bucket_for(90.0, rubric(relevance=3, urgency=3), signals(source_weights=(0.8,))) == "top"
    corroborated = signals(source_weights=(0.8, 0.7))
    assert bucket_for(90.0, rubric(relevance=2, urgency=1), corroborated) == "top"
    assert bucket_for(90.0, rubric(relevance=3, urgency=2), signals(source_weights=(1.0,))) == "top"
    assert bucket_for(90.0, rubric(relevance=1, urgency=3), corroborated) == "relevant"


def test_assess_failed_is_side():
    assert bucket_for(None, None, signals()) == "side"


def test_top_overflow_demoted():
    out = place([scored(i, 91 - i, "top") for i in range(1, 11)])
    assert ids(out["top"]) == list(range(1, 9))
    assert all(x.bucket == "top" for x in out["top"])
    assert ids(out["relevant"]) == [9, 10]
    assert all(x.bucket == "relevant" for x in out["relevant"])
    assert out["side"] == []


def test_relevant_overflow_to_side():
    stories = [scored(i, 70 - i * 0.1, "relevant") for i in range(1, 33)]
    stories.append(scored(100, 30.0, "side"))
    out = place(stories)
    assert ids(out["relevant"]) == list(range(1, 31))
    assert ids(out["side"]) == [31, 32, 100]
    assert all(x.bucket == "side" for x in out["side"])


def test_top_overflow_pushes_relevant():
    stories = [scored(i, 91 - i, "top") for i in range(1, 11)]
    stories += [scored(100 + i, 60 - i, "relevant") for i in range(1, 30)]
    out = place(stories)
    assert len(out["top"]) == 8
    assert len(out["relevant"]) == 30
    assert ids(out["relevant"])[:3] == [9, 10, 101]
    assert ids(out["side"]) == [129]
    assert out["side"][0].bucket == "side"


def test_empty_top_stays_empty():
    stories = [
        scored(1, 60.0, "relevant"),
        scored(2, 50.0, "relevant"),
        scored(3, 30.0, "side"),
        scored(4, 10.0, "drop"),
    ]
    out = place(stories)
    assert out["top"] == []
    assert set(out.keys()) == {"top", "relevant", "side", "drop"}
    assert ids(out["relevant"]) == [1, 2]
    assert ids(out["side"]) == [3]
    assert ids(out["drop"]) == [4]


def test_place_order_and_determinism():
    stories = [
        scored(3, 40.0, "side"),
        scored(1, 40.0, "side"),
        scored(2, None, "side"),
        scored(4, 45.0, "side"),
    ]
    before = list(stories)
    out = place(stories)
    assert ids(out["side"]) == [4, 1, 3, 2]
    assert place(list(reversed(stories))) == out
    assert stories == before


@pytest.mark.parametrize(
    ("hours_ago", "expected"),
    [(0, 1.0), (5.99, 1.0), (6, 1.0), (15, 0.9), (24, 0.8), (24.5, 0.8), (48, 0.8), (-1, 1.0)],
)
def test_recency_factor(hours_ago, expected):
    assert recency_factor(NOW - timedelta(hours=hours_ago), NOW) == approx(expected)


def test_gazette_order():
    a = scored(1, 80.0, "top", hours_ago=30)
    b = scored(2, 70.0, "top", hours_ago=1)
    c = scored(3, None, "side")
    assert ids(gazette_order([a, b, c], NOW)) == [2, 1, 3]
    assert ids(place([a, b])["top"]) == [1, 2]

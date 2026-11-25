"""scoring.feedback_boost (M24, plan §8/§16): per source and per focus/tag,
``(up − down) / (n + 5)`` × 10, clamped ±10."""

from __future__ import annotations

import pytest

from sidereal.pipeline.scoring import (
    FEEDBACK_MAX,
    NO_BOOSTS,
    FeedbackBoosts,
    Rubric,
    StorySignals,
    Vote,
    feedback_boost,
    feedback_tables,
    score_story,
    smoothed_boost,
    topic_keys,
)


def votes(vote, n, *, sources=("bc",), focus=None, tags=()):
    return [Vote(vote, sources, focus, tags)] * n


@pytest.mark.parametrize(("up", "down", "expected"), [
    (0, 0, 0.0),
    (1, 0, 10 / 6),          # one vote is damped by the +5
    (0, 1, -10 / 6),
    (3, 1, 10 * 2 / 9),
    (5, 0, 5.0),
    (10, 0, 10 * 10 / 15),
    (2, 2, 0.0),
    (95, 0, 9.5),
])
def test_smoothed_boost(up, down, expected):
    assert smoothed_boost(up, down) == pytest.approx(expected)


def test_smoothed_boost_stays_within_clamp():
    assert smoothed_boost(10_000, 0) < FEEDBACK_MAX
    assert smoothed_boost(0, 10_000) > -FEEDBACK_MAX
    assert FEEDBACK_MAX == 10.0


def test_no_feedback_is_zero():
    assert feedback_boost(NO_BOOSTS, sources=("bc",), focus="ms-security", tags=("x",)) == 0.0
    t = feedback_tables([])
    assert t.sources == {} and t.topics == {}


def test_per_source_tables():
    t = feedback_tables(votes("up", 3, sources=("bc", "krebs")) + votes("down", 1))
    assert t.sources["bc"] == pytest.approx(10 * (3 - 1) / (4 + 5))
    assert t.sources["krebs"] == pytest.approx(10 * 3 / 8)
    assert t.topics == {}


def test_per_focus_and_tag_tables():
    t = feedback_tables(votes("up", 2, focus="entra-identity", tags=("Entra", " mfa "))
                        + votes("down", 1, focus="entra-identity"))
    assert t.topics["focus:entra-identity"] == pytest.approx(10 * 1 / 8)
    assert t.topics["tag:entra"] == pytest.approx(10 * 2 / 7)  # tags lower-cased, stripped
    assert t.topics["tag:mfa"] == pytest.approx(10 * 2 / 7)


def test_focus_none_and_duplicates_are_ignored():
    assert topic_keys("none", ["a", "A", " "]) == ("tag:a",)
    assert topic_keys(None, []) == ()
    t = feedback_tables([Vote("up", ("bc", "bc"), "none", ("a", "a"))])
    assert t.sources["bc"] == pytest.approx(10 / 6)  # one vote, not two
    assert t.topics == {"tag:a": pytest.approx(10 / 6)}


def test_story_boost_source_plus_topic_means():
    b = FeedbackBoosts(sources={"bc": 4.0, "krebs": -2.0},
                       topics={"focus:f": 3.0, "tag:x": 1.0})
    # mean over voted-on sources (1.0) + mean over voted-on topics (2.0); unknown keys ignored
    assert feedback_boost(b, sources=("bc", "krebs", "other"), focus="f",
                          tags=("x", "y")) == pytest.approx(3.0)
    assert feedback_boost(b, sources=("bc",), focus=None) == pytest.approx(4.0)
    assert feedback_boost(b, sources=(), focus="f") == pytest.approx(3.0)
    assert feedback_boost(b, sources=("other",), focus="g", tags=("z",)) == 0.0


@pytest.mark.parametrize(("src", "topic", "expected"), [
    (9.0, 9.0, 10.0), (-9.0, -9.0, -10.0), (6.0, 4.0, 10.0), (6.0, 3.9, 9.9)])
def test_story_boost_clamped(src, topic, expected):
    b = FeedbackBoosts(sources={"s": src}, topics={"tag:t": topic})
    assert feedback_boost(b, sources=("s",), focus=None, tags=("t",)) == pytest.approx(expected)


def test_down_votes_lower_the_score():
    t = feedback_tables(votes("down", 5))
    boost = feedback_boost(t, sources=("bc",), focus=None)
    assert boost == pytest.approx(-5.0)
    r = Rubric(2, 2, 2, 2)
    base = score_story(r, StorySignals())
    assert score_story(r, StorySignals(feedback_boost=boost)) == pytest.approx(base - 5.0)


def test_unknown_vote_kind_ignored():
    assert feedback_tables([Vote("meh", ("bc",))]).sources == {}

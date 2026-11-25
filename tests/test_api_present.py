"""Tests for ``src/sidereal/api/present.py`` and the response models in ``api/schemas.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.api.present import build_sections, placed_counts, story_out
from sidereal.api.schemas import (
    Counts,
    DayCounts,
    DayDetail,
    DayRun,
    DaySummary,
    Gazette,
    Sections,
    Story,
)
from sidereal.config import ScoringSettings
from sidereal.db.views_repo import SourceRef, StoryView, day_views, gazette_views
from sidereal.timeutil import iso_z
from tests.factories import DEMO_NOW, seed_demo

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
CFG = ScoringSettings()


def _view(id, *, bucket="top", score=80.0, first_seen=NOW, **kw):
    fields = dict(
        id=id, title=f"S{id}", day="2026-11-20", first_seen_at=iso_z(first_seen),
        state="assessed", bucket=bucket, score=score, flags={}, cve_ids=[], summary="sum",
        why="why", tags=["t"], focus="ms-security", lead_url=f"https://e.example/{id}",
        published_at=None, excerpt="ex",
        sources=[SourceRef(key="k", name="K", url="https://e.example/k")],
    )
    fields.update(kw)
    return StoryView(**fields)


def _ids(stories):
    return [s.id for s in stories]


def _five():
    return [
        _view(1, bucket="top"),
        _view(2, bucket="relevant", score=60.0),
        _view(3, bucket="side", score=30.0),
        _view(4, bucket="side", score=None, state="assess_failed"),
        _view(5, bucket="drop", score=10.0),
    ]


def test_story_out_fields():
    s = story_out(_view(1, published_at="2026-11-20T11:00:00Z", flags={"kev": True}))
    assert s.model_dump() == {
        "id": 1, "title": "S1", "day": "2026-11-20", "first_seen_at": "2026-11-20T12:00:00Z",
        "published_at": "2026-11-20T11:00:00Z", "bucket": "top", "score": 80.0,
        "summary": "sum", "why": "why", "tags": ["t"], "focus": "ms-security",
        "flags": {"kev": True},
        "sources": [{"key": "k", "name": "K", "url": "https://e.example/k"}],
        "lead_url": "https://e.example/1", "excerpt": "ex", "read": False,
        "vote": None, "hidden": False,
    }


def test_story_out_bucket_override():
    # The placed bucket wins when given.
    assert story_out(_view(1), bucket="relevant").bucket == "relevant"
    assert story_out(_view(1)).bucket == "top"


def test_story_out_null_source_url():
    # The repo already nulled non-http links; they stay null.
    s = story_out(_view(1, sources=[SourceRef(key="a", name="A", url=None)], lead_url=None))
    assert s.sources[0].url is None
    assert s.lead_url is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "ftp://e.example/x",
                                 "JaVaScRiPt:alert(1)", " javascript:alert(1)", ""])
def test_story_out_non_http_links_become_none(url):
    # Rule 2 is checked again at the API edge, whatever the view holds.
    s = story_out(_view(1, lead_url=url, sources=[SourceRef(key="a", name="A", url=url)]))
    assert s.lead_url is None
    assert s.sources[0].url is None


def test_story_out_http_links_kept():
    s = story_out(_view(1, lead_url="http://e.example/x",
                        sources=[SourceRef(key="a", name="A", url="HTTPS://e.example/y")]))
    assert s.lead_url == "http://e.example/x"
    assert s.sources[0].url == "HTTPS://e.example/y"


def test_story_out_copies_lists():
    v = _view(1, tags=["a"], flags={"kev": True})
    s = story_out(v)
    s.tags.append("b")
    s.flags["x"] = 1
    assert v.tags == ["a"]
    assert v.flags == {"kev": True}


def test_story_out_assess_failed_has_no_score():
    s = story_out(_view(1, state="assess_failed", bucket="top", score=55.0))
    assert s.score is None
    assert s.bucket == "side"


def test_model_fields():
    # Plan §10.1 Story schema; no state, no article text.
    assert set(Story.model_fields) == {
        "id", "title", "day", "first_seen_at", "published_at", "bucket", "score", "summary",
        "why", "tags", "focus", "flags", "sources", "lead_url", "excerpt", "read",
        "vote", "hidden"}
    assert set(Sections.model_fields) == {"top", "relevant", "side", "drop"}
    assert set(Gazette.model_fields) == {"generated_at", "window_start", "sections", "counts"}
    assert set(DaySummary.model_fields) == {"day", "label", "counts", "run_count", "headline"}
    assert set(DayRun.model_fields) == {"id", "started_at", "finished_at", "trigger", "status"}
    assert set(DayDetail.model_fields) == {
        "day", "label", "overview", "headline", "runs", "sections", "counts"}
    assert set(Counts.model_fields) == {"top", "relevant", "side", "drop"}
    assert set(DayCounts.model_fields) == {"top", "relevant", "side"}


def test_sections_grouping():
    # A None score sorts last in its bucket; drop is hidden but counted.
    sections, counts = build_sections(_five(), CFG, now=None, include_drop=False)
    assert (_ids(sections.top), _ids(sections.relevant), _ids(sections.side),
            _ids(sections.drop)) == ([1], [2], [3, 4], [])
    assert counts == Counts(top=1, relevant=1, side=2, drop=1)


def test_drop_key_always_serialised():
    sections, counts = build_sections(_five(), CFG, now=NOW, include_drop=False)
    assert sections.model_dump()["drop"] == []
    assert counts.model_dump() == {"top": 1, "relevant": 1, "side": 2, "drop": 1}


def test_include_drop():
    sections, _ = build_sections(_five(), CFG, now=None, include_drop=True)
    assert _ids(sections.drop) == [5]
    assert sections.drop[0].bucket == "drop"


def test_assess_failed_goes_to_side_without_score():
    # Even with a stored bucket and score, a failed assessment is shown in side, last, unscored.
    views = [_view(1, bucket="top", score=99.0, state="assess_failed"),
             _view(2, bucket="side", score=20.0)]
    sections, counts = build_sections(views, CFG, now=NOW, include_drop=False)
    assert _ids(sections.top) == []
    assert _ids(sections.side) == [2, 1]
    assert sections.side[1].score is None
    assert sections.side[1].bucket == "side"
    assert counts == Counts(top=0, relevant=0, side=2, drop=0)


def test_daily_order_is_score_only():
    # now=None means Daily order, score desc, age ignored.
    views = [_view(1, score=70.0, first_seen=NOW - timedelta(hours=1)),
             _view(2, score=80.0, first_seen=NOW - timedelta(hours=20))]
    assert _ids(build_sections(views, CFG, now=None, include_drop=False)[0].top) == [2, 1]


def test_gazette_order_uses_recency():
    # 80 × recency(20 h) = 80 × (1 − 0.2 × 14/18) ≈ 67.6, below 70 × 1.0.
    views = [_view(1, score=80.0, first_seen=NOW - timedelta(hours=20)),
             _view(2, score=70.0, first_seen=NOW - timedelta(hours=1))]
    assert _ids(build_sections(views, CFG, now=NOW, include_drop=False)[0].top) == [2, 1]
    assert _ids(build_sections(views, CFG, now=None, include_drop=False)[0].top) == [1, 2]


@pytest.mark.parametrize("bucket", ["relevant", "side", "drop"])
def test_gazette_order_in_every_section(bucket):
    views = [_view(1, bucket=bucket, score=40.0, first_seen=NOW - timedelta(hours=20)),
             _view(2, bucket=bucket, score=35.0, first_seen=NOW - timedelta(hours=1))]
    sections, _ = build_sections(views, CFG, now=NOW, include_drop=True)
    assert _ids(getattr(sections, bucket)) == [2, 1]


def test_caps_move_overflow_down():
    # Story 2 overflows top into the relevant pool and outscores 3 (80 > 60), so 3 overflows
    # into side; the Story shows the placed bucket.
    cfg = ScoringSettings(top_cap=1, relevant_cap=1)
    views = [_view(1, score=90.0), _view(2, score=80.0), _view(3, bucket="relevant", score=60.0)]
    sections, counts = build_sections(views, cfg, now=None, include_drop=False)
    assert _ids(sections.top) == [1]
    assert _ids(sections.relevant) == [2]
    assert sections.relevant[0].bucket == "relevant"
    assert _ids(sections.side) == [3]
    assert sections.side[0].bucket == "side"
    assert counts == Counts(top=1, relevant=1, side=1, drop=0)


def test_caps_apply_before_gazette_order():
    # The cap keeps the highest score (90, old), then recency orders what is shown.
    cfg = ScoringSettings(top_cap=1)
    views = [_view(1, score=90.0, first_seen=NOW - timedelta(hours=20)),
             _view(2, score=80.0, first_seen=NOW - timedelta(hours=1))]
    sections, counts = build_sections(views, cfg, now=NOW, include_drop=False)
    assert _ids(sections.top) == [1]
    assert _ids(sections.relevant) == [2]
    assert counts == Counts(top=1, relevant=1, side=0, drop=0)


def test_empty():
    sections, counts = build_sections([], CFG, now=NOW, include_drop=True)
    assert sections == Sections(top=[], relevant=[], side=[], drop=[])
    assert counts == Counts(top=0, relevant=0, side=0, drop=0)


def test_placed_counts_examples():
    assert placed_counts(0, 0, 0, CFG) == DayCounts(top=0, relevant=0, side=0)
    # 2 top overflow into relevant, 27 <= 30.
    assert placed_counts(10, 25, 4, CFG) == DayCounts(top=8, relevant=27, side=4)
    # Pool 5 + 1 = 6, 3 shown, 3 overflow to side.
    assert placed_counts(2, 5, 0, ScoringSettings(top_cap=1, relevant_cap=3)) == DayCounts(
        top=1, relevant=3, side=3)


@pytest.mark.parametrize(("top", "relevant", "side", "top_cap", "relevant_cap"), [
    (0, 0, 0, 8, 30), (3, 2, 1, 8, 30), (10, 0, 0, 8, 30), (10, 25, 4, 8, 30),
    (2, 5, 0, 1, 3), (0, 5, 1, 1, 3), (4, 0, 2, 1, 1)])
def test_placed_counts_matches_place(top, relevant, side, top_cap, relevant_cap):
    # The day list's counts must equal what the day's own page shows.
    cfg = ScoringSettings(top_cap=top_cap, relevant_cap=relevant_cap)
    views = []
    i = 0
    for bucket, n, base in (("top", top, 90.0), ("relevant", relevant, 60.0),
                            ("side", side, 30.0)):
        for _ in range(n):
            i += 1
            views.append(_view(i, bucket=bucket, score=base - i))
    _, counts = build_sections(views, cfg, now=None, include_drop=False)
    assert placed_counts(top, relevant, side, cfg) == DayCounts(
        top=counts.top, relevant=counts.relevant, side=counts.side)


def test_demo_db_round_trip(db):
    # Views from the demo DB present cleanly: every visible story lands in exactly one section.
    seed_demo(db)
    views = gazette_views(db, since=DEMO_NOW - timedelta(days=3))
    sections, counts = build_sections(views, CFG, now=DEMO_NOW, include_drop=True)
    shown = sections.top + sections.relevant + sections.side + sections.drop
    assert sorted(_ids(shown)) == sorted(v.id for v in views)
    assert (counts.top, counts.relevant, counts.side, counts.drop) == (
        len(sections.top), len(sections.relevant), len(sections.side), len(sections.drop))
    failed = {v.id for v in views if v.state == "assess_failed"}
    assert failed
    assert all(s.score is None for s in sections.side if s.id in failed)
    assert failed <= set(_ids(sections.side))
    day = day_views(db, views[0].day)
    assert build_sections(day, CFG, now=None, include_drop=False)[1].top == sum(
        v.bucket == "top" for v in day)

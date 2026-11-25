"""Tests for ``src/sidereal/db/views_repo.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db.assessments_repo import save_assessment
from sidereal.db.digests_repo import save_day_digest
from sidereal.db.items_repo import insert_item, set_content
from sidereal.db.runs_repo import start_run
from sidereal.db.seed import seed_sources
from sidereal.db.sources_repo import get_by_key
from sidereal.db.stories_repo import attach_item, create_story, set_score, set_state
from sidereal.db.views_repo import (
    DaySummaryRow,
    SourceRef,
    StoryView,
    day_summaries,
    day_views,
    gazette_views,
    runs_between,
)
from sidereal.defaults import SourceSeed
from tests import factories

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
SEC = timedelta(seconds=1)


def _source(db, key="src", name=None):
    seed_sources(db, [SourceSeed(key=key, name=name or key.upper(), kind="rss",
                                 url=f"https://{key}.example/feed")])
    return get_by_key(db, key).id


def _run(db, at=T0):
    return start_run(db, trigger="timer", at=at)


def _story(db, run_id, *, title="T", first_seen=T0, day="2026-11-20", state="assessed",
           bucket="top", score=80.0, flags=None, cve_ids=()):
    sid = create_story(db, title=title, day=day, first_seen_at=first_seen, first_run_id=run_id,
                       cve_ids=cve_ids, flags=flags)
    set_state(db, sid, state)
    if bucket is not None:
        set_score(db, sid, score=score, bucket=bucket)
    return sid


def _item(db, story_id, run_id, source_id, *, n, url=None, published=None, excerpt="",
          attach=True):
    iid = insert_item(db, source_id=source_id, story_id=story_id, guid=f"g{n}",
                      url=url or f"https://example.com/{n}",
                      canonical_url=f"https://example.com/c{n}", title=f"t{n}",
                      title_norm=f"t{n}", author=None, published_at=published,
                      first_seen_at=T0, run_id=run_id, excerpt=excerpt)
    if attach:
        attach_item(db, story_id, item_id=iid, seen_at=T0)
    return iid


def _assess(db, story_id, *, summary="S", why="W", tags=("a",), raw=None):
    save_assessment(db, story_id, model="m", prompt_version="assess.v1", relevance=2,
                    urgency=2, actionability=2, novelty=2, tags=tags, summary=summary,
                    why=why, raw={"focus": "ms-security"} if raw is None else raw,
                    duration_ms=1, at=T0)


# 1. test_gazette_full_view
def test_gazette_full_view(db):
    src = _source(db, "msrc", "MSRC")
    run = _run(db)
    sid = _story(db, run, title="Patch", flags={"kev": True}, cve_ids=["CVE-2026-1"])
    iid = _item(db, sid, run, src, n=1, url="https://msrc.example/a",
                published=T0 - HOUR, excerpt="ex")
    _assess(db, sid)
    set_content(db, iid, text="SECRET BODY", status="ok")
    views = gazette_views(db, since=T0 - HOUR)
    assert views == [StoryView(
        id=sid, title="Patch", day="2026-11-20",
        first_seen_at="2026-11-20T12:00:00Z", state="assessed", bucket="top",
        score=80.0, flags={"kev": True}, cve_ids=["CVE-2026-1"],
        summary="S", why="W", tags=["a"], focus="ms-security",
        lead_url="https://msrc.example/a",
        published_at="2026-11-20T11:00:00Z", excerpt="ex",
        sources=[SourceRef(key="msrc", name="MSRC", url="https://msrc.example/a")],
    )]
    assert "SECRET BODY" not in repr(views)


# 2. test_gazette_window_is_inclusive
def test_gazette_window_is_inclusive(db):
    run = _run(db)
    a = _story(db, run, first_seen=T0 - 24 * HOUR)
    _story(db, run, first_seen=T0 - 24 * HOUR - SEC)
    assert [v.id for v in gazette_views(db, since=T0 - 24 * HOUR)] == [a]


# 3. test_gazette_window_ignores_day
def test_gazette_window_ignores_day(db):
    run = _run(db)
    a = _story(db, run, day="2026-11-19", first_seen=T0 - HOUR)
    _story(db, run, day="2026-11-20", first_seen=T0 - 25 * HOUR)
    assert [v.id for v in gazette_views(db, since=T0 - 24 * HOUR)] == [a]


# 4. test_hidden_states_excluded
def test_hidden_states_excluded(db):
    run = _run(db)
    _story(db, run, state="new", bucket=None)
    _story(db, run, state="filtered", bucket=None)
    _story(db, run, state="triaged_out", bucket=None)
    failed = _story(db, run, state="assess_failed", bucket=None)
    dropped = _story(db, run, bucket="drop", score=10.0)
    assert [(v.id, v.state, v.bucket, v.score) for v in
            gazette_views(db, since=T0 - HOUR)] == [
        (failed, "assess_failed", "side", None),
        (dropped, "assessed", "drop", 10.0),
    ]


# 5. test_assess_failed_with_side_bucket
def test_assess_failed_with_side_bucket(db):
    run = _run(db)
    sid = _story(db, run, state="assess_failed", bucket="side", score=None)
    assert [(v.id, v.bucket, v.score) for v in
            gazette_views(db, since=T0 - HOUR)] == [(sid, "side", None)]


# 6. test_no_assessment
def test_no_assessment(db):
    run = _run(db)
    _story(db, run)
    v = gazette_views(db, since=T0 - HOUR)[0]
    assert (v.summary, v.why, v.tags, v.focus) == (None, None, [], None)


# 7. test_focus_only_from_string
@pytest.mark.parametrize("raw", [{}, {"focus": 3}, {"focus": None}])
def test_focus_only_from_string(db, raw):
    run = _run(db)
    sid = _story(db, run)
    _assess(db, sid, raw=raw)
    assert gazette_views(db, since=T0 - HOUR)[0].focus is None


# 8. test_lead_item_not_first_item
def test_lead_item_not_first_item(db):
    src = _source(db)
    run = _run(db)
    sid = _story(db, run)
    i1 = _item(db, sid, run, src, n=1, excerpt="e1", attach=False)
    _item(db, sid, run, src, n=2, excerpt="e2", published=T0 - 2 * HOUR)
    attach_item(db, sid, item_id=i1, seen_at=T0)
    v = gazette_views(db, since=T0 - HOUR)[0]
    assert (v.lead_url, v.excerpt, v.published_at) == (
        "https://example.com/2", "e2", "2026-11-20T10:00:00Z",
    )


# 9. test_story_without_items
def test_story_without_items(db):
    run = _run(db)
    _story(db, run)
    v = gazette_views(db, since=T0 - HOUR)[0]
    assert (v.lead_url, v.published_at, v.excerpt, v.sources) == (None, None, "", [])


# 10. test_sources_distinct_in_item_order
def test_sources_distinct_in_item_order(db):
    a = _source(db, "a", "A")
    b = _source(db, "b", "B")
    run = _run(db)
    sid = _story(db, run)
    _item(db, sid, run, b, n=1)
    _item(db, sid, run, a, n=2)
    _item(db, sid, run, b, n=3)
    assert gazette_views(db, since=T0 - HOUR)[0].sources == [
        SourceRef(key="b", name="B", url="https://example.com/1"),
        SourceRef(key="a", name="A", url="https://example.com/2"),
    ]


# 11. test_non_http_url_becomes_none
@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "ftp://x.example/a", "data:text/html,x",
])
def test_non_http_url_becomes_none(db, url):
    src = _source(db)
    run = _run(db)
    sid = _story(db, run)
    _item(db, sid, run, src, n=1, url=url)
    v = gazette_views(db, since=T0 - HOUR)[0]
    assert v.lead_url is None
    assert v.sources[0].url is None


# 12. test_gazette_ordered_by_id
def test_gazette_ordered_by_id(db):
    run = _run(db)
    a = _story(db, run, first_seen=T0)
    b = _story(db, run, first_seen=T0 - 2 * HOUR)
    assert [v.id for v in gazette_views(db, since=T0 - 3 * HOUR)] == [a, b]


# 13. test_day_views_by_day_column
def test_day_views_by_day_column(db):
    run = _run(db)
    a = _story(db, run, day="2026-11-20", first_seen=T0 - 30 * HOUR)
    _story(db, run, day="2026-11-19", first_seen=T0)
    _story(db, run, day="2026-11-20", state="filtered", bucket=None)
    assert [v.id for v in day_views(db, "2026-11-20")] == [a]


# 14. test_day_views_bad_day
def test_day_views_bad_day(db):
    with pytest.raises(ValueError, match="day must be YYYY-MM-DD"):
        day_views(db, "2026-11-2")


# 15. test_day_summaries_counts_and_headline
def test_day_summaries_counts_and_headline(db):
    run = _run(db)
    _story(db, run, bucket="top")
    _story(db, run, bucket="top")
    _story(db, run, bucket="relevant", score=60.0)
    _story(db, run, bucket="side", score=30.0)
    _story(db, run, state="assess_failed", bucket=None)
    _story(db, run, bucket="drop", score=10.0)
    _story(db, run, state="filtered", bucket=None)
    _story(db, run, day="2026-11-19", bucket="relevant", score=60.0)
    save_day_digest(db, "2026-11-20", overview="O", headline="H",
                    story_ids=[], model="m", run_id=run, at=T0)
    assert day_summaries(db) == [
        DaySummaryRow(day="2026-11-20", top=2, relevant=1, side=2,
                      drop=1, headline="H"),
        DaySummaryRow(day="2026-11-19", top=0, relevant=1, side=0,
                      drop=0, headline=None),
    ]


# 16. test_day_summaries_digest_only_and_filtered_only_days
def test_day_summaries_digest_only_and_filtered_only_days(db):
    run = _run(db)
    _story(db, run, day="2026-11-17", state="filtered", bucket=None)
    save_day_digest(db, "2026-11-18", overview="O", headline="D",
                    story_ids=[], model="m", run_id=run, at=T0)
    assert day_summaries(db) == [
        DaySummaryRow(day="2026-11-18", top=0, relevant=0, side=0,
                      drop=0, headline="D"),
        DaySummaryRow(day="2026-11-17", top=0, relevant=0, side=0,
                      drop=0, headline=None),
    ]


# 17. test_day_summaries_limit_and_before
def test_day_summaries_limit_and_before(db):
    run = _run(db)
    for d in ("2026-11-18", "2026-11-19", "2026-11-20"):
        _story(db, run, day=d, bucket="relevant", score=60.0)
    save_day_digest(db, "2026-11-21", overview="O", headline="X",
                    story_ids=[], model="m", run_id=run, at=T0)
    assert [r.day for r in day_summaries(db, limit=2)] == [
        "2026-11-21", "2026-11-20",
    ]
    assert [r.day for r in day_summaries(db, before="2026-11-21")] == [
        "2026-11-20", "2026-11-19", "2026-11-18",
    ]
    assert [r.day for r in day_summaries(db, before="2026-11-20", limit=1)] == [
        "2026-11-19",
    ]
    assert day_summaries(db, before="2026-11-18") == []


# 18. test_day_summaries_empty
def test_day_summaries_empty(db):
    assert day_summaries(db) == []


# 19. test_day_summaries_bad_args
def test_day_summaries_bad_args(db):
    with pytest.raises(ValueError, match="limit must be >= 1"):
        day_summaries(db, limit=0)
    with pytest.raises(ValueError, match="day must be YYYY-MM-DD"):
        day_summaries(db, before="2026-11")


# 20. test_runs_between_half_open
def test_runs_between_half_open(db):
    r0 = _run(db, T0 - HOUR)
    r1 = _run(db, T0)
    r2 = _run(db, T0 + HOUR)
    _run(db, T0 + 2 * HOUR)
    rows = runs_between(db, start=T0, end=T0 + 2 * HOUR)
    assert [r.id for r in rows] == [r1, r2]
    assert rows[0].status == "running"
    assert rows[0].stats == {}
    assert rows[0].started_at == "2026-11-20T12:00:00Z"
    assert r0 not in [r.id for r in rows]


# 21. test_runs_between_ordered_by_start
def test_runs_between_ordered_by_start(db):
    late = _run(db, T0 + HOUR)
    early = _run(db, T0)
    assert [r.id for r in runs_between(db, start=T0, end=T0 + 3 * HOUR)] == [early, late]


# 22. test_reads_do_not_open_transactions
def test_reads_do_not_open_transactions(db):
    run = _run(db)
    _story(db, run)
    gazette_views(db, since=T0 - HOUR)
    day_views(db, "2026-11-20")
    day_summaries(db)
    runs_between(db, start=T0, end=T0 + HOUR)
    assert db.in_transaction is False


# Review additions (r68): per-story grouping and the factories' demo data.
def test_each_story_uses_its_own_rows(db):
    a_src = _source(db, "a", "A")
    b_src = _source(db, "b", "B")
    run = _run(db)
    s1 = _story(db, run, title="One", bucket="top", score=90.0, flags={"kev": True},
                cve_ids=["CVE-2026-1"])
    _item(db, s1, run, a_src, n=1, url="https://one.example/1", excerpt="e1",
          published=T0 - HOUR)
    _assess(db, s1, summary="S1", why="W1", tags=("t1",), raw={"focus": "f1"})
    s2 = _story(db, run, title="Two", bucket="relevant", score=55.0)
    _item(db, s2, run, b_src, n=2, url="javascript:x", excerpt="e2")
    _item(db, s2, run, a_src, n=3, url="https://two.example/3")
    v1, v2 = gazette_views(db, since=T0 - HOUR)
    assert v1 == StoryView(
        id=s1, title="One", day="2026-11-20", first_seen_at="2026-11-20T12:00:00Z",
        state="assessed", bucket="top", score=90.0, flags={"kev": True},
        cve_ids=["CVE-2026-1"], summary="S1", why="W1", tags=["t1"], focus="f1",
        lead_url="https://one.example/1", published_at="2026-11-20T11:00:00Z", excerpt="e1",
        sources=[SourceRef(key="a", name="A", url="https://one.example/1")],
    )
    assert v2 == StoryView(
        id=s2, title="Two", day="2026-11-20", first_seen_at="2026-11-20T12:00:00Z",
        state="assessed", bucket="relevant", score=55.0, flags={}, cve_ids=[],
        summary=None, why=None, tags=[], focus=None, lead_url=None, published_at=None,
        excerpt="e2",
        sources=[SourceRef(key="b", name="B", url=None),
                 SourceRef(key="a", name="A", url="https://two.example/3")],
    )
    assert day_views(db, "2026-11-20") == [v1, v2]


def test_demo_data_round_trip(db):
    counts = factories.seed_demo(db)
    rows = day_summaries(db)
    assert [r.day for r in rows] == ["2026-07-14", "2026-07-13", "2026-07-12"]
    assert [r.headline is not None for r in rows] == [False, True, True]
    views = [v for r in rows for v in day_views(db, r.day)]
    assert len(views) == counts["stories"] == sum(
        r.top + r.relevant + r.side + r.drop for r in rows)
    focus_of = {t["title"]: t["focus"] for t in factories.DEMO_TEMPLATES}
    for v in views:
        expected = focus_of[v.title.rsplit(" #", 1)[0]] if v.state == "assessed" else None
        assert v.focus == expected
        assert v.lead_url is not None and v.lead_url.startswith("https://")
        assert v.day == v.first_seen_at[:10]  # London is UTC+1 in July, runs from 01:00 local
    assert sum(r.drop for r in rows) == sum(v.bucket == "drop" for v in views) > 0
    assert sum(r.side for r in rows) == sum(v.bucket == "side" for v in views)
    assert any(v.state == "assess_failed" for v in views)
    start = datetime(2026, 7, 11, 23, 0, tzinfo=UTC)  # 2026-07-12 00:00 BST
    assert len(runs_between(db, start=start, end=factories.DEMO_NOW)) == counts["runs"]


def test_article_text_never_selected(db):
    src = _source(db)
    run = _run(db)
    sid = _story(db, run)
    iid = _item(db, sid, run, src, n=1)
    set_content(db, iid, text="SECRET BODY", status="ok")
    seen: list[str] = []
    db.set_trace_callback(seen.append)
    try:
        gazette_views(db, since=T0 - HOUR)
        day_views(db, "2026-11-20")
        day_summaries(db)
        runs_between(db, start=T0, end=T0 + HOUR)
    finally:
        db.set_trace_callback(None)
    assert len(seen) == 4
    assert not any("content" in sql or "i.*" in sql for sql in seen)

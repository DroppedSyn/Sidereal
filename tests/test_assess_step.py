"""pipeline/assess_step.py (M13b): prefilter → triage → enrich → assess → placement."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from sidereal.db import assessments_repo, items_repo, stories_repo
from sidereal.pipeline import assess_step, enrich
from sidereal.pipeline.common import Deadline
from tests.pipeline_helpers import (
    NOW,
    FakeClock,
    FeedServer,
    assess_reply,
    chats,
    ollama_for,
    seeded_db,
    smart_ollama,
    start,
    state_of,
)
from tests.pipeline_helpers import add_story as _add

PAGES = Path(__file__).parent / "fixtures" / "pages"
PLAIN = "Local bakery wins regional bread award again"  # no focus keyword: goes to triage


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def add(conn, **kw):
    return _add(conn, start(conn), **kw)


def with_budget(settings, **kw):
    return settings.model_copy(update={"budget": settings.budget.model_copy(update=kw)})


async def run(conn, settings, fake=None, server=None, deadline=None, **kw):
    fake = fake or smart_ollama()
    server = server or FeedServer(conn)
    res = await assess_step.run_assess(conn, ollama_for(fake, settings), server.fetcher(),
                                       settings, now=NOW, deadline=deadline or Deadline(None),
                                       **kw)
    return res, fake, server


async def test_prefilter_filters_always_keeps_and_triages(settings, conn):
    old = add(conn, title=PLAIN + " old", published=NOW - timedelta(hours=200))
    trusted = add(conn, source="tc-entra", title=PLAIN + " trusted")
    plain = add(conn, title=PLAIN)
    res, fake, _ = await run(conn, settings)
    old_row = stories_repo.get_story(conn, old)
    assert (old_row.state, old_row.filter_reason) == ("filtered", "too_old")
    assert res.stats["prefilter"] == {"kept": 2, "filtered": 1, "always": 1, "deferred": 0}
    [tri] = chats(fake, "triage")
    assert f"[{plain}]" in tri["messages"][1]["content"]
    assert f"[{trusted}]" not in tri["messages"][1]["content"]
    assert state_of(conn, trusted) == state_of(conn, plain) == "assessed"
    assert stories_repo.get_story(conn, trusted).triage_relevance is None


async def test_triage_drop_is_stored(settings, conn):
    keep = add(conn, title=PLAIN)
    drop = add(conn, title=PLAIN + " two")
    fake = smart_ollama(triage_relevance=lambda i: 3 if i == keep else 1)
    res, _, _ = await run(conn, settings, fake=fake)
    d = stories_repo.get_story(conn, drop)
    assert (d.state, d.filter_reason, d.triage_relevance) == ("triaged_out", "triage", 1)
    k = stories_repo.get_story(conn, keep)
    assert (k.state, k.triage_relevance) == ("assessed", 3)
    assert res.stats["triage"]["kept"] == 1 and res.stats["triage"]["dropped"] == 1
    assert len(chats(fake, "assess")) == 1


async def test_triage_slice_leaves_the_rest_new(settings, conn):
    a = add(conn, title=PLAIN, published=NOW - timedelta(hours=60))  # oldest band first
    b = add(conn, title=PLAIN + " two", published=NOW - timedelta(hours=1))
    res, fake, _ = await run(conn, with_budget(settings, max_triage_per_run=1))
    assert res.stats["prefilter"]["deferred"] == 1
    assert state_of(conn, a) == "assessed"
    row = stories_repo.get_story(conn, b)
    assert row.state == "new" and row.triage_relevance is None


async def test_pretriaged_story_skips_triage(settings, conn):
    sid = add(conn, title=PLAIN)
    stories_repo.set_triage(conn, sid, 2)
    _, fake, _ = await run(conn, settings)
    assert chats(fake, "triage") == [] and state_of(conn, sid) == "assessed"


async def test_assess_cap_defers_in_queue_order(settings, conn):
    first = add(conn, source="tc-entra", title="One", published=NOW - timedelta(hours=50))
    second = add(conn, source="tc-entra", title="Two", published=NOW - timedelta(hours=1))
    third = add(conn, title=PLAIN)
    res, fake, _ = await run(conn, settings, max_assess=1)
    assert state_of(conn, first) == "assessed"
    assert state_of(conn, second) == state_of(conn, third) == "new"
    assert stories_repo.get_story(conn, third).triage_relevance == 2  # not triaged again later
    assert res.stats["assess"]["deferred"] == 2 and res.stats["assess"]["ok"] == 1
    res2, _, _ = await run(conn, with_budget(settings, max_assess_per_run=1))
    assert state_of(conn, second) == "assessed" and res2.stats["assess"]["deferred"] == 1


async def test_invalid_assess_reply_marks_assess_failed(settings, conn):
    sid = add(conn, source="tc-entra")
    res, _, _ = await run(conn, settings, fake=smart_ollama(assess=lambda t: "not json"))
    row = stories_repo.get_story(conn, sid)
    assert (row.state, row.bucket, row.score) == ("assess_failed", "side", None)
    assert res.stats["assess"]["failed"] == 1 and res.stats["buckets"]["side"] == 1
    assert assessments_repo.get_assessment(conn, sid) is None and res.llm_error is None


async def test_ollama_down_in_triage_keeps_everything_new(settings, conn):
    trusted = add(conn, source="tc-entra")
    plain = add(conn, title=PLAIN)
    fake = smart_ollama()
    fake.errors["/api/chat"] = httpx.ConnectError("refused")
    res, _, _ = await run(conn, settings, fake=fake)
    assert res.llm_error.startswith("LLMUnavailable")
    assert state_of(conn, trusted) == state_of(conn, plain) == "new"
    assert stories_repo.get_story(conn, plain).triage_relevance is None
    assert res.stats["assess"]["deferred"] == 1 and res.days == set()


async def test_ollama_down_mid_assess_keeps_the_rest_new(settings, conn):
    a = add(conn, source="tc-entra", title="One", published=NOW - timedelta(hours=50))
    b = add(conn, source="tc-entra", title="Two", published=NOW - timedelta(hours=1))
    replies = [assess_reply(), httpx.Response(503, json={"error": "loading"})]
    fake = smart_ollama(assess=lambda t: replies.pop(0))
    res, _, _ = await run(conn, settings, fake=fake)
    assert state_of(conn, a) == "assessed" and state_of(conn, b) == "new"
    assert res.llm_error is not None and res.stats["assess"]["deferred"] == 1


async def test_raw_keeps_reply_with_normalised_focus(settings, conn):
    sid = add(conn, source="tc-entra")
    fake = smart_ollama(assess=lambda t: assess_reply(focus="bogus", exploited_in_wild=True,
                                                      bucket="top"))
    await run(conn, settings, fake=fake)
    a = assessments_repo.get_assessment(conn, sid)
    assert a.raw["focus"] == "none" and a.raw["bucket"] == "top" and a.raw["relevance"] == 3
    assert stories_repo.get_story(conn, sid).flags["exploited"] is True


async def test_deadline_stops_before_the_next_assessment(settings, conn):
    ids = [add(conn, source="tc-entra", title=f"Story {i}",
               published=NOW - timedelta(hours=60 - i)) for i in range(3)]
    clock = FakeClock()
    deadline = Deadline(30, clock=clock)

    def slow(title):
        clock.t += 20
        return assess_reply()

    res, _, _ = await run(conn, settings, fake=smart_ollama(assess=slow), deadline=deadline)
    assert [state_of(conn, i) for i in ids] == ["assessed", "assessed", "new"]
    assert deadline.hit and res.stats["assess"]["deferred"] == 1


async def test_enrichment_feeds_article_text_to_assess(settings, conn):
    url = "https://techcommunity.microsoft.com/t5/azure-networking-blog/route-maps/ba-p/1"
    sid = add(conn, source="tc-azure-networking", url=url)
    other = add(conn, source="cisa-kev", title="KEV: Acme thing: bug")  # empty allowlist
    server = FeedServer(conn)
    page = (PAGES / "tc-azure-networking-route-maps.html").read_bytes()
    server.pages[url] = httpx.Response(200, content=page,
                                       headers={"content-type": "text/html; charset=utf-8"})
    res, fake, _ = await run(conn, settings, server=server)
    lead = items_repo.items_for_story(conn, sid)[0]
    assert lead.content_status == "ok" and len(lead.content_text) > 1000
    kev_item = items_repo.items_for_story(conn, other)[0]
    assert kev_item.content_status == "skipped" and kev_item.content_text is None
    prompts = {b["messages"][1]["content"].split("\n")[1]: b["messages"][1]["content"]
               for b in chats(fake, "assess")}
    assert any("Article text:" in p for p in prompts.values())
    assert res.stats["enrich"]["ok"] == 1 and res.stats["enrich"]["skipped"] >= 1
    assert server.requests == [url]  # no request for the empty allowlist


async def test_enrichment_not_retried_once_tried(settings, conn):
    sid = add(conn, source="tc-entra")
    lead = items_repo.items_for_story(conn, sid)[0]
    items_repo.set_content(conn, lead.id, text=None, status="failed")
    _, _, server = await run(conn, settings)
    assert server.requests == []


async def test_enrichment_crash_does_not_stop_assessment(settings, conn, monkeypatch):
    sid = add(conn, source="tc-entra")

    async def boom(*a, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(enrich, "enrich_many", boom)
    res, _, _ = await run(conn, settings)
    assert state_of(conn, sid) == "assessed"
    assert items_repo.items_for_story(conn, sid)[0].content_status is None


async def test_enrichment_deadline_skip_is_not_stored(settings, conn):
    sid = add(conn, source="tc-entra")
    deadline = Deadline(0)
    res, _, _ = await run(conn, settings, deadline=deadline)
    assert items_repo.items_for_story(conn, sid)[0].content_status is None
    assert state_of(conn, sid) == "new"  # the assess loop sees the deadline too


async def test_deadline_stops_triage_between_batches(settings, conn):
    ids = [add(conn, title=f"{PLAIN} {w}", published=NOW - timedelta(hours=60 - i))
           for i, w in enumerate(("alpha", "beta", "gamma"))]
    clock = FakeClock()
    deadline = Deadline(30, clock=clock)
    fake = smart_ollama()
    real = fake.rules[0]

    def slow_triage(body):
        clock.t += 20
        return real[1](body)

    fake.rules[0] = (real[0], slow_triage)
    res, _, _ = await run(conn, with_budget(settings, triage_batch_size=1), fake=fake,
                          deadline=deadline)
    assert res.stats["triage"]["calls"] == 2 and res.stats["triage"]["unfinished"] == 1
    last = stories_repo.get_story(conn, ids[2])
    assert last.state == "new" and last.triage_relevance is None
    assert deadline.hit

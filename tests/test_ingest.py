"""pipeline/ingest.py (M13b): fetch isolation, source health, normalisation, story storage."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sidereal.db import items_repo, runs_repo, sources_repo, stories_repo
from sidereal.pipeline import ingest
from sidereal.pipeline.dedupe import Assignment, rollup_title
from sidereal.sources.base import FetchResult, RawItem
from tests.adapter_helpers import feed_bytes
from tests.pipeline_helpers import NOW, FeedServer, count, seeded_db, start


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def src(conn, key):
    row = sources_repo.get_by_key(conn, key)
    assert row is not None
    return row


def raw(key="bleepingcomputer", url="https://news.example/a", title="Title one two three",
        guid=None, published=NOW - timedelta(hours=1), extra=None, excerpt="<p>Hello</p>"):
    return RawItem(source_key=key, guid=guid or url, url=url, title=title, published=published,
                   author=None, excerpt_html=excerpt, extra=extra or {})


OTHER = "A different headline about routers"


def ok(conn, key, items, **kw):
    return ingest.SourceOutcome(src(conn, key), FetchResult(items=list(items), **kw))


async def run_ingest(conn, outcomes_or_server, run_id, now=NOW, tz="Europe/London"):
    if isinstance(outcomes_or_server, FeedServer):
        sources = sources_repo.list_sources(conn, enabled_only=True)
        return await ingest.ingest(conn, sources, outcomes_or_server.fetcher(), run_id=run_id,
                                   now=now, tz=tz, max_age_hours=72, window_hours=72)
    items, _ = ingest.normalize_all(outcomes_or_server)
    fresh, assignments, _ = ingest.plan_stories(conn, items, now=now, window_hours=72)
    return ingest.store(conn, fresh, assignments, run_id=run_id, now=now, tz=tz)


# --- fetch_all -----------------------------------------------------------------------------

async def test_fetch_all_isolates_each_failure(conn):
    server = FeedServer(conn)
    server.overrides["krebs"] = httpx.Response(
        200, content=feed_bytes("msrc-blog-html.html"), headers={"content-type": "text/html"})
    server.overrides["darkreading"] = httpx.Response(404)
    hn = replace(src(conn, "hn-cloud-sec"), options={"queries": "not a list"})
    weird = replace(src(conn, "schneier"), kind="gopher")
    sources = [src(conn, "krebs"), src(conn, "darkreading"), hn, weird, src(conn, "sans-isc")]
    out = await ingest.fetch_all(sources, server.fetcher(), NOW, max_age_hours=72)
    assert [o.source.key for o in out] == ["krebs", "darkreading", "hn-cloud-sec", "schneier",
                                           "sans-isc"]
    assert out[0].broken and out[0].error.startswith("SourceBroken: ")
    assert not out[1].broken and out[1].error == "FetchHTTPError: HTTP 404"
    assert out[2].error.startswith("ValueError: hn-cloud-sec: options.queries")
    assert out[3].error == "UnknownKind: 'gopher'"
    assert out[4].result is not None and out[4].error is None and out[4].result.items


async def test_fetch_all_limits_sources_in_flight(conn):
    import asyncio

    active = peak = 0

    class SlowFetcher:
        async def get(self, url, **kw):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            raise RuntimeError("stop")

    sources = sources_repo.list_sources(conn)
    out = await ingest.fetch_all(sources, SlowFetcher(), NOW, max_age_hours=72, concurrency=3)
    assert peak == 3 and all(o.error == "RuntimeError: stop" for o in out)
    assert ingest.FETCH_CONCURRENCY == 6


# --- record_health -------------------------------------------------------------------------

def test_record_health_ok_error_broken_and_304(conn):
    sources_repo.record_fetch_ok(conn, src(conn, "krebs").id, at=NOW - timedelta(hours=4),
                                 etag='"e1"', last_modified="Mon", entry_count=5)
    outcomes = [
        ok(conn, "bleepingcomputer", [raw()], etag='"b"', last_modified=None),
        ok(conn, "krebs", [], not_modified=True),  # 304 without validators: keep stored ones
        ingest.SourceOutcome(src(conn, "darkreading"), None, "FetchError: x"),
        ingest.SourceOutcome(src(conn, "schneier"), None, "SourceBroken: y", broken=True),
        ok(conn, "sans-isc", []),
    ]
    stats = ingest.record_health(conn, outcomes, at=NOW)
    assert stats == {"ok": 3, "failed": 2, "not_modified": 1,
                     "failed_keys": ["darkreading", "schneier"]}
    krebs = src(conn, "krebs")
    assert (krebs.etag, krebs.last_modified, krebs.zero_item_runs) == ('"e1"', "Mon", 0)
    assert src(conn, "bleepingcomputer").etag == '"b"'
    assert src(conn, "darkreading").last_error == "FetchError: x"
    assert src(conn, "schneier").last_error == "broken: SourceBroken: y"
    assert src(conn, "sans-isc").zero_item_runs == 1


# --- normalize -----------------------------------------------------------------------------

def test_normalize_cleans_and_canonicalises(conn):
    n = ingest.normalize(src(conn, "bleepingcomputer"), raw(
        url=" https://News.Example/a/?utm_source=x ", title="  <b>Big</b>\n news &amp; more ",
        excerpt="<p>Para</p><script>x()</script>"))
    assert n.canonical_url == "https://news.example/a" and n.url == "https://News.Example/a/?utm_source=x"
    assert n.title == "Big news & more" and n.title_norm == "big new more"
    assert n.excerpt == "Para" and n.kev_vendor is None and n.cve_ids == ()


def test_normalize_skips_bad_urls_and_falls_back_on_empty_title(conn):
    s = src(conn, "bleepingcomputer")
    assert ingest.normalize(s, raw(url="ftp://x.example/a")) is None
    assert ingest.normalize(s, raw(title="  ")).title == "https://news.example/a"
    items, skipped = ingest.normalize_all([ingest.SourceOutcome(s, FetchResult(
        items=[raw(url="javascript:alert(1)"), raw()]))])
    assert len(items) == 1 and skipped == 1


def test_normalize_kev_and_cves(conn):
    n = ingest.normalize(src(conn, "cisa-kev"), raw(
        key="cisa-kev", extra={"kev": True, "vendor": "Microsoft", "cve_ids": ["CVE-2026-1"]}))
    assert n.kev_vendor == "Microsoft" and n.cve_ids == ("CVE-2026-1",)
    m = ingest.normalize(src(conn, "msrc-update-guide"), raw(extra={"cve_ids": ["CVE-2026-2"]}))
    assert m.kev_vendor is None and m.cve_ids == ("CVE-2026-2",)


# --- store ---------------------------------------------------------------------------------

async def test_store_creates_stories_with_day_in_tz(conn):
    run = start(conn)
    late = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)  # 00:30 BST on the 25th
    res = await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw()])], run, now=late)
    story = stories_repo.get_story(conn, res.new_story_ids[0])
    assert story.day == "2026-10-25" and story.first_run_id == run
    assert story.lead_item_id is not None and story.state == "new"
    assert res.stats == {"inserted": 1, "duplicate": 0}


async def test_store_checks_item_exists_before_creating_a_story(conn):
    run = start(conn)
    await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw()])], run)
    stories = count(conn, "stories")
    n = ingest.normalize(src(conn, "bleepingcomputer"), raw())
    res = ingest.store(conn, [n], [Assignment(0, "new", new_group=0)], run_id=run, now=NOW,
                       tz="UTC")
    assert count(conn, "stories") == stories and res.new_story_ids == []
    assert res.stats == {"inserted": 0, "duplicate": 1}


async def test_store_insert_conflict_counts_duplicate(conn, monkeypatch):
    run = start(conn)
    monkeypatch.setattr(items_repo, "insert_item", lambda *a, **kw: None)
    res = await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw()])], run)
    assert res.stats == {"inserted": 0, "duplicate": 1}


async def test_known_items_and_batch_duplicates_are_not_inserted(conn):
    run = start(conn)
    await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw()])], run)
    items, _ = ingest.normalize_all([
        ok(conn, "bleepingcomputer", [raw(), raw(url="https://news.example/b", title=OTHER)]),
        ok(conn, "krebs", [raw(key="krebs", url="https://news.example/b", title=OTHER)]),
    ])
    fresh, assignments, known = ingest.plan_stories(conn, items, now=NOW, window_hours=72)
    assert known == 1 and len(fresh) == 2
    assert [a.kind for a in assignments] == ["new", "duplicate"]


async def test_same_story_from_two_outlets_joins(conn):
    run = start(conn)
    first = await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw(
        title="Microsoft fixes exploited Entra flaw CVE", extra={"cve_ids": ["CVE-2026-7"]})])],
        run)
    later = await run_ingest(conn, [ok(conn, "thehackernews", [raw(
        key="thehackernews", url="https://thn.example/x", title="Unrelated words entirely here",
        extra={"cve_ids": ["CVE-2026-7", "CVE-2026-8"]})])], run, now=NOW + timedelta(hours=1))
    sid = first.new_story_ids[0]
    assert later.joined_story_ids == [sid] and later.new_story_ids == []
    story = stories_repo.get_story(conn, sid)
    assert story.cve_ids == ["CVE-2026-7", "CVE-2026-8"]
    assert len(items_repo.items_for_story(conn, sid)) == 2


async def test_msrc_rollup_titled_with_cve_count(conn):
    run = start(conn)
    day = datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
    items = [raw(key="msrc-update-guide", url=f"https://msrc.example/{i}", title=f"Bug {i} x y z",
                 published=day, extra={"cve_ids": [f"CVE-2026-{i}", f"CVE-2026-{i + 100}"]})
             for i in range(5)]
    res = await run_ingest(conn, [ok(conn, "msrc-update-guide", items)], run)
    assert len(res.new_story_ids) == 1
    story = stories_repo.get_story(conn, res.new_story_ids[0])
    assert story.title == rollup_title(day.date(), 10)
    assert len(story.cve_ids) == 10 and len(items_repo.items_for_story(conn, story.id)) == 5


async def test_kev_item_sets_flags_and_dedupes_by_guid(conn):
    run = start(conn)
    kev = raw(key="cisa-kev", url="https://nvd.example/CVE-2026-9", guid="kev:CVE-2026-9",
              title="KEV: Microsoft Windows: bug", extra={"kev": True, "vendor": "Microsoft",
                                                          "cve_ids": ["CVE-2026-9"]})
    res = await run_ingest(conn, [ok(conn, "cisa-kev", [kev])], run)
    story = stories_repo.get_story(conn, res.new_story_ids[0])
    assert story.flags == {"kev": True, "kev_vendor": "Microsoft"}
    again = await run_ingest(conn, [ok(conn, "cisa-kev", [replace(
        kev, url="https://nvd.example/moved")])], run, now=NOW + timedelta(hours=4))
    assert again.new_story_ids == [] and again.stats["inserted"] == 0


async def test_ingest_stats_over_fixtures(conn):
    run = start(conn)
    server = FeedServer(conn)
    server.overrides["darkreading"] = httpx.Response(500)
    res = await run_ingest(conn, server, run)
    s = res.stats
    assert s["sources"]["ok"] == 20 and s["sources"]["failed_keys"] == ["darkreading"]
    assert s["items"]["new"] == count(conn, "items") and s["items"]["duplicate"] >= 0
    assert s["stories"]["new"] == count(conn, "stories") == len(res.new_story_ids)
    assert s["items"]["fetched"] == s["items"]["new"] + s["items"]["duplicate"] \
        + s["items"]["skipped"]
    assert runs_repo.get_run(conn, run).status == "running"  # ingest never finishes the run

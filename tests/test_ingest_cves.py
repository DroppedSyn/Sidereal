"""CVE ids from news items at ingest (post-M14): title + excerpt, merged by dedupe's CVE rule."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sidereal.db import items_repo, sources_repo, stories_repo
from sidereal.pipeline import ingest
from sidereal.sources.base import FetchResult, RawItem
from tests.pipeline_helpers import NOW, seeded_db, start


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def raw(key, url, title, excerpt="<p>Details.</p>", extra=None):
    return RawItem(source_key=key, guid=url, url=url, title=title,
                   published=NOW - timedelta(hours=1), author=None, excerpt_html=excerpt,
                   extra=extra or {})


def ok(conn, key, items):
    src = sources_repo.get_by_key(conn, key)
    assert src is not None
    return ingest.SourceOutcome(src, FetchResult(items=list(items)))


async def run_ingest(conn, outcomes, run, now=NOW):
    items, _ = ingest.normalize_all(outcomes)
    fresh, assignments, _ = ingest.plan_stories(conn, items, now=now, window_hours=72)
    return ingest.store(conn, fresh, assignments, run_id=run, now=now, tz="UTC")


def sources_of(conn, sid):
    return {i.source_id for i in items_repo.items_for_story(conn, sid)}


def test_item_cve_ids_title_excerpt_upper_and_adapter_first():
    assert ingest.item_cve_ids((), "Fix for CVE-2026-1234", "see cve-2026-12345 and "
                               "CVE-2026-1234 again") == ("CVE-2026-1234", "CVE-2026-12345")
    assert ingest.item_cve_ids(["CVE-2026-9999"], "cve-2026-1111", "CVE-2026-9999") == (
        "CVE-2026-9999", "CVE-2026-1111")
    assert ingest.item_cve_ids((), "CVE-26-1 and CVE-2026-123", "") == ()


def test_more_than_three_text_cves_are_ignored_adapter_ids_kept():
    three = " ".join(f"CVE-2026-100{i}" for i in range(3))
    four = " ".join(f"CVE-2026-100{i}" for i in range(4))
    assert len(ingest.item_cve_ids((), three, "")) == 3
    assert ingest.item_cve_ids((), four, "") == ()
    assert ingest.item_cve_ids(["CVE-2026-7"], "", four) == ("CVE-2026-7",)


async def test_two_outlets_naming_the_same_cve_become_one_story(conn):
    run = start(conn)
    res = await run_ingest(conn, [
        ok(conn, "bleepingcomputer", [raw("bleepingcomputer", "https://bc.example/drupal",
                                          "Drupal patches critical CVE-2026-4242 flaw")]),
        ok(conn, "thehackernews", [raw("thehackernews", "https://thn.example/d",
                                       "Hackers exploit content management bug",
                                       excerpt="<p>Tracked as cve-2026-4242, the issue...</p>")]),
    ], run)
    [sid] = res.new_story_ids
    assert sources_of(conn, sid) == {sources_repo.get_by_key(conn, k).id
                                     for k in ("bleepingcomputer", "thehackernews")}
    assert stories_repo.get_story(conn, sid).cve_ids == ["CVE-2026-4242"]


async def test_lowercase_cve_in_excerpt_joins_a_known_story(conn):
    run = start(conn)
    first = await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw(
        "bleepingcomputer", "https://bc.example/a", "N-able MailAssure flaw CVE-2026-5555")])],
        run)
    later = await run_ingest(conn, [ok(conn, "darkreading", [raw(
        "darkreading", "https://dr.example/b", "Email security gateway attacked",
        excerpt="<p>The bug (cve-2026-5555) is exploited.</p>")])], run,
        now=NOW + timedelta(hours=2))
    assert later.joined_story_ids == first.new_story_ids and later.new_story_ids == []


async def test_roundup_listing_ten_cves_does_not_swallow_a_story(conn):
    """A roundup's text CVEs (> 3) are ignored, so it stays its own story; the small story
    keeps its single CVE and later reports of that CVE still join it."""
    run = start(conn)
    first = await run_ingest(conn, [ok(conn, "bleepingcomputer", [raw(
        "bleepingcomputer", "https://bc.example/a", "Drupal patches CVE-2026-4242")])], run)
    [small] = first.new_story_ids
    cves = ", ".join(["CVE-2026-4242"] + [f"CVE-2026-90{i:02d}" for i in range(9)])
    roundup = await run_ingest(conn, [ok(conn, "darkreading", [raw(
        "darkreading", "https://dr.example/r", "Weekly vulnerability roundup",
        excerpt=f"<p>This week: {cves}.</p>")])], run, now=NOW + timedelta(hours=1))
    assert roundup.joined_story_ids == [] and len(roundup.new_story_ids) == 1
    assert stories_repo.get_story(conn, roundup.new_story_ids[0]).cve_ids == []
    assert stories_repo.get_story(conn, small).cve_ids == ["CVE-2026-4242"]
    later = await run_ingest(conn, [ok(conn, "thehackernews", [raw(
        "thehackernews", "https://thn.example/z", "CMS flaw CVE-2026-4242 under attack")])],
        run, now=NOW + timedelta(hours=2))
    assert later.joined_story_ids == [small]

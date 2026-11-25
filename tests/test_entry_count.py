"""Plan §6.5: ``zero_item_runs`` counts fetches whose answer had 0 entries, not 0 items left
after filters and caps. Adapters report ``FetchResult.entry_count``; ingest stores it."""

from __future__ import annotations

import json

import feedparser
import pytest

from sidereal.db import sources_repo
from sidereal.pipeline import ingest
from sidereal.sources.base import FetchResult
from sidereal.sources.cisa_kev import CisaKevAdapter
from sidereal.sources.hn_algolia import HnAlgoliaAdapter
from sidereal.sources.msrc import MsrcAdapter
from sidereal.sources.rss import RssAdapter
from tests.adapter_helpers import FakeSource, feed_bytes, make_fetcher
from tests.pipeline_helpers import NOW, seeded_db

FAR_FUTURE = NOW.replace(year=2030)  # every fixture entry is past the age cap


@pytest.mark.parametrize("adapter,name", [(RssAdapter, "krebs.xml"),
                                          (MsrcAdapter, "msrc-update-guide.xml")])
async def test_rss_counts_feed_entries_before_cap_and_age(adapter, name):
    body = feed_bytes(name)
    entries = len(feedparser.parse(body).entries)
    fetcher, _ = make_fetcher(body)
    capped = await adapter().fetch(FakeSource(max_items=1), fetcher, NOW)
    assert len(capped.items) <= 1 and capped.entry_count == entries > 1
    old = await adapter().fetch(FakeSource(), fetcher, FAR_FUTURE, max_age_hours=96)
    assert old.items == [] and old.entry_count == entries


async def test_rss_empty_feed_counts_zero():
    body = b"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title></channel></rss>"
    fetcher, _ = make_fetcher(body)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert result.items == [] and result.entry_count == 0


async def test_kev_counts_catalogue_entries():
    body = feed_bytes("cisa-kev.json")
    entries = len(json.loads(body)["vulnerabilities"])
    fetcher, _ = make_fetcher(body, content_type="application/json")
    result = await CisaKevAdapter().fetch(FakeSource(key="cisa-kev"), fetcher, FAR_FUTURE,
                                          max_age_hours=96)
    assert result.items == [] and result.entry_count == entries > 0


async def test_hn_counts_merged_hits_before_age_cap():
    body = feed_bytes("hn-cloud-sec.json")
    hits = {h["objectID"] for h in json.loads(body)["hits"]}
    fetcher, _ = make_fetcher(body, content_type="application/json")
    src = FakeSource(key="hn-cloud-sec", options={"queries": ["azure", "entra"]})
    result = await HnAlgoliaAdapter().fetch(src, fetcher, FAR_FUTURE, max_age_hours=96)
    assert result.items == [] and result.entry_count == len(hits) > 0


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def zero_runs(conn, key):
    return sources_repo.get_by_key(conn, key).zero_item_runs


def record(conn, key, **kw):
    row = sources_repo.get_by_key(conn, key)
    ingest.record_health(conn, [ingest.SourceOutcome(row, FetchResult(items=[], **kw))], at=NOW)


def test_record_health_uses_entry_count(conn):
    record(conn, "krebs", entry_count=0)
    record(conn, "krebs", entry_count=0)
    assert zero_runs(conn, "krebs") == 2
    record(conn, "krebs", entry_count=7)  # entries, all filtered out: not an empty feed
    assert zero_runs(conn, "krebs") == 0
    record(conn, "krebs")  # adapter without a count: falls back to len(items) (0 here)
    assert zero_runs(conn, "krebs") == 1
    record(conn, "krebs", not_modified=True, entry_count=0)  # 304 leaves it alone
    assert zero_runs(conn, "krebs") == 1


async def test_rss_counts_entries_without_usable_links():
    body = (b"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>"
            b"<item><title>a</title><link>ftp://x.example/a</link></item>"
            b"<item><title>b</title></item></channel></rss>")
    fetcher, _ = make_fetcher(body)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert result.items == [] and result.entry_count == 2

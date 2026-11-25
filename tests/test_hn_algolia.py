from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from sidereal.net.fetch import Fetcher, FetchHTTPError
from sidereal.net.guard import UrlGuard
from sidereal.sources.base import REGISTRY, SourceBroken
from sidereal.sources.hn_algolia import HnAlgoliaAdapter, search_url
from tests.adapter_helpers import FakeSource, fake_resolver, feed_bytes, make_fetcher

NOW = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)
BASE = "https://hn.algolia.com/api/v1/search_by_date"
HN = feed_bytes("hn-cloud-sec.json")


def src(**options) -> FakeSource:
    return FakeSource(key="hn-cloud-sec", url=BASE, options=options)


async def test_request_url_defaults():
    fetcher, seen = make_fetcher(HN, content_type="application/json")
    await HnAlgoliaAdapter().fetch(src(queries=["azure"]), fetcher, NOW)
    assert len(seen) == 1
    assert (
        str(seen[0].url)
        == BASE
        + "?query=azure&tags=story&numericFilters=points%3E%3D40%2Ccreated_at_i%3E1795219200"
    )
    assert seen[0].headers["accept"] == "application/json"
    assert "if-none-match" not in seen[0].headers


async def test_min_points_and_window_in_url():
    fetcher, seen = make_fetcher(
        HN, content_type="application/json"
    )
    await HnAlgoliaAdapter().fetch(
        src(queries=["zero day"], min_points=100),
        fetcher,
        NOW,
        max_age_hours=72,
    )
    assert (
        str(seen[0].url)
        == BASE
        + "?query=zero+day&tags=story&numericFilters=points%3E%3D100%2Ccreated_at_i%3E1795305600"
    )


async def test_search_url():
    assert (
        search_url(BASE, "zero day", 40, 1795219200)
        == BASE
        + "?query=zero+day&tags=story&numericFilters=points%3E%3D40%2Ccreated_at_i%3E1795219200"
    )


async def test_one_request_per_query_dedupes():
    fetcher, seen = make_fetcher(HN, content_type="application/json")
    result = await HnAlgoliaAdapter().fetch(src(queries=["azure", "entra"]), fetcher, NOW)
    assert [r.url.params["query"] for r in seen] == ["azure", "entra"]
    assert len(result.items) == 20
    assert len({it.guid for it in result.items}) == 20


async def test_first_query_wins_on_duplicate_object_id():
    def hit(title: str, points: int) -> dict:
        return {"objectID": "7", "title": title, "points": points, "created_at_i": 1795560000}

    bodies = {
        "azure": json.dumps({"hits": [hit("from azure", 50)]}).encode(),
        "entra": json.dumps({"hits": [hit("from entra", 99)]}).encode(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[request.url.params["query"]]
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(client=client, guard=UrlGuard(resolver=fake_resolver))
    result = await HnAlgoliaAdapter().fetch(src(queries=["azure", "entra"]), fetcher, NOW)
    assert [(it.guid, it.title, it.extra["hn_points"]) for it in result.items] == [
        ("hn:7", "from azure", 50)
    ]


async def test_missing_url_falls_back_to_item_link():
    fetcher, _ = make_fetcher(HN, content_type="application/json")
    result = await HnAlgoliaAdapter().fetch(src(queries=["azure"]), fetcher, NOW)
    item = next(it for it in result.items if it.guid == "hn:50471668")
    assert item.url == "https://news.ycombinator.com/item?id=50471668"
    assert item.title == "Ask HN: Microsoft/Azure Outage?"
    assert item.author == "nazgulsenpai"
    assert item.published == datetime(2026, 11, 12, 18, 17, 13, tzinfo=UTC)
    assert item.excerpt_html == (
        "For the past 5 minutes all of our Microsoft Cloud connections are down. "
        "Anyone else? The Status page won&#x27;t even load."
    )
    assert item.extra == {
        "hn_points": 402,
        "hn_comments": 1,
        "hn_url": "https://news.ycombinator.com/item?id=50471668",
    }


async def test_story_url_kept():
    fetcher, _ = make_fetcher(HN, content_type="application/json")
    result = await HnAlgoliaAdapter().fetch(src(queries=["azure"]), fetcher, NOW)
    item = next(it for it in result.items if it.guid == "hn:50301854")
    assert item.url == "https://www.binarysecurity.no/posts/2026/10/one-root-case"
    assert item.excerpt_html == ""
    assert item.extra == {
        "hn_points": 340,
        "hn_comments": 64,
        "hn_url": "https://news.ycombinator.com/item?id=50301854",
    }
    assert item.source_key == "hn-cloud-sec"


async def test_age_cap():
    fetcher, _ = make_fetcher(HN, content_type="application/json")
    result = await HnAlgoliaAdapter().fetch(
        src(queries=["azure"]), fetcher, NOW, max_age_hours=336
    )
    assert [it.guid for it in result.items] == [
        "hn:50581403",
        "hn:50471668",
    ]


async def test_max_items():
    s = FakeSource(
        key="hn-cloud-sec",
        url=BASE,
        max_items=3,
        options={"queries": ["azure"]},
    )
    fetcher, _ = make_fetcher(HN, content_type="application/json")
    result = await HnAlgoliaAdapter().fetch(s, fetcher, NOW)
    assert [it.guid for it in result.items] == [
        "hn:50581403",
        "hn:50471668",
        "hn:50301854",
    ]


async def test_bad_json_is_broken():
    fetcher, _ = make_fetcher(b"<html>oops</html>", content_type="application/json")
    with pytest.raises(SourceBroken):
        await HnAlgoliaAdapter().fetch(src(queries=["azure"]), fetcher, NOW)
    fetcher, _ = make_fetcher(
        b'{"message": "x"}', content_type="application/json"
    )
    with pytest.raises(SourceBroken):
        await HnAlgoliaAdapter().fetch(src(queries=["azure"]), fetcher, NOW)


async def test_bad_hits_skipped():
    body = json.dumps(
        {
            "hits": [
                {"title": "no id"},
                {"objectID": "1", "title": "  "},
                "junk",
                {
                    "objectID": "2",
                    "title": "ok",
                    "url": "javascript:alert(1)",
                    "created_at_i": True,
                },
            ]
        }
    ).encode()
    fetcher, _ = make_fetcher(body, content_type="application/json")
    result = await HnAlgoliaAdapter().fetch(src(queries=["azure"]), fetcher, NOW)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.guid == "hn:2"
    assert item.url == "https://news.ycombinator.com/item?id=2"
    assert item.published is None
    assert item.extra == {
        "hn_points": 0,
        "hn_comments": 0,
        "hn_url": "https://news.ycombinator.com/item?id=2",
    }


async def test_invalid_options():
    # All these raise ValueError before any request is made.
    bad_options = [
        ({}, r"hn-cloud-sec: options\.queries"),
        ({"queries": []}, r"hn-cloud-sec: options\.queries"),
        ({"queries": "azure"}, r"hn-cloud-sec: options\.queries"),
        ({"queries": ["azure", ""]}, r"hn-cloud-sec: options\.queries"),
        ({"queries": ["azure"], "min_points": "40"}, r"hn-cloud-sec: options\.min_points"),
        ({"queries": ["azure"], "min_points": True}, r"hn-cloud-sec: options\.min_points"),
    ]
    fetcher, seen = make_fetcher(HN, content_type="application/json")
    for opts, match in bad_options:
        with pytest.raises(ValueError, match=match):
            await HnAlgoliaAdapter().fetch(src(**opts), fetcher, NOW)
    assert len(seen) == 0


async def test_http_error_propagates():
    fetcher, seen = make_fetcher(b"", status=500)
    with pytest.raises(FetchHTTPError):
        await HnAlgoliaAdapter().fetch(
            src(queries=["a", "b"]), fetcher, NOW
        )
    assert len(seen) == 1


async def test_registered():
    assert REGISTRY["hn_algolia"] is HnAlgoliaAdapter

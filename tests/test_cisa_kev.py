from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from sidereal.net.fetch import FetchHTTPError
from sidereal.sources.base import REGISTRY, FetchResult, SourceBroken
from sidereal.sources.cisa_kev import CisaKevAdapter
from tests.adapter_helpers import FakeSource, feed_bytes, make_fetcher

NOW = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
KEV = feed_bytes("cisa-kev.json")
SRC = FakeSource(key="cisa-kev")
RAW = json.loads(KEV)["vulnerabilities"]
FIRST9 = [
    "kev:CVE-2026-132224",
    "kev:CVE-2026-131914",
    "kev:CVE-2026-132165",
    "kev:CVE-2026-133968",
    "kev:CVE-2026-134624",
    "kev:CVE-2026-129448",
    "kev:CVE-2026-123890",
    "kev:CVE-2025-42884",
    "kev:CVE-2026-76466",
]


async def test_age_window_96h():
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW, max_age_hours=96)
    assert [it.guid for it in result.items] == FIRST9


async def test_first_run_backfill_72h():
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW, max_age_hours=72)
    assert [it.guid for it in result.items] == FIRST9[:5]


async def test_no_cap_returns_all():
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW)
    assert len(result.items) == 20
    assert [it.guid for it in result.items] == ["kev:" + e["cveID"] for e in RAW]


async def test_max_items():
    src = FakeSource(key="cisa-kev", max_items=3)
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(src, fetcher, NOW)
    assert [it.guid for it in result.items] == FIRST9[:3]


async def test_item_fields():
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW)
    item = next(it for it in result.items if it.guid == "kev:CVE-2026-132224")
    assert item.title == (
        "KEV: Optimizely Web Experimentation: "
        "Optimizely Web Experimentation External Control of Critical State Data Vulnerability"
    )
    assert item.url == "https://nvd.nist.gov/vuln/detail/CVE-2026-132224"
    assert item.source_key == "cisa-kev"
    assert item.author is None
    assert item.published == datetime(2026, 11, 24, tzinfo=UTC)
    assert item.extra == {
        "kev": True,
        "cve_ids": ["CVE-2026-132224"],
        "vendor": "Optimizely",
        "product": "Web Experimentation",
        "ransomware": False,
    }
    assert item.excerpt_html == "\n\n".join(
        [
            RAW[0]["shortDescription"],
            "Required action: " + RAW[0]["requiredAction"],
            "Due date: 2026-11-27",
        ]
    )


async def test_microsoft_vendor():
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW)
    microsoft = [
        it.extra["cve_ids"][0]
        for it in result.items
        if it.extra["vendor"] == "Microsoft"
    ]
    assert microsoft == [
        "CVE-2026-124194",
        "CVE-2026-96951",
        "CVE-2026-65660",
        "CVE-2026-81963",
        "CVE-2026-85880",
        "CVE-2019-1068",
    ]


async def test_ransomware_flag():
    fetcher, _ = make_fetcher(KEV, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW)
    ransomware_guids = [it.guid for it in result.items if it.extra["ransomware"]]
    assert ransomware_guids == ["kev:CVE-2024-10441"]
    ransom_item = next(it for it in result.items if it.guid == "kev:CVE-2024-10441")
    assert (
        ransom_item.excerpt_html.endswith(
            "Due date: 2026-11-21\n\nKnown ransomware campaign use."
        )
        is True
    )
    for it in result.items:
        if it.guid != "kev:CVE-2024-10441":
            assert "ransomware" not in it.excerpt_html


async def test_malformed_json_is_broken():
    fetcher, _ = make_fetcher(
        b"<!doctype html><html><body>Error</body></html>",
        content_type="text/html",
    )
    with pytest.raises(SourceBroken):
        await CisaKevAdapter().fetch(SRC, fetcher, NOW)


async def test_missing_vulnerabilities_is_broken():
    for body in [b'{"title": "x"}', b'{"vulnerabilities": {}}', b"[]"]:
        fetcher, _ = make_fetcher(body, content_type="application/json")
        with pytest.raises(SourceBroken):
            await CisaKevAdapter().fetch(SRC, fetcher, NOW)


async def test_bad_entries_skipped():
    body = json.dumps(
        {
            "vulnerabilities": [
                {"vendorProject": "A", "dateAdded": "2026-11-23"},
                {"cveID": "CVE-2026-1", "dateAdded": "not a date"},
                {"cveID": "  ", "dateAdded": "2026-11-23"},
                "junk",
                {
                    "cveID": "CVE-2026-2",
                    "vendorProject": "V",
                    "product": "P",
                    "vulnerabilityName": "N",
                    "dateAdded": "2026-11-23",
                },
            ]
        }
    ).encode()
    fetcher, _ = make_fetcher(body, content_type="application/json")
    result = await CisaKevAdapter().fetch(SRC, fetcher, NOW)
    assert [it.guid for it in result.items] == ["kev:CVE-2026-2"]
    item = result.items[0]
    assert item.title == "KEV: V P: N"
    assert item.excerpt_html == ""
    assert item.extra["ransomware"] is False


async def test_conditional_get():
    source = FakeSource(
        key="cisa-kev",
        etag='"abc"',
        last_modified="Tue, 24 Nov 2026 10:00:00 GMT",
    )
    fetcher, seen = make_fetcher(b"", status=304)
    result = await CisaKevAdapter().fetch(source, fetcher, NOW)
    assert result == FetchResult(
        items=[],
        not_modified=True,
        etag='"abc"',
        last_modified="Tue, 24 Nov 2026 10:00:00 GMT",
    )
    assert seen[0].headers["if-none-match"] == '"abc"'


async def test_request():
    fetcher, seen = make_fetcher(KEV, content_type="application/json")
    await CisaKevAdapter().fetch(SRC, fetcher, NOW)
    assert str(seen[0].url) == SRC.url
    assert seen[0].headers["accept"] == "application/json"


async def test_http_error_propagates():
    fetcher, _ = make_fetcher(b"", status=500)
    with pytest.raises(FetchHTTPError):
        await CisaKevAdapter().fetch(SRC, fetcher, NOW)


async def test_registered():
    assert REGISTRY["cisa_kev"] is CisaKevAdapter

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from sidereal.sources.base import SourceBroken
from sidereal.sources.msrc import DEFAULT_PRODUCT_REGEX, MsrcAdapter, extract_cve_ids
from sidereal.sources.rss import RssAdapter
from tests.adapter_helpers import FakeSource, feed_bytes, make_fetcher

NOW = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)
SRC = FakeSource(key="msrc-update-guide", max_items=300)
# max_age_hours=152 → cutoff 2026-11-18T16:00Z; the Active Directory entry sits exactly on it.
AGE_152_TITLES = [
    "CVE-2026-96082 Windows Kerberos Denial of Service Vulnerability",
    "CVE-2026-88130 Role: DNS Server Denial of Service Vulnerability",
    "CVE-2026-55007 Microsoft Exchange Server Remote Code Execution Vulnerability",
    "CVE-2026-63516 Microsoft SharePoint Server Spoofing Vulnerability",
    "CVE-2026-118148 Active Directory Domain Services Elevation of Privilege Vulnerability",
]


async def test_product_filter_keeps_matching():
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    result = await MsrcAdapter().fetch(SRC, fetcher, NOW)
    assert len(result.items) == 20
    for it in result.items:
        assert re.search(DEFAULT_PRODUCT_REGEX, it.title)
    for it in result.items:
        assert "chromium" not in it.title.lower()


async def test_cve_ids_extracted():
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    result = await MsrcAdapter().fetch(SRC, fetcher, NOW)
    assert len(result.items) == 20
    for it in result.items:
        assert it.source_key == "msrc-update-guide"
        assert it.extra["cve_ids"] == [it.title.split()[0]]
    exchange = [
        it for it in result.items if it.title.startswith("CVE-2026-55007 Microsoft Exchange Server")
    ]
    assert len(exchange) == 1
    assert exchange[0].extra == {"cve_ids": ["CVE-2026-55007"]}


async def test_cve_ids_from_guid_and_url_lowercase():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>MSRC</title>'
        b"<item><title>Windows Kerberos advisory</title>"
        b"<link>https://msrc.microsoft.com/update-guide/vulnerability/cve-2026-1111</link>"
        b"<guid>cve-2026-2222</guid><pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate></item>"
        b"</channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await MsrcAdapter().fetch(SRC, fetcher, NOW)
    assert [it.extra for it in result.items] == [{"cve_ids": ["CVE-2026-2222", "CVE-2026-1111"]}]


async def test_extract_cve_ids():
    result = extract_cve_ids("cve-2026-1234 and CVE-2026-1234,", "CVE-2025-123456; CVE-12-1")
    assert result == ["CVE-2026-1234", "CVE-2025-123456"]
    assert extract_cve_ids("") == []


async def test_age_cap_before_filter():
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    source = FakeSource(key="msrc-update-guide", max_items=300)
    result = await MsrcAdapter().fetch(source, fetcher, NOW, max_age_hours=152)
    assert [it.title for it in result.items] == AGE_152_TITLES


async def test_max_items_applies_after_product_filter():
    # Raw newest-first order: the 16 newest entries match no product (.NET, Visio, Chromium...);
    # the first match is raw entry 17. Filtering first must keep it with max_items=3 or 12.
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    source = FakeSource(key="msrc-update-guide", max_items=3)
    result = await MsrcAdapter().fetch(source, fetcher, NOW)
    assert [it.title for it in result.items] == AGE_152_TITLES[:3]

    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    source = FakeSource(key="msrc-update-guide", max_items=12)
    result = await MsrcAdapter().fetch(source, fetcher, NOW)
    assert len(result.items) == 12
    assert [it.title for it in result.items[:5]] == AGE_152_TITLES
    assert all(re.search(DEFAULT_PRODUCT_REGEX, it.title) for it in result.items)


async def test_max_items_cuts_after_age_cap_and_filter():
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    source = FakeSource(key="msrc-update-guide", max_items=4)
    result = await MsrcAdapter().fetch(source, fetcher, NOW, max_age_hours=152)
    assert [it.title for it in result.items] == AGE_152_TITLES[:4]


async def test_include_exclude_before_cap():
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    source = FakeSource(
        key="msrc-update-guide",
        max_items=2,
        options={"include_regex": "(?i)sharepoint", "exclude_regex": "Spoofing"},
    )
    result = await MsrcAdapter().fetch(source, fetcher, NOW)
    assert [it.title for it in result.items] == [
        "CVE-2026-124223 Microsoft Office SharePoint Remote Code Execution Vulnerability",
        "CVE-2026-124222 Microsoft Office SharePoint Elevation of Privilege Vulnerability",
    ]


async def test_product_regex_option():
    fetcher, _ = make_fetcher(feed_bytes("msrc-update-guide.xml"))
    source = FakeSource(key="msrc-update-guide", options={"product_regex": "(?i)chromium"})
    result = await MsrcAdapter().fetch(source, fetcher, NOW)
    assert len(result.items) == 5
    assert all("chromium" in it.title.lower() for it in result.items)


async def test_html_page_is_broken():
    fetcher, _ = make_fetcher(
        feed_bytes("msrc-blog-html.html"),
        content_type="text/html",
    )
    with pytest.raises(SourceBroken):
        await MsrcAdapter().fetch(SRC, fetcher, NOW)


async def test_msrc_is_rss_subclass():
    assert issubclass(MsrcAdapter, RssAdapter)
    assert MsrcAdapter.kind == "msrc"

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.net.fetch import FetchHTTPError, FetchTooLarge
from sidereal.sources.base import FetchResult, SourceBroken
from sidereal.sources.rss import FEED_ACCEPT, RssAdapter
from tests.adapter_helpers import FEED_URL, FEEDS, FakeSource, feed_bytes, make_fetcher

NOW = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)

RSS_FIXTURES = sorted(p.name for p in FEEDS.glob("*.xml") if p.name != "tc-dead-board.xml")


@pytest.mark.parametrize("fixture_name", RSS_FIXTURES, ids=RSS_FIXTURES)
async def test_every_fixture_yields_items(fixture_name: str):
    fetcher, _ = make_fetcher(feed_bytes(fixture_name))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert result.not_modified is False
    assert 1 <= len(result.items) <= 50
    for it in result.items:
        assert it.source_key == "test-source"
        assert it.title and it.title == it.title.strip()
        assert it.url.startswith(("http://", "https://"))
        assert it.guid
        assert isinstance(it.excerpt_html, str)
        assert it.extra == {}
        assert it.published is None or (
            it.published.utcoffset() == timedelta(0) and it.published <= NOW + timedelta(days=1)
        )


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("azure-updates.xml", 20),
        ("azure-blog.xml", 10),
        ("schneier.xml", 10),
        ("msrc-update-guide.xml", 40),
    ],
    ids=["azure-updates", "azure-blog", "schneier", "msrc-update-guide"],
)
async def test_exact_counts(fixture_name: str, expected: int):
    fetcher, _ = make_fetcher(feed_bytes(fixture_name))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert len(result.items) == expected


async def test_bleepingcomputer_first_item_fields():
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    first = result.items[0]
    assert first.title == "Rackspace shuts down Spot cloud platform after security breach"
    assert (
        first.url
        == "https://www.bleepingcomputer.com/news/security/rackspace-shuts-down-spot-cloud-platform-after-security-breach/"
    )
    assert (
        first.guid
        == "https://www.bleepingcomputer.com/news/security/rackspace-shuts-down-spot-cloud-platform-after-security-breach/"
    )
    assert first.published == datetime(2026, 11, 24, 21, 37, 30, tzinfo=UTC)
    assert first.author == "Lawrence Abrams"
    assert first.excerpt_html != ""


async def test_atom_schneier_first_item():
    fetcher, _ = make_fetcher(feed_bytes("schneier.xml"))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    first = result.items[0]
    assert first.title == "We Get the Infrastructure We Pay For"
    assert first.guid == "https://www.schneier.com/?p=72991"
    assert (
        first.url
        == "https://www.schneier.com/blog/archives/2026/11/we-get-the-infrastructure-we-pay-for.html"
    )
    assert first.published == datetime(2026, 11, 24, 12, 6, 50, tzinfo=UTC)
    assert first.author == "Bruce Schneier"


async def test_link_rules_and_guid_fallback():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        b"<item><title>No link here</title><description>x</description></item>"
        b"<item><title>  Has link  </title><link>https://example.com/a</link>"
        b"<description>&lt;p&gt;Hi&lt;/p&gt;</description></item>"
        b"<item><title>Bad scheme</title><link>javascript:alert(1)</link></item>"
        b"</channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert len(result.items) == 1
    it = result.items[0]
    assert it.title == "Has link"
    assert it.url == "https://example.com/a"
    assert it.guid == "https://example.com/a"
    assert it.excerpt_html == "<p>Hi</p>"
    assert it.published is None
    assert it.author is None


async def test_excerpt_from_content_and_guid_from_id():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        b"<channel><title>T</title><item><title>Only content</title><link>https://example.com/c</link>"
        b'<guid isPermaLink="false">tag-1</guid>'
        b"<content:encoded><![CDATA[<p>Body <b>text</b></p>]]></content:encoded>"
        b"<pubDate>Tue, 24 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert len(result.items) == 1
    it = result.items[0]
    assert it.guid == "tag-1"
    assert it.excerpt_html == "<p>Body <b>text</b></p>"
    assert it.published == datetime(2026, 11, 24, 10, 0, tzinfo=UTC)


async def test_dead_board_is_broken():
    fetcher, _ = make_fetcher(feed_bytes("tc-dead-board.xml"))
    with pytest.raises(SourceBroken):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_html_page_is_broken_not_empty():
    fetcher, _ = make_fetcher(
        feed_bytes("msrc-blog-html.html"),
        content_type="text/html; charset=utf-8",
    )
    with pytest.raises(SourceBroken):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_html_page_sniffed_without_html_content_type():
    fetcher, _ = make_fetcher(
        feed_bytes("msrc-blog-html.html"),
        content_type="application/rss+xml",
    )
    with pytest.raises(SourceBroken):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_krebs_served_as_html_still_parses():
    fetcher, _ = make_fetcher(
        feed_bytes("krebs.xml"),
        content_type="text/html",
    )
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert len(result.items) == 10


async def test_empty_feed_is_not_broken():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>Quiet feed</title>'
        b"<link>https://example.com/</link></channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert result.items == []


async def test_error_title_regex_option():
    fetcher, _ = make_fetcher(
        feed_bytes("tc-dead-board.xml"),
    )
    source = FakeSource(options={"error_title_regex": "(?i)maintenance"})
    result = await RssAdapter().fetch(source, fetcher, NOW)
    assert result.items == []


async def test_include_regex():
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    source = FakeSource(options={"include_regex": "(?i)breach"})
    result = await RssAdapter().fetch(source, fetcher, NOW)
    assert len(result.items) == 5
    for it in result.items:
        assert "breach" in it.title.lower()


async def test_exclude_regex():
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    source = FakeSource(options={"exclude_regex": "(?i)breach"})
    result = await RssAdapter().fetch(source, fetcher, NOW)
    assert len(result.items) == 10
    for it in result.items:
        assert "breach" not in it.title.lower()


async def test_max_items_newest_first():
    fetcher, _ = make_fetcher(feed_bytes("tc-sentinel.xml"))
    source = FakeSource(max_items=3)
    result = await RssAdapter().fetch(source, fetcher, NOW)
    titles = [it.title for it in result.items]
    assert titles == [
        "Microsoft Ignite 2026: New Sentinel Connectors Announcement",
        "Ignite 2026: What's new in Microsoft Sentinel",
        "Protecting Microsoft's SAP workload with Microsoft Sentinel for SAP:"
        " the RISE with SAP chapter",
    ]


async def test_age_cap():
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW, max_age_hours=24)
    assert len(result.items) == 11
    for it in result.items:
        assert it.published is not None and it.published >= NOW - timedelta(hours=24)

    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW, max_age_hours=48)
    assert len(result.items) == 15


async def test_age_cap_keeps_undated():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
        b"<item><title>No link here</title><description>x</description></item>"
        b"<item><title>  Has link  </title><link>https://example.com/a</link>"
        b"<description>&lt;p&gt;Hi&lt;/p&gt;</description></item>"
        b"<item><title>Bad scheme</title><link>javascript:alert(1)</link></item>"
        b"</channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW, max_age_hours=1)
    assert [it.title for it in result.items] == ["Has link"]


async def test_conditional_get_headers():
    etag_req = '"abc"'
    lm_req = "Tue, 24 Nov 2026 10:00:00 GMT"
    source = FakeSource(etag=etag_req, last_modified=lm_req)
    resp_headers = {
        "etag": '"def"',
        "last-modified": "Wed, 25 Nov 2026 10:00:00 GMT",
    }
    fetcher, seen = make_fetcher(
        feed_bytes("azure-blog.xml"),
        headers=resp_headers,
    )
    result = await RssAdapter().fetch(source, fetcher, NOW)
    assert seen[0].headers["if-none-match"] == etag_req
    assert seen[0].headers["if-modified-since"] == lm_req
    assert seen[0].headers["accept"] == FEED_ACCEPT
    assert str(seen[0].url) == FEED_URL
    assert result.etag == '"def"'
    assert result.last_modified == "Wed, 25 Nov 2026 10:00:00 GMT"
    assert len(result.items) == 10


async def test_not_modified():
    source = FakeSource(etag='"abc"', last_modified="Tue, 24 Nov 2026 10:00:00 GMT")
    fetcher, seen = make_fetcher(b"", status=304)
    result = await RssAdapter().fetch(source, fetcher, NOW)
    assert result == FetchResult(
        items=[], not_modified=True, etag='"abc"', last_modified="Tue, 24 Nov 2026 10:00:00 GMT"
    )
    assert len(seen) == 1


async def test_max_bytes_option():
    fetcher, _ = make_fetcher(
        feed_bytes("azure-blog.xml"),
    )
    source = FakeSource(options={"max_bytes": 100})
    with pytest.raises(FetchTooLarge):
        await RssAdapter().fetch(source, fetcher, NOW)


async def test_http_error_propagates():
    fetcher, _ = make_fetcher(b"", status=500)
    with pytest.raises(FetchHTTPError):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_feedparser_gets_bytes_only(monkeypatch):
    import sidereal.sources.rss as rss_mod

    real_parse = rss_mod.feedparser.parse
    seen_types: list[type] = []

    def spy(data, *args, **kwargs):
        seen_types.append(type(data))
        return real_parse(data, *args, **kwargs)

    monkeypatch.setattr(rss_mod.feedparser, "parse", spy)
    fetcher, _ = make_fetcher(feed_bytes("azure-blog.xml"))
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert len(result.items) == 10
    assert seen_types == [bytes]
    with pytest.raises(TypeError):
        RssAdapter().parse(FakeSource(), str(FEEDS / "azure-blog.xml"), "text/xml", NOW)  # type: ignore[arg-type]


async def test_excerpt_prefers_summary_over_content():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"'
        b' xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>T</title>'
        b"<item><title>Both</title><link>https://example.com/b</link>"
        b"<description>Short &lt;i&gt;teaser&lt;/i&gt;</description>"
        b"<content:encoded><![CDATA[<p>Long body</p>]]></content:encoded></item>"
        b"</channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert [it.excerpt_html for it in result.items] == ["Short <i>teaser</i>"]


async def test_error_title_with_entries_is_not_broken():
    feed = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>Error handling blog</title>'
        b"<item><title>A</title><link>https://example.com/a</link></item></channel></rss>"
    )
    fetcher, _ = make_fetcher(feed)
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert [it.title for it in result.items] == ["A"]


async def test_broken_messages_name_source_and_reason():
    fetcher, _ = make_fetcher(feed_bytes("tc-dead-board.xml"))
    with pytest.raises(SourceBroken, match=r"^test-source: error feed .*Resource Not Found"):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    fetcher, _ = make_fetcher(feed_bytes("msrc-blog-html.html"), content_type="text/html")
    with pytest.raises(SourceBroken, match=r"^test-source: HTML page"):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_html_sniff_after_bom_and_whitespace():
    body = b"\xef\xbb\xbf  \n<HTML><head><title>App</title></head><body><p>x</body></html>"
    fetcher, _ = make_fetcher(body, content_type="application/octet-stream")
    with pytest.raises(SourceBroken, match="HTML page"):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_include_and_exclude_together():
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    source = FakeSource(
        max_items=2, options={"include_regex": "(?i)breach", "exclude_regex": "Rackspace"}
    )
    result = await RssAdapter().fetch(source, fetcher, NOW)
    assert len(result.items) == 2
    for it in result.items:
        assert "breach" in it.title.lower() and "Rackspace" not in it.title


async def test_invalid_option_regex_is_a_clear_error():
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    source = FakeSource(options={"include_regex": "(unclosed"})
    with pytest.raises(ValueError, match=r"test-source: invalid options\.include_regex"):
        await RssAdapter().fetch(source, fetcher, NOW)


async def test_html_content_type_without_html_start_is_broken():
    # No <!doctype>/<html> prefix to sniff: only the content type says HTML.
    fetcher, _ = make_fetcher(b"<div><p>Loading</div>", content_type="text/html")
    with pytest.raises(SourceBroken, match="HTML page"):
        await RssAdapter().fetch(FakeSource(), fetcher, NOW)


async def test_quiet_feed_served_as_html_is_not_broken():
    # Well-formed feed (bozo False) with 0 entries: the HTML content type alone is not an error.
    feed = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Quiet</title></channel></rss>'
    fetcher, _ = make_fetcher(feed, content_type="text/html; charset=utf-8")
    result = await RssAdapter().fetch(FakeSource(), fetcher, NOW)
    assert result.items == []

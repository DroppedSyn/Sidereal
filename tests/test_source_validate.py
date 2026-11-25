"""sources/validate.py (M27): static URL checks and per-kind option validation."""

from __future__ import annotations

import pytest

from sidereal.sources.validate import check_source_url, clean_options, is_local_name


@pytest.mark.parametrize("url", [
    "https://feeds.example.com/rss",
    "http://example.org/feed.xml",
    "https://93.184.215.14/feed",
    "  https://example.com/x  ",
])
def test_good_urls(url):
    assert check_source_url(url) == url.strip()


@pytest.mark.parametrize("url, reason", [
    ("", "required"),
    ("ftp://example.com/feed", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("javascript:alert(1)", "scheme"),
    ("https://user:pw@example.com/", "userinfo"),
    ("https://example.com:8080/feed", "port 8080"),
    ("http://127.0.0.1/feed", "loopback"),
    ("http://10.0.0.5/feed", "private"),
    ("http://192.168.1.1/", "private"),
    ("http://169.254.169.254/latest/meta-data", "link_local"),
    ("http://[::1]/", "refused: address ::1"),
    ("http://[::ffff:127.0.0.1]/", "loopback"),
    ("http://2130706433/", "numeric host"),
    ("http://0x7f.1/", "numeric host"),
    ("http://localhost/feed", "local host name"),
    ("http://intranet/feed", "local host name"),
    ("http://nas.local/feed", "local host name"),
    ("http://router.lan/", "local host name"),
    ("http://svc.internal/", "local host name"),
    ("https://exa mple.com/", "whitespace"),
    ("https://example.com/" + "a" * 2000, "longer than"),
])
def test_bad_urls(url, reason):
    with pytest.raises(ValueError, match=reason):
        check_source_url(url)


def test_local_names():
    assert is_local_name("LOCALHOST.") and is_local_name("box") and is_local_name("a.home.arpa")
    assert not is_local_name("example.com") and not is_local_name("local.example.com")


def test_rss_options_cleaned():
    out = clean_options("rss", "k", {
        "article_hosts": [" Example.COM. ", "example.com", "www.example.org"],
        "include_regex": "(?i)azure", "exclude_regex": "", "max_bytes": 4_000_000})
    assert out == {"article_hosts": ["example.com", "www.example.org"],
                   "include_regex": "(?i)azure", "max_bytes": 4_000_000}


@pytest.mark.parametrize("kind, options, message", [
    ("rss", {"include_regex": "(unclosed"}, "invalid options.include_regex"),
    ("rss", {"exclude_regex": "[a-"}, "invalid options.exclude_regex"),
    ("msrc", {"product_regex": "*bad"}, "invalid options.product_regex"),
    ("rss", {"error_title_regex": "x" * 501}, "at most 500"),
    ("rss", {"include_regex": 5}, "regular expression"),
    ("rss", {"product_regex": "azure"}, "not used by rss"),
    ("rss", {"queries": ["x"]}, "not used by rss"),
    ("rss", {"surprise": 1}, "not used by rss"),
    ("cisa_kev", {"include_regex": "x"}, "not used by cisa_kev"),
    ("rss", {"article_hosts": "example.com"}, "list"),
    ("rss", {"article_hosts": ["localhost"]}, "not a public host"),
    ("rss", {"article_hosts": ["10.0.0.1"]}, "not a public host"),
    ("rss", {"article_hosts": ["exa mple.com"]}, "not a public host"),
    ("rss", {"article_hosts": [7]}, "not a public host"),
    ("rss", {"article_hosts": [f"h{i}.example.com" for i in range(21)]}, "at most 20"),
    ("rss", {"max_bytes": 0}, "max_bytes"),
    ("rss", {"max_bytes": 20_000_001}, "max_bytes"),
    ("rss", {"max_bytes": True}, "max_bytes"),
    ("rss", {"max_bytes": "4000000"}, "max_bytes"),
    ("hn_algolia", {}, "queries"),
    ("hn_algolia", {"queries": []}, "queries"),
    ("hn_algolia", {"queries": ["ok", "  "]}, "queries"),
    ("hn_algolia", {"queries": ["x" * 101]}, "queries"),
    ("hn_algolia", {"queries": ["azure"], "min_points": -1}, "min_points"),
    ("hn_algolia", {"queries": ["azure"], "min_points": 1.5}, "min_points"),
    ("nope", {}, "unknown source kind"),
])
def test_bad_options(kind, options, message):
    with pytest.raises(ValueError, match=message):
        clean_options(kind, "k", options)


def test_hn_options_kept():
    assert clean_options("hn_algolia", "hn", {"queries": [" zero   day "], "min_points": 40}) == {
        "queries": ["zero day"], "min_points": 40}


def test_regex_semantics_match_a_run():
    """Same compile as ``base.option_regex``: a pattern Python accepts is accepted as is."""
    assert clean_options("msrc", "m", {"product_regex": r"(?i)\b(azure|entra)\b"}) == {
        "product_regex": r"(?i)\b(azure|entra)\b"}

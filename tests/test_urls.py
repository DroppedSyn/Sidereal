import pytest

from sidereal.urls import canonicalize, host_matches, host_of, is_http_url


def test_lowercases_scheme_and_host_keeps_path_case():
    assert (
        canonicalize("HTTPS://Example.COM/Some/Path")
        == "https://example.com/Some/Path"
    )


def test_drops_default_ports_only():
    assert canonicalize("http://example.com:80/a") == "http://example.com/a"
    assert (
        canonicalize("https://example.com:443/a")
        == "https://example.com/a"
    )
    assert (
        canonicalize("https://example.com:8443/a")
        == "https://example.com:8443/a"
    )
    assert (
        canonicalize("http://example.com:443/a")
        == "http://example.com:443/a"
    )


def test_drops_fragment():
    assert (
        canonicalize("https://example.com/a#section-2")
        == "https://example.com/a"
    )


def test_strips_tracking_params():
    assert (
        canonicalize(
            "https://example.com/a?utm_source=rss&utm_medium=feed&id=7&fbclid=x&gclid=y&mc_cid=1&mc_eid=2&ocid=3&cmp=4&sc_cid=5"
        )
        == "https://example.com/a?id=7"
    )


def test_wt_mc_id_case_insensitive():
    assert (
        canonicalize("https://learn.microsoft.com/a?WT.mc_id=AZ-MVP&x=1")
        == "https://learn.microsoft.com/a?x=1"
    )
    assert (
        canonicalize("https://learn.microsoft.com/a?wt.mc_id=1&x=1")
        == "https://learn.microsoft.com/a?x=1"
    )
    assert (
        canonicalize("https://learn.microsoft.com/a?Wt.Mc_Id=1&x=1")
        == "https://learn.microsoft.com/a?x=1"
    )
    assert (
        canonicalize("https://example.com/a?UTM_Source=x&b=2")
        == "https://example.com/a?b=2"
    )


def test_only_tracking_params_leaves_no_question_mark():
    assert (
        canonicalize("https://example.com/a?utm_source=x")
        == "https://example.com/a"
    )


def test_sorts_query():
    assert (
        canonicalize("https://example.com/a?b=2&a=1&c=3")
        == "https://example.com/a?a=1&b=2&c=3"
    )
    assert (
        canonicalize("https://example.com/a?a=2&a=1")
        == "https://example.com/a?a=1&a=2"
    )
    assert (
        canonicalize("https://example.com/a?b=1&&a=2")
        == "https://example.com/a?a=2&b=1"
    )


def test_keeps_query_encoding_and_blank_values():
    assert (
        canonicalize("https://example.com/s?q=a%20b&r=c+d")
        == "https://example.com/s?q=a%20b&r=c+d"
    )
    assert (
        canonicalize("https://example.com/a?flag&x=1")
        == "https://example.com/a?flag&x=1"
    )


def test_trailing_slash():
    assert (
        canonicalize("https://example.com/a/b/")
        == "https://example.com/a/b"
    )
    assert (
        canonicalize("https://example.com/a/?x=1")
        == "https://example.com/a?x=1"
    )


def test_root_path_kept():
    assert canonicalize("https://example.com/") == "https://example.com/"
    assert canonicalize("https://example.com") == "https://example.com/"
    assert (
        canonicalize("https://example.com/?b=1")
        == "https://example.com/?b=1"
    )
    assert canonicalize("https://example.com//") == "https://example.com/"


def test_drops_userinfo_and_whitespace():
    assert (
        canonicalize("https://user:pw@example.com/a")
        == "https://example.com/a"
    )
    assert (
        canonicalize("  https://example.com/a \n")
        == "https://example.com/a"
    )


def test_ipv6_host():
    assert (
        canonicalize("http://[::1]:8080/a")
        == "http://[::1]:8080/a"
    )


def test_idempotent():
    for u in ("HTTPS://Example.COM:443/A/b/?z=1&utm_source=x&a=2#f", "https://example.com"):
        assert canonicalize(canonicalize(u)) == canonicalize(u)
    u = "HTTPS://Example.COM:443/A/b/?z=1&utm_source=x&a=2#f"
    assert canonicalize(u) == "https://example.com/A/b?a=2&z=1"


def test_canonicalize_rejects_non_http():
    for u in (
        "javascript:alert(1)",
        "data:text/html,<b>x</b>",
        "ftp://example.com/f",
        "",
        "http://example.com:99999/",
        "http://example.com:abc/",
    ):
        with pytest.raises(ValueError):
            canonicalize(u)


def test_is_http_url_true():
    assert is_http_url("http://example.com")
    assert is_http_url("HTTPS://Example.com/a?b=1")


def test_is_http_url_false():
    for u in (
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<b>x</b>",
        "ftp://example.com/f",
        "//example.com/a",
        "/relative/path",
        "https:///nohost",
        "",
        "mailto:a@example.com",
        "http://example.com:99999/",
    ):
        assert is_http_url(u) is False


def test_host_of():
    assert host_of("https://Sub.Example.com:8443/a") == "sub.example.com"
    assert host_of("javascript:alert(1)") is None
    assert host_of("not a url") is None


def test_host_matches_exact_and_subdomain():
    assert host_matches("example.com", ["example.com"]) is True
    assert (
        host_matches("blog.example.com", ["example.com"]) is True
    )
    assert (
        host_matches("BLOG.Example.COM.", ["example.com"]) is True
    )
    assert (
        host_matches("example.com", ["Example.com"]) is True
    )


def test_host_matches_rejects_lookalikes():
    for host, allowlist in (
        ("evilexample.com", ["example.com"]),
        ("example.com.evil.net", ["example.com"]),
        ("com", ["example.com"]),
        ("example.com", []),
        ("example.com", [""]),
    ):
        assert host_matches(host, allowlist) is False

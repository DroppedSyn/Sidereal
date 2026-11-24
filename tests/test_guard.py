"""Tests for ``sidereal.net.guard`` (plan §6.2 SSRF pitfalls). Written by Claude (security module).

No real DNS: every guard gets a fake resolver (the autouse ``no_network`` fixture would refuse).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from sidereal.net.guard import CheckedUrl, UrlBlocked, UrlGuard

PUBLIC_V4 = "93.184.215.14"
PUBLIC_V6 = "2606:4700::6810:84e5"


class FakeResolver:
    """Maps host names to address lists; records every lookup."""

    def __init__(self, table: dict[str, Sequence[str]] | None = None) -> None:
        self.table = dict(table or {})
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        if host not in self.table:
            raise OSError("name not known")
        return self.table[host]


def make_guard(table: dict[str, Sequence[str]] | None = None, **kwargs: object) -> UrlGuard:
    resolver = FakeResolver({"example.com": [PUBLIC_V4], **(table or {})})
    return UrlGuard(resolver=resolver, **kwargs)  # type: ignore[arg-type]


async def blocked(guard: UrlGuard, url: str, **kwargs: object) -> str:
    with pytest.raises(UrlBlocked) as info:
        await guard.check(url, **kwargs)  # type: ignore[arg-type]
    return info.value.reason


async def test_public_host_allowed() -> None:
    guard = make_guard({"www.example.com": [PUBLIC_V4, PUBLIC_V6]})
    checked = await guard.check("https://WWW.Example.com./path?q=1")
    assert checked == CheckedUrl(
        url="https://WWW.Example.com./path?q=1", host="www.example.com", port=443,
        addresses=(PUBLIC_V4, PUBLIC_V6),
    )
    assert (await guard.check("http://example.com/")).port == 80


async def test_redirect_to_private_blocked() -> None:
    """The fetcher re-checks every redirect hop; a hop to a private target must be refused."""
    guard = make_guard({"internal.example.net": ["10.0.0.5"]})
    await guard.check("https://example.com/start")  # first URL is fine
    for location in ("http://169.254.169.254/latest/meta-data/", "http://internal.example.net/",
                     "http://localhost/admin", "http://[::1]/"):
        await blocked(guard, location)


async def test_hostname_resolving_to_127_blocked() -> None:
    guard = make_guard({"evil.example": ["127.0.0.1"]})
    assert "loopback" in await blocked(guard, "https://evil.example/")


async def test_ipv4_mapped_ipv6_blocked() -> None:
    guard = make_guard({"mapped.example": ["::ffff:127.0.0.1"], "m2.example": ["::ffff:10.1.2.3"]})
    reason = await blocked(guard, "https://mapped.example/")
    assert "embedded IPv4 127.0.0.1" in reason  # unwrapped, not left to the stdlib's handling
    assert "embedded IPv4 10.1.2.3" in await blocked(guard, "https://m2.example/")
    assert "embedded IPv4 127.0.0.1" in await blocked(guard, "http://[::ffff:7f00:1]/")


async def test_other_embedded_ipv4_forms_blocked() -> None:
    guard = make_guard({
        "sixtofour.example": ["2002:7f00:1::1"],
        "nat64.example": ["64:ff9b::a00:1"],
        "compat.example": ["::127.0.0.1"],
    })
    for host in ("sixtofour.example", "nat64.example", "compat.example"):
        assert "embedded IPv4" in await blocked(guard, f"https://{host}/")


@pytest.mark.parametrize("url", [
    "http://2130706433/", "http://0x7f000001/", "http://0x7f.1/", "http://017700000001/",
    "http://127.1/", "http://0177.0.0.1/", "http://1.2.3.4.5/", "http://8.8.8.010/",
])
async def test_decimal_ip_host_blocked(url: str) -> None:
    guard = make_guard()
    await blocked(guard, url)
    assert guard._resolver.calls == []  # type: ignore[attr-defined]  # refused before any lookup


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0",
    "100.64.0.1", "224.0.0.1", "255.255.255.255", "240.0.0.1", "198.18.0.1", "::1", "::",
    "fe80::1", "fc00::1", "ff02::1", "2001:db8::1",
])
async def test_non_public_addresses_blocked(addr: str) -> None:
    guard = make_guard({"host.example": [addr]})
    await blocked(guard, "https://host.example/")
    literal = f"[{addr}]" if ":" in addr else addr
    await blocked(guard, f"https://{literal}/")


async def test_public_ip_literals_allowed() -> None:
    guard = make_guard()
    assert (await guard.check("https://8.8.8.8/")).addresses == ("8.8.8.8",)
    assert (await guard.check(f"https://[{PUBLIC_V6}]/")).host == PUBLIC_V6


async def test_any_bad_address_blocks() -> None:
    guard = make_guard({"multi.example": [PUBLIC_V4, PUBLIC_V6, "192.168.0.10"]})
    assert "192.168.0.10" in await blocked(guard, "https://multi.example/")
    guard = make_guard({"multi.example": ["10.0.0.1", PUBLIC_V4]})
    await blocked(guard, "https://multi.example/")


@pytest.mark.parametrize("url", [
    "ftp://example.com/", "file:///etc/passwd", "javascript:alert(1)", "data:text/html,x",
    "gopher://example.com/", "//example.com/", "example.com", "", "http:///path", "https://",
])
async def test_bad_scheme_or_missing_host_blocked(url: str) -> None:
    await blocked(make_guard(), url)


@pytest.mark.parametrize("url", [
    "https://user:pass@example.com/", "https://user@example.com/",
    "https://example.com@127.0.0.1/", "https://@example.com/",
])
async def test_userinfo_blocked(url: str) -> None:
    await blocked(make_guard(), url)


@pytest.mark.parametrize("url", [
    "https://example.com /", "https://exa mple.com/", "https://example.com\\@evil.example/",
    "https://example.com/\npath", "https://example.com/\x00", "\thttps://example.com/",
])
async def test_whitespace_control_backslash_blocked(url: str) -> None:
    await blocked(make_guard(), url)


async def test_ports() -> None:
    guard = make_guard()
    assert "8080" in await blocked(guard, "http://example.com:8080/")
    await blocked(guard, "https://example.com:22/")
    await blocked(guard, "https://example.com:99999/")
    await blocked(guard, "https://example.com:abc/")
    assert (await guard.check("https://example.com:443/")).port == 443
    assert (await guard.check("http://example.com:443/")).port == 443
    assert (await make_guard(allowed_ports=(80, 443, 8443)).check(
        "https://example.com:8443/")).port == 8443


async def test_allow_hosts() -> None:
    guard = make_guard({
        "learn.microsoft.com": [PUBLIC_V4], "microsoft.com": [PUBLIC_V4],
        "evilmicrosoft.com": [PUBLIC_V4], "microsoft.com.evil.example": [PUBLIC_V4],
        "xn--mnchen-3ya.de": [PUBLIC_V4],
    })
    allow = ["Microsoft.COM.", "münchen.de"]
    assert (await guard.check("https://learn.microsoft.com/x", allow_hosts=allow)).host == (
        "learn.microsoft.com")
    await guard.check("https://microsoft.com/", allow_hosts=allow)
    await guard.check("https://MÜNCHEN.de/", allow_hosts=allow)
    await guard.check("https://xn--mnchen-3ya.de/", allow_hosts=allow)
    assert "allowed hosts" in await blocked(guard, "https://evilmicrosoft.com/", allow_hosts=allow)
    await blocked(guard, "https://microsoft.com.evil.example/", allow_hosts=allow)
    await blocked(guard, "https://microsoft.com/", allow_hosts=[])  # empty list allows nothing


async def test_allow_hosts_still_checks_addresses() -> None:
    guard = make_guard({"intranet.corp.example": ["10.1.1.1"]})
    await blocked(guard, "https://intranet.corp.example/", allow_hosts=["corp.example"])


async def test_resolution_failures_blocked() -> None:
    guard = make_guard({"empty.example": [], "junk.example": ["not-an-ip"]})
    assert "cannot resolve" in await blocked(guard, "https://unknown.example/")
    assert "no addresses" in await blocked(guard, "https://empty.example/")
    await blocked(guard, "https://junk.example/")


async def test_invalid_host_names_blocked() -> None:
    guard = make_guard()
    for url in ("https://a..b/", "https://ex%61mple.com/", "https://" + "a" * 64 + ".com/",
                "https://[::1%25eth0]/", "https://[not-ipv6]/"):
        await blocked(guard, url)


async def test_allow_private_for_lan_notifiers() -> None:
    guard = make_guard({"nas.lan": ["192.168.1.20"], "zero.lan": ["0.0.0.0"]},
                       allow_private=True, allowed_ports=(80, 443, 8123))
    assert (await guard.check("http://nas.lan:8123/hook")).addresses == ("192.168.1.20",)
    await guard.check("http://127.0.0.1/")
    await blocked(guard, "http://zero.lan/")
    await blocked(guard, "http://224.0.0.1/")
    await blocked(guard, "http://2130706433/")
    await blocked(guard, "ftp://nas.lan/")


async def test_default_resolver_is_used_and_network_is_refused() -> None:
    # The default resolver goes through the loop's getaddrinfo, which the autouse fixture
    # replaces with one that raises RuntimeError; either way nothing is fetched.
    guard = UrlGuard()
    with pytest.raises((UrlBlocked, RuntimeError)):
        await guard.check("https://example.com/")

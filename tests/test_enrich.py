"""Tests for `pipeline.enrich` — article text enrichment.

Every test exercises exactly one behaviour.  Use helpers at the top to avoid
inline repeats.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from sidereal.pipeline import enrich
from sidereal.pipeline.enrich import (
    ACCEPT,
    ARTICLE_MAX_BYTES,
    ERROR_MAX_CHARS,
    MAX_CHARS,
    ArticleTarget,
    allowlist_for,
    charset_of,
    enrich_many,
    enrich_one,
    extract_text,
)
from sidereal.textclean import truncate
from tests.adapter_helpers import make_fetcher

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PAGES = Path(__file__).parent / "fixtures" / "pages"
BLEEP = (PAGES / "bleepingcomputer-rackspace-spot.html").read_bytes()
TC = (PAGES / "tc-azure-networking-route-maps.html").read_bytes()
HTML = "text/html; charset=utf-8"
LATIN1 = (
    "<html><head><title>T</title></head><body><article>"
    + "<p>Café résumé naïve paragraph text that is long enough to count as content.</p>" * 5
    + "</article></body></html>"
).encode("latin-1")


def target(
    url: str = "https://news.example.com/a",
    hosts: tuple[str, ...] = ("news.example.com",),
    item_id: int = 1,
) -> ArticleTarget:
    return ArticleTarget(item_id=item_id, url=url, source_key="s", allow_hosts=tuple(hosts))


async def split_resolver(host: str, port: int) -> Sequence[str]:
    """`internal.*` resolves to a private address, everything else to public."""
    return ["10.0.0.5"] if host.startswith("internal.") else ["93.184.215.14"]


def routed_fetcher(
    routes: dict[str, tuple[int, bytes, dict[str, str]]],
    *,
    per_host_concurrency: int = 2,
) -> tuple[Fetcher, list[str]]:
    """`routes`: `{url: (status, body, headers)}`; unknown URL → 404.
    Returns ``(fetcher, seen_urls)``."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        status, body, headers = routes.get(str(request.url), (404, b"", {}))
        return httpx.Response(status, content=body, headers=headers)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        Fetcher(
            client=client,
            guard=UrlGuard(resolver=split_resolver),
            per_host_concurrency=per_host_concurrency,
        ),
        seen,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_ok_bleepingcomputer_page() -> None:
    """1. BleepingComputer page: status ok, expected text, no <, within limit."""
    fetcher, _ = make_fetcher(BLEEP, content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert result.error is None
    assert result.text is not None
    assert "Rackspace Spot is a cloud platform" in result.text
    assert "<" not in result.text
    assert len(result.text) <= 20000
    await fetcher.aclose()


async def test_ok_techcommunity_page() -> None:
    """2. TechCommunity page: expected text, no <."""
    fetcher, _ = make_fetcher(TC, content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert result.error is None
    assert result.text is not None
    assert "Azure Route Server uses Border Gateway Protocol" in result.text
    assert "<" not in result.text
    await fetcher.aclose()


async def test_truncation() -> None:
    """3. Truncation: max_chars=500 → len <= 500, ends with …."""
    fetcher, _ = make_fetcher(TC, content_type=HTML)
    result = await enrich_one(target(), fetcher, max_chars=500)
    assert result.status == "ok"
    assert result.text is not None
    assert len(result.text) <= 500
    assert result.text.endswith("…")
    await fetcher.aclose()


async def test_host_not_allowed() -> None:
    """4. Host not in allowlist → blocked, no request."""
    fetcher, seen = routed_fetcher({})
    result = await enrich_one(target(url="https://evil.example.org/x"), fetcher)
    assert result.status == "blocked"
    assert result.error is not None
    assert result.error.startswith("UrlBlocked: ")
    assert seen == []
    await fetcher.aclose()


async def test_redirect_to_private_ip() -> None:
    """5. Redirect to private IP → blocked, seen only the first URL."""
    routes = {
        "https://news.example.com/a": (
            302, b"", {"location": "https://internal.news.example.com/admin"}
        ),
    }
    fetcher, seen = routed_fetcher(routes)
    result = await enrich_one(target(), fetcher)
    assert result.status == "blocked"
    assert result.error is not None
    assert result.error.startswith("UrlBlocked: ")
    assert seen == ["https://news.example.com/a"]
    await fetcher.aclose()


async def test_404_with_body() -> None:
    """6. 404 with BLEEP as body → failed, exact error."""
    fetcher, _ = make_fetcher(BLEEP, content_type=HTML, status=404)
    result = await enrich_one(target(), fetcher)
    assert result.status == "failed"
    assert result.error == "FetchHTTPError: HTTP 404"
    await fetcher.aclose()


async def test_oversize() -> None:
    """7. Oversize: BLEEP with max_bytes=1000 → failed, FetchTooLarge, no page content."""
    fetcher, _ = make_fetcher(BLEEP, content_type=HTML)
    result = await enrich_one(target(), fetcher, max_bytes=1000)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.startswith("FetchTooLarge: ")
    assert "Rackspace" not in result.error
    await fetcher.aclose()


async def test_non_html_content_type() -> None:
    """8. content_type=application/pdf → failed, NotHtml."""
    fetcher, _ = make_fetcher(BLEEP, content_type="application/pdf")
    result = await enrich_one(target(), fetcher)
    assert result.status == "failed"
    assert result.error == "NotHtml: application/pdf"
    await fetcher.aclose()


@pytest.mark.parametrize(
    "body", [b"", b"\x00\x01\x02", b"<html><body><script>alert(1)</script></body></html>"]
)
async def test_empty_garbage_extract(body: bytes) -> None:
    """9. Empty / garbage HTML → failed, NoText, text is None."""
    fetcher, _ = make_fetcher(body, content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "failed"
    assert result.error == "NoText: no article text extracted"
    assert result.text is None
    await fetcher.aclose()


async def test_empty_allowlist() -> None:
    """10. Empty allowlist → skipped, no request."""
    fetcher, seen = make_fetcher(BLEEP, content_type=HTML)
    result = await enrich_one(target(hosts=()), fetcher)
    assert result.status == "skipped"
    assert result.error is not None
    assert result.error.startswith("NoAllowlist")
    assert seen == []
    await fetcher.aclose()


async def test_latin1_charset() -> None:
    """11. Latin-1 body with charset → ok, decoded text, no replacement char."""
    fetcher, _ = make_fetcher(LATIN1, content_type="text/html; charset=iso-8859-1")
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert result.error is None
    assert result.text is not None
    assert "Café résumé naïve" in result.text
    assert "�" not in result.text
    await fetcher.aclose()


def test_extract_text_directly() -> None:
    """12. extract_text directly: latin-1 with no-such-codec -> str
    (utf-8 fallback); empty -> None."""
    result = extract_text(LATIN1, charset="no-such-codec")
    assert isinstance(result, str)
    assert extract_text(b"") is None


def test_charset_of() -> None:
    """13. charset_of: various content-type strings."""
    assert charset_of("text/html; charset=ISO-8859-1") == "iso-8859-1"
    assert charset_of('text/html; Charset="UTF-8"') == "utf-8"
    assert charset_of("text/html") is None
    assert charset_of("") is None


async def test_concurrency_limit() -> None:
    """14. concurrency: 8 targets, per_host_concurrency=10, concurrency=3 → max in-flight == 3."""
    max_in_flight = 0
    current_in_flight = 0

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal max_in_flight, current_in_flight
        current_in_flight += 1
        max_in_flight = max(max_in_flight, current_in_flight)
        await asyncio.sleep(0.02)
        current_in_flight -= 1
        return httpx.Response(200, content=TC, headers={"content-type": HTML})

    base_url = "https://news.example.com"
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return await slow_handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(
        client=client,
        guard=UrlGuard(resolver=split_resolver),
        per_host_concurrency=10,
    )

    targets = [
        ArticleTarget(
            item_id=i,
            url=f"{base_url}/a{i}",
            source_key="s",
            allow_hosts=("news.example.com",),
        )
        for i in range(8)
    ]
    results = await enrich_many(targets, fetcher, concurrency=3)
    assert max_in_flight == 3
    assert all(r.status == "ok" for r in results)
    await fetcher.aclose()


async def test_deadline() -> None:
    """15. deadline: 5 targets, concurrency=1, deadline=lambda: len(seen) >= 2 →
    first 2 ok, rest skipped."""
    fetcher, seen = make_fetcher(TC, content_type=HTML)
    targets = [
        ArticleTarget(
            item_id=i,
            url=f"https://news.example.com/a{i}",
            source_key="s",
            allow_hosts=("news.example.com",),
        )
        for i in range(1, 6)
    ]
    results = await enrich_many(
        targets, fetcher, concurrency=1, deadline=lambda: len(seen) >= 2
    )
    statuses = [r.status for r in results]
    item_ids = [r.item_id for r in results]
    assert statuses == ["ok", "ok", "skipped", "skipped", "skipped"]
    assert item_ids == [1, 2, 3, 4, 5]
    for r in results[2:]:
        assert r.error == "Deadline: run time budget reached"
    assert len(seen) == 2
    await fetcher.aclose()


async def test_concurrency_zero() -> None:
    """16. concurrency=0 → ValueError."""
    fetcher, _ = make_fetcher(BLEEP, content_type=HTML)
    with pytest.raises(ValueError):
        await enrich_many([target()], fetcher, concurrency=0)
    await fetcher.aclose()


def test_allowlist_for() -> None:
    """17. allowlist_for: various inputs."""
    assert allowlist_for({}) == ()
    assert allowlist_for({"article_hosts": []}) == ()
    assert allowlist_for(
        {
            "article_hosts": [
                " Azure.Microsoft.com. ",
                "learn.microsoft.com",
                "azure.microsoft.com",
                "",
                3,
            ]
        }
    ) == ("azure.microsoft.com", "learn.microsoft.com")
    with pytest.raises(ValueError, match="article_hosts"):
        allowlist_for({"article_hosts": "x.com"})


async def test_subdomain_allowed() -> None:
    """18. Subdomain: blog.news.example.com with hosts (news.example.com,) → ok."""
    fetcher, _ = make_fetcher(TC, content_type=HTML)
    result = await enrich_one(
        target(
            url="https://blog.news.example.com/a",
            hosts=("news.example.com",),
        ),
        fetcher,
    )
    assert result.status == "ok"
    assert result.text is not None
    await fetcher.aclose()


# ---------------------------------------------------------------------------
# Review additions (r60)
# ---------------------------------------------------------------------------

BIG = (
    "<html><head><title>T</title></head><body><article>"
    + "".join(
        f"<p>Paragraph {i} of a very long article body with plenty of ordinary words.</p>"
        for i in range(600)
    )
    + "</article></body></html>"
).encode()


def test_constants() -> None:
    assert ARTICLE_MAX_BYTES == 2_000_000
    assert MAX_CHARS == 20_000
    assert ERROR_MAX_CHARS == 200


async def test_request_sends_accept_header() -> None:
    fetcher, seen = make_fetcher(TC, content_type=HTML)
    await enrich_one(target(), fetcher)
    assert [r.headers["accept"] for r in seen] == [ACCEPT]
    await fetcher.aclose()


async def test_default_max_bytes_is_two_megabytes() -> None:
    """No max_bytes given: a body one byte over 2 MB is refused (the Fetcher default is 8 MB)."""
    fetcher, _ = make_fetcher(b"x" * (ARTICLE_MAX_BYTES + 1), content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.startswith("FetchTooLarge: ")
    await fetcher.aclose()


async def test_default_max_chars_truncates() -> None:
    fetcher, _ = make_fetcher(BIG, content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert result.text is not None
    assert 19_000 < len(result.text) <= MAX_CHARS
    assert result.text.endswith("…")
    await fetcher.aclose()


@pytest.mark.parametrize("delta", [1, 0, 300])
def test_truncation_exact(delta: int) -> None:
    full = extract_text(TC, max_chars=10**9)
    assert full is not None
    n = len(full) - delta
    assert extract_text(TC, max_chars=n) == truncate(full, n)


async def test_extracted_text_goes_through_to_text() -> None:
    """Escaped markup in the article comes back from trafilatura as real tags; to_text drops it."""
    para = (
        "<p>Paragraph text that is long enough to count as article content "
        "&lt;script&gt;alert(1)&lt;/script&gt; and more words after it.</p>"
    )
    body = ("<html><body><article>" + para * 5 + "</article></body></html>").encode()
    fetcher, _ = make_fetcher(body, content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert result.text is not None
    assert "and more words after it" in result.text
    assert "<" not in result.text
    assert "alert" not in result.text
    await fetcher.aclose()


@pytest.mark.parametrize("charset", ["no-such-codec", "idna", "undefined", "hex", "zlib", '""'])
async def test_unusable_charset_falls_back_to_utf8(charset: str) -> None:
    fetcher, _ = make_fetcher(TC, content_type=f"text/html; charset={charset}")
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert result.text is not None
    assert "Azure Route Server uses Border Gateway Protocol" in result.text
    await fetcher.aclose()


async def test_xhtml_accepted() -> None:
    fetcher, _ = make_fetcher(TC, content_type="Application/XHTML+XML; charset=utf-8")
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    await fetcher.aclose()


async def test_missing_content_type_is_not_html() -> None:
    fetcher, _ = make_fetcher(TC, content_type="")
    result = await enrich_one(target(), fetcher)
    assert result.status == "failed"
    assert result.error == "NotHtml: (none)"
    await fetcher.aclose()


async def test_error_cut_to_200_chars() -> None:
    fetcher, _ = make_fetcher(TC, content_type="application/" + "x" * 400)
    result = await enrich_one(target(), fetcher)
    assert result.status == "failed"
    assert result.error == ("NotHtml: application/" + "x" * 400)[:ERROR_MAX_CHARS]
    await fetcher.aclose()


async def test_blocked_error_cut_to_200_chars() -> None:
    host = ".".join(["a" * 60] * 3) + ".example.org"
    fetcher, seen = make_fetcher(TC, content_type=HTML)
    result = await enrich_one(target(url=f"https://{host}/x"), fetcher)
    assert result.status == "blocked"
    assert result.error is not None
    assert result.error.startswith("UrlBlocked: host ")
    assert len(result.error) == ERROR_MAX_CHARS
    assert seen == []
    await fetcher.aclose()


async def test_redirect_to_other_public_host_blocked() -> None:
    """A public but unlisted redirect target is blocked too: allow_hosts reaches every hop."""
    routes = {
        "https://news.example.com/a": (302, b"", {"location": "https://tracker.example.net/x"}),
        "https://tracker.example.net/x": (200, TC, {"content-type": HTML}),
    }
    fetcher, seen = routed_fetcher(routes)
    result = await enrich_one(target(), fetcher)
    assert result.status == "blocked"
    assert seen == ["https://news.example.com/a"]
    await fetcher.aclose()


async def test_uppercase_allowlist_entry_matches() -> None:
    hosts = allowlist_for({"article_hosts": ["NEWS.Example.COM"]})
    fetcher, _ = make_fetcher(TC, content_type=HTML)
    result = await enrich_one(target(url="https://News.Example.com/a", hosts=hosts), fetcher)
    assert result.status == "ok"
    await fetcher.aclose()


async def test_extraction_runs_in_a_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    threads: list[int] = []
    real = enrich.extract_text

    def spy(*args: object, **kwargs: object) -> str | None:
        threads.append(threading.get_ident())
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(enrich, "extract_text", spy)
    fetcher, _ = make_fetcher(TC, content_type=HTML)
    result = await enrich_one(target(), fetcher)
    assert result.status == "ok"
    assert len(threads) == 1
    assert threads[0] != threading.get_ident()
    await fetcher.aclose()


async def test_many_empty_allowlist_and_order() -> None:
    fetcher, seen = make_fetcher(TC, content_type=HTML)
    targets = [target(item_id=1), target(item_id=2, hosts=()), target(item_id=3)]
    results = await enrich_many(targets, fetcher)
    assert [(r.item_id, r.status) for r in results] == [(1, "ok"), (2, "skipped"), (3, "ok")]
    assert len(seen) == 2
    await fetcher.aclose()

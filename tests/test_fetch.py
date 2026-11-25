from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx
import pytest

import sidereal
from sidereal.net.fetch import (
    Fetcher,
    FetchError,
    FetchHTTPError,
    FetchResponse,
    FetchTooLarge,
    UrlBlocked,
)
from sidereal.net.guard import UrlGuard

PUBLIC = "93.184.215.14"
HOSTS = {
    "feeds.example.com": [PUBLIC],
    "cdn.example.net": [PUBLIC],
    "internal.example.com": ["127.0.0.1"],
}

async def fake_resolver(host: str, port: int) -> Sequence[str]:
    if host not in HOSTS:
        raise OSError("name not known")
    return HOSTS[host]


class Recorder:
    """Records sleep() calls instead of sleeping."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make(handler, **kw) -> tuple[Fetcher, list[httpx.Request], Recorder]:
    """Fetcher over a MockTransport; returns (fetcher, list of requests sent, sleep recorder)."""
    seen: list[httpx.Request] = []

    async def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result = handler(request)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    sleep = Recorder()
    client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
    fetcher = Fetcher(client=client, guard=UrlGuard(resolver=fake_resolver), sleep=sleep, **kw)
    return fetcher, seen, sleep


# -- 1. test_get_200_returns_body_and_headers --
async def test_get_200_returns_body_and_headers() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<rss/>",
            headers={
                "content-type": "application/rss+xml",
                "etag": '"abc"',
                "last-modified": "Tue, 24 Nov 2026 10:00:00 GMT",
            },
        )

    fetcher, seen, _ = make(handler)
    resp = await fetcher.get(F)
    expected = FetchResponse(
        url=F,
        status=200,
        content=b"<rss/>",
        content_type="application/rss+xml",
        etag='"abc"',
        last_modified="Tue, 24 Nov 2026 10:00:00 GMT",
        not_modified=False,
    )
    assert resp == expected
    assert len(seen) == 1
    await fetcher.aclose()


# -- 2. test_conditional_headers_sent_and_304 --
async def test_conditional_headers_sent_and_304() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    fetcher, seen, _ = make(handler)
    resp = await fetcher.get(
        F,
        etag='"abc"',
        last_modified="Tue, 24 Nov 2026 10:00:00 GMT",
    )
    assert seen[0].headers["If-None-Match"] == '"abc"'
    assert seen[0].headers["If-Modified-Since"] == "Tue, 24 Nov 2026 10:00:00 GMT"
    assert resp.not_modified is True
    assert resp.status == 304
    assert resp.content == b""
    assert resp.etag == '"abc"'
    await fetcher.aclose()


# -- 3. test_no_conditional_headers_by_default --
async def test_no_conditional_headers_by_default() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    fetcher, seen, _ = make(handler)
    await fetcher.get(F)
    assert "If-None-Match" not in seen[0].headers
    assert "If-Modified-Since" not in seen[0].headers
    await fetcher.aclose()


# -- 4. test_user_agent_exact --
async def test_user_agent_exact() -> None:
    F = "https://feeds.example.com/feed"
    ua = f"Sidereal/{sidereal.__version__} (+personal news reader)"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    fetcher, seen, _ = make(handler)
    await fetcher.get(F, accept="application/json")
    assert seen[0].headers["User-Agent"] == ua
    assert seen[0].headers["Accept"] == "application/json"
    await fetcher.aclose()


# -- 5. test_size_cap_content_length --
async def test_size_cap_content_length() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 11)

    fetcher, seen, _ = make(handler, max_bytes=10)
    with pytest.raises(FetchTooLarge):
        await fetcher.get(F)
    assert len(seen) == 1
    await fetcher.aclose()


# -- 6. test_size_cap_streaming_without_length --
async def test_size_cap_streaming_without_length() -> None:
    F = "https://feeds.example.com/feed"

    async def gen():
        for _ in range(3):
            yield b"y" * 10

    fetcher, seen, _ = make(lambda _r: httpx.Response(200, content=gen()), max_bytes=25)
    with pytest.raises(FetchTooLarge):
        await fetcher.get(F)
    await fetcher.aclose()


# -- 7. test_size_exactly_at_cap_ok --
async def test_size_exactly_at_cap_ok() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 10)

    fetcher, seen, _ = make(handler, max_bytes=10)
    resp = await fetcher.get(F)
    assert resp.content == b"x" * 10
    await fetcher.aclose()


# -- 8. test_retry_503_then_success --
async def test_retry_503_then_success() -> None:
    F = "https://feeds.example.com/feed"
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok")

    fetcher, seen, sleep = make(handler)
    resp = await fetcher.get(F)
    assert resp.content == b"ok"
    assert len(seen) == 2
    assert sleep.calls == [2.0]
    await fetcher.aclose()


# -- 9. test_gives_up_after_two_retries_on_502 --
async def test_gives_up_after_two_retries_on_502() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502)

    fetcher, seen, sleep = make(handler)
    with pytest.raises(FetchHTTPError) as ei:
        await fetcher.get(F)
    assert ei.value.status == 502
    assert len(seen) == 3
    assert sleep.calls == [2.0, 6.0]
    await fetcher.aclose()


# -- 10. test_connect_error_retried --
async def test_connect_error_retried() -> None:
    F = "https://feeds.example.com/feed"
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, content=b"ok")

    fetcher, seen, sleep = make(handler)
    resp = await fetcher.get(F)
    assert resp.content == b"ok"
    assert sleep.calls == [2.0, 6.0]
    assert len(seen) == 3
    await fetcher.aclose()


# -- 10b. test_connect_error_gives_up --
async def test_connect_error_gives_up() -> None:
    F = "https://feeds.example.com/feed"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    fetcher, seen, sleep = make(handler)
    with pytest.raises(FetchError) as exc_info:
        await fetcher.get(F)
    exc = exc_info.value
    assert not isinstance(exc, FetchHTTPError)
    await fetcher.aclose()


# -- 11. test_404_not_retried --
async def test_404_not_retried() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    fetcher, seen, sleep = make(handler)
    with pytest.raises(FetchHTTPError) as ei:
        await fetcher.get(F)
    assert ei.value.status == 404
    assert len(seen) == 1
    assert sleep.calls == []
    await fetcher.aclose()


# -- 12. test_429_retry_after_honoured_once --
async def test_429_retry_after_honoured_once() -> None:
    F = "https://feeds.example.com/feed"
    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "5"})
        return httpx.Response(200, content=b"ok")

    fetcher, seen, sleep = make(handler)
    resp = await fetcher.get(F)
    assert resp.content == b"ok"
    assert len(seen) == 2
    assert sleep.calls == [5.0]
    await fetcher.aclose()


# -- 13. test_429_retry_after_too_long_fails --
async def test_429_retry_after_too_long_fails() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"})

    fetcher, seen, sleep = make(handler)
    with pytest.raises(FetchHTTPError) as ei:
        await fetcher.get(F)
    assert ei.value.status == 429
    assert sleep.calls == []
    assert len(seen) == 1
    await fetcher.aclose()


# -- 14. test_429_twice_fails --
async def test_429_twice_fails() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "1"})

    fetcher, seen, sleep = make(handler)
    with pytest.raises(FetchHTTPError) as ei:
        await fetcher.get(F)
    assert ei.value.status == 429
    assert len(seen) == 2
    assert sleep.calls == [1.0]
    await fetcher.aclose()


# -- 15. test_redirects_followed --
async def test_redirects_followed() -> None:
    F = "https://feeds.example.com/feed"
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        path = request.url.path
        if path == "/feed" and call_count == 1:
            return httpx.Response(302, headers={"Location": "/moved"})
        if path == "/moved":
            return httpx.Response(301, headers={"Location": "https://cdn.example.net/final"})
        return httpx.Response(200, content=b"done")

    fetcher, seen, _ = make(handler)
    resp = await fetcher.get(F)
    assert resp.url == "https://cdn.example.net/final"
    assert resp.content == b"done"
    urls = [str(r.url) for r in seen]
    assert urls == [
        "https://feeds.example.com/feed",
        "https://feeds.example.com/moved",
        "https://cdn.example.net/final",
    ]
    await fetcher.aclose()


# -- 16. test_redirect_to_private_blocked --
async def test_redirect_to_private_blocked() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/"})

    fetcher, seen, sleep = make(handler)
    with pytest.raises(UrlBlocked):
        await fetcher.get(F)
    urls = [str(r.url) for r in seen]
    assert urls == [F]
    assert sleep.calls == []  # UrlBlocked is never retried
    await fetcher.aclose()


# -- 17. test_redirect_to_host_resolving_private_blocked --
async def test_redirect_to_host_resolving_private_blocked() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://internal.example.com/x"})

    fetcher, seen, _ = make(handler)
    with pytest.raises(UrlBlocked):
        await fetcher.get(F)
    assert len(seen) == 1
    await fetcher.aclose()


# -- 18. test_redirect_loop_limit --
async def test_redirect_loop_limit() -> None:
    F = "https://feeds.example.com/feed"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/feed"})

    fetcher, seen, _ = make(handler)
    with pytest.raises(FetchError) as ei:
        await fetcher.get(F)
    assert not isinstance(ei.value, UrlBlocked)
    assert "too many redirects" in str(ei.value)
    assert len(seen) == 6
    await fetcher.aclose()


# -- 19. test_blocked_initial_url_makes_no_request --
async def test_blocked_initial_url_makes_no_request() -> None:
    # localhost blocked
    fetcher, seen, _ = make(lambda r: httpx.Response(200))
    with pytest.raises(UrlBlocked):
        await fetcher.get("http://127.0.0.1/feed")
    assert seen == []
    await fetcher.aclose()

    # ftp scheme blocked
    fetcher2, seen2, _ = make(lambda r: httpx.Response(200))
    with pytest.raises(UrlBlocked):
        await fetcher2.get("ftp://feeds.example.com/x")
    assert seen2 == []
    await fetcher2.aclose()


# -- 20. test_allow_hosts_enforced_on_redirect --
async def test_allow_hosts_enforced_on_redirect() -> None:
    F = "https://feeds.example.com/feed"

    def redirect_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://cdn.example.net/x"})

    fetcher, seen, _ = make(redirect_handler)
    with pytest.raises(UrlBlocked):
        await fetcher.get(F, allow_hosts=["example.com"])
    assert len(seen) == 1
    await fetcher.aclose()

    # subdomain of example.com is allowed
    fetcher2, seen2, _ = make(lambda r: httpx.Response(200, content=b"ok"))
    resp = await fetcher2.get(F, allow_hosts=["example.com"])
    assert resp.content == b"ok"
    assert len(seen2) == 1
    await fetcher2.aclose()


# -- 21. test_per_host_concurrency_limit --
async def test_per_host_concurrency_limit() -> None:
    F = "https://feeds.example.com/feed"
    state: dict[str, int] = {"now": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.02)
        state["now"] -= 1
        return httpx.Response(200, content=b"ok")

    fetcher, seen, _ = make(handler)
    await asyncio.gather(*(fetcher.get(F) for _ in range(6)))
    assert state["max"] == 2
    assert len(seen) == 6
    await fetcher.aclose()

    state.update(now=0, max=0)
    fetcher, seen, _ = make(handler, per_host_concurrency=1)
    await asyncio.gather(*(fetcher.get(F) for _ in range(3)))
    assert state["max"] == 1
    await fetcher.aclose()

    # The limit is per host: two hosts at limit 1 run side by side.
    state.update(now=0, max=0)
    fetcher, seen, _ = make(handler, per_host_concurrency=1)
    await asyncio.gather(fetcher.get(F), fetcher.get("https://cdn.example.net/x"))
    assert state["max"] == 2
    await fetcher.aclose()


# -- 22. test_aclose_owned_client --
async def test_aclose_owned_client() -> None:
    fetcher = Fetcher(guard=UrlGuard(resolver=fake_resolver))
    await fetcher.aclose()
    # should not raise


async def test_owned_client_has_timeout_and_no_redirects() -> None:
    fetcher = Fetcher(guard=UrlGuard(resolver=fake_resolver), timeout_s=7.0)
    assert fetcher._client.timeout == httpx.Timeout(7.0)
    assert fetcher._client.follow_redirects is False
    await fetcher.aclose()


async def test_redirect_without_location_fails() -> None:
    fetcher, seen, _ = make(lambda _r: httpx.Response(302))
    with pytest.raises(FetchError, match="without Location"):
        await fetcher.get("https://feeds.example.com/feed")
    assert len(seen) == 1
    await fetcher.aclose()


async def test_allow_hosts_generator_checked_on_every_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(302, headers={"Location": "https://cdn.example.net/x"})
        return httpx.Response(200, content=b"ok")

    fetcher, seen, _ = make(handler)
    resp = await fetcher.get(
        "https://feeds.example.com/feed", allow_hosts=(h for h in ["example.com", "example.net"])
    )
    assert resp.content == b"ok"
    assert len(seen) == 2
    await fetcher.aclose()


async def test_error_body_not_read_or_capped() -> None:
    fetcher, _, _ = make(lambda _r: httpx.Response(404, content=b"z" * 100), max_bytes=10)
    with pytest.raises(FetchHTTPError) as ei:
        await fetcher.get("https://feeds.example.com/feed")
    assert ei.value.status == 404
    await fetcher.aclose()


async def test_read_timeout_is_fetch_error_not_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    fetcher, seen, sleep = make(handler)
    with pytest.raises(FetchError) as ei:
        await fetcher.get("https://feeds.example.com/feed")
    assert isinstance(ei.value.__cause__, httpx.ReadTimeout)
    assert len(seen) == 1
    assert sleep.calls == []
    await fetcher.aclose()


@pytest.mark.parametrize("value", [None, "Wed, 25 Nov 2026 10:00:00 GMT", "-1", "nan"])
async def test_429_unusable_retry_after_fails_without_sleep(value: str | None) -> None:
    headers = {} if value is None else {"Retry-After": value}
    fetcher, seen, sleep = make(lambda _r: httpx.Response(429, headers=headers))
    with pytest.raises(FetchHTTPError):
        await fetcher.get("https://feeds.example.com/feed")
    assert len(seen) == 1
    assert sleep.calls == []
    await fetcher.aclose()


async def test_429_allowance_is_per_call() -> None:
    calls = 0

    def handler(_r: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls % 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, content=b"ok")

    fetcher, seen, sleep = make(handler)
    for _ in range(2):
        assert (await fetcher.get("https://feeds.example.com/feed")).content == b"ok"
    assert sleep.calls == [1.0, 1.0]
    assert len(seen) == 4
    await fetcher.aclose()


async def test_host_slot_released_while_backing_off() -> None:
    """With one slot per host, a request waiting to retry must not block another request."""
    gate = asyncio.Event()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        gate.set()
        return httpx.Response(200, content=b"ok")

    async def sleep(_seconds: float) -> None:
        await asyncio.wait_for(gate.wait(), timeout=1.0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = Fetcher(
        client=client, guard=UrlGuard(resolver=fake_resolver), sleep=sleep, per_host_concurrency=1
    )
    first = asyncio.create_task(fetcher.get("https://feeds.example.com/feed"))
    await asyncio.sleep(0)
    second = await fetcher.get("https://feeds.example.com/other")
    assert second.content == b"ok"
    assert (await first).content == b"ok"
    await client.aclose()


async def test_content_length_over_cap_rejected_before_reading() -> None:
    read = False

    async def body():
        nonlocal read
        read = True
        yield b"x"

    fetcher, seen, _ = make(
        lambda _r: httpx.Response(200, headers={"Content-Length": "1000"}, content=body()),
        max_bytes=10,
    )
    with pytest.raises(FetchTooLarge, match="Content-Length"):
        await fetcher.get("https://feeds.example.com/feed")
    assert read is False
    assert len(seen) == 1
    await fetcher.aclose()

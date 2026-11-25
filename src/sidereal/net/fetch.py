"""Outbound internet fetcher (plan §6.2). The only module that makes internet HTTP requests."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

import httpx

from sidereal import __version__
from sidereal.net.guard import UrlBlocked, UrlGuard

__all__ = [
    "FetchError",
    "FetchHTTPError",
    "FetchResponse",
    "FetchTooLarge",
    "Fetcher",
    "USER_AGENT",
    "UrlBlocked",
]

USER_AGENT = f"Sidereal/{__version__} (+personal news reader)"
RETRY_STATUSES = frozenset({502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
BACKOFF_S = (2.0, 6.0)  # 2 retries
MAX_REDIRECTS = 5
MAX_RETRY_AFTER_S = 60.0

_logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Base for every fetch failure except UrlBlocked."""


class FetchTooLarge(FetchError):
    """The response body exceeded the size limit."""


class FetchHTTPError(FetchError):
    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(message or f"HTTP {status}")


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status: int
    content: bytes
    content_type: str
    etag: str | None
    last_modified: str | None
    not_modified: bool


_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


def _retry_after(value: str | None) -> float | None:
    """Seconds from a numeric `Retry-After` within [0, MAX_RETRY_AFTER_S], else None."""
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None  # HTTP-date or junk: not honoured
    if 0 <= seconds <= MAX_RETRY_AFTER_S:  # also rejects nan / inf
        return seconds
    return None


class Fetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        guard: UrlGuard,
        max_bytes: int = 8_000_000,
        timeout_s: float = 20.0,
        per_host_concurrency: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._guard = guard
        self._max_bytes = max_bytes
        self._timeout = httpx.Timeout(timeout_s)
        self._per_host = per_host_concurrency
        self._sleep = sleep
        self._owned = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        self._client = client
        self._sems: dict[str, asyncio.Semaphore] = {}

    async def get(
        self,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_bytes: int | None = None,
        accept: str | None = None,
        allow_hosts: Iterable[str] | None = None,
    ) -> FetchResponse:
        limit = max_bytes if max_bytes is not None else self._max_bytes
        if allow_hosts is not None:
            allow_hosts = list(allow_hosts)  # reused on every hop; a generator would run dry
        headers = {"User-Agent": USER_AGENT}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if accept:
            headers["Accept"] = accept

        current = url
        redirects = 0
        while True:
            # The guard sees every URL before it is requested: the first one and each redirect.
            checked = await self._guard.check(current, allow_hosts=allow_hosts)
            status, resp_headers, body = await self._hop(checked.host, current, headers, limit)

            if status in REDIRECT_STATUSES:
                location = resp_headers.get("location")
                if not location:
                    raise FetchError(f"HTTP {status} without Location")
                if redirects >= MAX_REDIRECTS:
                    raise FetchError("too many redirects")
                redirects += 1
                current = str(httpx.URL(current).join(location))
                _logger.debug("redirect %d -> %s", status, current)
                continue

            if status == 304:
                return FetchResponse(
                    url=current,
                    status=304,
                    content=b"",
                    content_type=resp_headers.get("content-type", ""),
                    etag=resp_headers.get("etag") or etag,
                    last_modified=resp_headers.get("last-modified") or last_modified,
                    not_modified=True,
                )
            if 200 <= status <= 299:
                return FetchResponse(
                    url=current,
                    status=status,
                    content=body,
                    content_type=resp_headers.get("content-type", ""),
                    etag=resp_headers.get("etag"),
                    last_modified=resp_headers.get("last-modified"),
                    not_modified=False,
                )
            raise FetchHTTPError(status)

    async def _hop(
        self, host: str, url: str, headers: dict[str, str], limit: int
    ) -> tuple[int, httpx.Headers, bytes]:
        """One URL with retries. The host semaphore is held per request, never while sleeping."""
        sem = self._sems.get(host)
        if sem is None:
            sem = self._sems[host] = asyncio.Semaphore(self._per_host)
        retries = 0
        retried_429 = False
        while True:
            try:
                async with sem:
                    status, resp_headers, body = await self._request(url, headers, limit)
            except _CONNECT_ERRORS as exc:
                if retries < len(BACKOFF_S):
                    _logger.info("%s on %s, retrying", type(exc).__name__, url)
                    await self._sleep(BACKOFF_S[retries])
                    retries += 1
                    continue
                raise FetchError(f"{type(exc).__name__} for {url}") from exc
            except httpx.HTTPError as exc:  # read timeout, protocol error, ...: not retried
                raise FetchError(f"{type(exc).__name__} for {url}") from exc

            if status in RETRY_STATUSES:
                if retries < len(BACKOFF_S):
                    _logger.info("HTTP %d on %s, retrying", status, url)
                    await self._sleep(BACKOFF_S[retries])
                    retries += 1
                    continue
                raise FetchHTTPError(status)
            if status == 429:
                delay = _retry_after(resp_headers.get("retry-after"))
                if delay is None or retried_429:
                    raise FetchHTTPError(429)
                retried_429 = True
                _logger.info("HTTP 429 on %s, waiting %.1fs", url, delay)
                await self._sleep(delay)
                continue
            _logger.debug("HTTP %d %s", status, url)
            return status, resp_headers, body

    async def _request(
        self, url: str, headers: dict[str, str], limit: int
    ) -> tuple[int, httpx.Headers, bytes]:
        """One GET; the body is read (capped at `limit` bytes) only for 2xx."""
        async with self._client.stream(
            "GET", url, headers=headers, timeout=self._timeout, follow_redirects=False
        ) as resp:
            status = resp.status_code
            if not 200 <= status <= 299:
                return status, resp.headers, b""
            declared = resp.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > limit:
                raise FetchTooLarge(f"Content-Length {declared} > {limit}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > limit:
                    raise FetchTooLarge(f"body > {limit} bytes")
                chunks.append(chunk)
            return status, resp.headers, b"".join(chunks)

    async def aclose(self) -> None:
        if self._owned:
            await self._client.aclose()

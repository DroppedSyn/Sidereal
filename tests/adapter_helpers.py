"""Shared helpers for the source adapter tests: a fake source row and a Fetcher on MockTransport."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard

FEEDS = Path(__file__).parent / "fixtures" / "feeds"
FEED_URL = "https://feeds.example.com/feed"


async def fake_resolver(host: str, port: int) -> Sequence[str]:
    return ["93.184.215.14"]


@dataclass(frozen=True)
class FakeSource:
    key: str = "test-source"
    url: str = FEED_URL
    max_items: int = 50
    options: dict[str, Any] = field(default_factory=dict)
    etag: str | None = None
    last_modified: str | None = None


def feed_bytes(name: str) -> bytes:
    return (FEEDS / name).read_bytes()


def make_fetcher(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/rss+xml",
    headers: dict[str, str] | None = None,
) -> tuple[Fetcher, list[httpx.Request]]:
    """Fetcher whose every request gets `status` with `body`; returns (fetcher, requests seen)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status, content=body, headers={"content-type": content_type, **(headers or {})}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Fetcher(client=client, guard=UrlGuard(resolver=fake_resolver)), seen

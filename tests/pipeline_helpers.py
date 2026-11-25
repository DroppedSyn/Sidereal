"""Shared helpers for the pipeline tests (M13b): a seeded DB, a Fetcher serving the recorded
feed fixtures for the seed sources, and a FakeOllama answering triage/assess/digest calls."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from sidereal import bootstrap
from sidereal.config import Settings
from sidereal.db import Connection, sources_repo
from sidereal.db.connect import connect
from sidereal.llm.ollama import OllamaClient
from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from tests.adapter_helpers import FEEDS, fake_resolver
from tests.fake_ollama import FakeOllama

NOW = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)  # fixtures were recorded 2026-11-24
OLLAMA_URL = "http://ollama.test"
_ID = re.compile(r"^\[(\d+)\]", re.MULTILINE)
_TITLE = re.compile(r"^Title: (.*)$", re.MULTILINE)

Answer = httpx.Response | Callable[[httpx.Request], httpx.Response]


def seeded_db(settings: Settings) -> Connection:
    """``sidereal init`` (migrations + seed sources/focus areas), then an open connection."""
    bootstrap.init(settings)
    return connect(settings.db_path)


def fixture_file(key: str) -> bytes:
    for ext in (".xml", ".json"):
        path = FEEDS / f"{key}{ext}"
        if path.exists():
            return path.read_bytes()
    raise KeyError(key)


class FeedServer:
    """MockTransport handler: each seed source URL answers its fixture (``<key>.xml|json``);
    ``overrides[key]`` replaces a source's answer; ``pages[url]`` answers article URLs; anything
    else is 404. ``requests`` records every URL asked for."""

    def __init__(self, conn: Connection) -> None:
        self.by_url = {s.url: s.key for s in sources_repo.list_sources(conn)}
        self.overrides: dict[str, Answer] = {}
        self.pages: dict[str, Answer] = {}
        self.requests: list[str] = []

    def _key(self, url: str) -> str | None:
        if url in self.by_url:
            return self.by_url[url]
        base = url.split("?", 1)[0]
        key = self.by_url.get(base)  # hn_algolia adds the query itself
        return key if key == "hn-cloud-sec" else None

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        key = self._key(url)
        answer: Answer | None = None
        if key is not None:
            answer = self.overrides.get(key)
            if answer is None:
                body = fixture_file(key)
                ctype = "application/json" if body.lstrip()[:1] in (b"{", b"[") else \
                    "application/rss+xml"
                answer = httpx.Response(200, content=body, headers={"content-type": ctype})
        else:
            answer = self.pages.get(url)
        if answer is None:
            return httpx.Response(404, content=b"not found")
        return answer(request) if callable(answer) else answer

    def fetcher(self) -> Fetcher:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return Fetcher(client=client, guard=UrlGuard(resolver=fake_resolver), sleep=_no_sleep)


async def _no_sleep(_: float) -> None:
    return None


def kind_of(body: dict[str, Any]) -> str:
    props = body.get("format", {}).get("properties", {})
    if "results" in props:
        return "triage"
    if "overview" in props:
        return "digest"
    return "assess"


def user_text(body: dict[str, Any]) -> str:
    return body["messages"][1]["content"]


def triage_ids(body: dict[str, Any]) -> list[int]:
    return [int(m) for m in _ID.findall(user_text(body))]


def assess_title(body: dict[str, Any]) -> str:
    m = _TITLE.search(user_text(body))
    return m.group(1) if m else ""


def assess_reply(relevance: int = 3, urgency: int = 2, actionability: int = 2,
                 novelty: int = 2, **over: Any) -> dict[str, Any]:
    reply = {"relevance": relevance, "urgency": urgency, "actionability": actionability,
             "novelty": novelty, "focus": "azure-networking", "tags": ["test"],
             "exploited_in_wild": False, "summary": "A summary.", "why": "Why it matters."}
    reply.update(over)
    return reply


def smart_ollama(*, triage_relevance: Callable[[int], int] = lambda i: 2,
                 assess: Callable[[str], dict[str, Any]] = lambda title: assess_reply(),
                 digest: dict[str, Any] | None = None) -> FakeOllama:
    """FakeOllama answering every triage id, every assess call (by article title) and every
    digest call."""
    fake = FakeOllama()
    fake.on_chat(lambda b: kind_of(b) == "triage", lambda b: {
        "results": [{"id": i, "relevance": triage_relevance(i)} for i in triage_ids(b)]})
    fake.on_chat(lambda b: kind_of(b) == "digest",
                 digest or {"overview": "The day in brief.", "headline": "A headline"})
    fake.on_chat(lambda b: kind_of(b) == "assess", lambda b: assess(assess_title(b)))
    return fake


def ollama_for(fake: FakeOllama, settings: Settings) -> OllamaClient:
    client = httpx.AsyncClient(transport=fake.transport())
    return OllamaClient(OLLAMA_URL, client=client, never_unload=settings.models.never_unload)


def chats(fake: FakeOllama, kind: str) -> list[dict[str, Any]]:
    return [b for b in fake.calls("/api/chat") if kind_of(b) == kind]


class FakeClock:
    """Monotonic clock for Deadline tests; ``advance`` moves it, ``tick`` per call."""

    def __init__(self, tick: float = 0.0) -> None:
        self.t = 1000.0
        self.tick = tick

    def __call__(self) -> float:
        self.t += self.tick
        return self.t


def start(conn: Connection, at: datetime = NOW) -> int:
    from sidereal.db import runs_repo

    return runs_repo.start_run(conn, trigger="manual", at=at)


def add_story(conn: Connection, run_id: int, *, source: str = "bleepingcomputer",
              title: str = "Some story title here", url: str | None = None,
              published: datetime | None = None, excerpt: str = "An excerpt.",
              at: datetime = NOW, day: str = "2026-11-25", cve_ids: tuple[str, ...] = (),
              flags: dict[str, Any] | None = None, extra_sources: tuple[str, ...] = ()) -> int:
    """A ``new`` story with one item from ``source`` (plus one item per ``extra_sources``)."""
    from sidereal.db import items_repo, stories_repo
    from sidereal.pipeline.dedupe import normalize_title

    sid = stories_repo.create_story(conn, title=title, day=day, first_seen_at=at,
                                    first_run_id=run_id, cve_ids=cve_ids, flags=flags)
    for n, key in enumerate((source, *extra_sources)):
        src = sources_repo.get_by_key(conn, key)
        assert src is not None, key
        item_url = url if (url and n == 0) else f"https://{key}.example/{sid}/{n}"
        iid = items_repo.insert_item(
            conn, source_id=src.id, story_id=sid, guid=item_url, url=item_url,
            canonical_url=item_url, title=title, title_norm=normalize_title(title), author=None,
            published_at=published, first_seen_at=at, run_id=run_id, excerpt=excerpt)
        assert iid is not None
        stories_repo.attach_item(conn, sid, item_id=iid, seen_at=at)
    return sid


def count(conn: Connection, table: str) -> int:
    assert table in {"stories", "items", "runs", "assessments", "day_digests"}
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def state_of(conn: Connection, story_id: int) -> str:
    from sidereal.db import stories_repo

    row = stories_repo.get_story(conn, story_id)
    assert row is not None
    return row.state

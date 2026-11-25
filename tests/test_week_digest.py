"""llm/week_digest.py (M29): schema, longer overview, URLs stripped, paragraphs kept."""

from __future__ import annotations

import httpx
import pytest

from sidereal.llm.ollama import LLMOutputInvalid, OllamaClient
from sidereal.llm.week_digest import (
    OVERVIEW_MAX,
    WEEK_DIGEST_SCHEMA,
    clean_overview,
    write_week_digest,
)
from tests.fake_ollama import FakeOllama


def make(fake: FakeOllama) -> OllamaClient:
    return OllamaClient("http://ollama.test", client=httpx.AsyncClient(transport=fake.transport()))


async def run(fake: FakeOllama):
    return await write_week_digest(make(fake), model="m", system="SYS", user="USER")


def test_schema_allows_a_250_word_overview():
    assert WEEK_DIGEST_SCHEMA["required"] == ["overview", "headline"]
    assert WEEK_DIGEST_SCHEMA["properties"]["overview"]["maxLength"] == OVERVIEW_MAX == 2400
    assert WEEK_DIGEST_SCHEMA["properties"]["headline"]["maxLength"] == 160


async def test_urls_stripped_and_paragraphs_kept():
    fake = FakeOllama()
    fake.chat_replies.append({
        "overview": "Azure: see https://evil.example/x now.\n\n  Identity <http://a.b/c> news. "
                    "\n \nhttps://only.example/url\n\nLast   line\nwraps.",
        "headline": "Week of HTTPS://x.example/y patches"})
    res = await run(fake)
    assert res.overview == "Azure: see now.\n\nIdentity news.\n\nLast line wraps."
    assert res.headline == "Week of patches"
    body = fake.calls("/api/chat")[0]
    assert body["format"] == WEEK_DIGEST_SCHEMA and body["think"] is False


async def test_url_only_fields_become_empty():
    fake = FakeOllama()
    fake.chat_replies.append({"overview": "https://a.example/", "headline": "http://b.example"})
    res = await run(fake)
    assert (res.overview, res.headline) == ("", "")


async def test_too_long_overview_retried_then_invalid():
    fake = FakeOllama()
    long = {"overview": "x" * (OVERVIEW_MAX + 1), "headline": "h"}
    fake.chat_replies.extend([long, long])
    with pytest.raises(LLMOutputInvalid):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


def test_clean_overview_drops_empty_paragraphs():
    assert clean_overview("\n\nA\n\n\n\nB\n\n") == "A\n\nB"

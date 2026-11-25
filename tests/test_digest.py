"""Tests for ``src/sidereal/llm/digest.py``."""

from __future__ import annotations

import dataclasses

import httpx
import pytest

from sidereal.llm.digest import (
    DIGEST_SCHEMA,
    DigestResult,
    strip_urls,
    write_digest,
)
from sidereal.llm.ollama import LLMOutputInvalid, LLMUnavailable, OllamaClient
from tests.fake_ollama import FakeOllama

VALID = {
    "overview": "Microsoft patched CVE-2026-1234 in Entra. Azure changed VNet peering.",
    "headline": "Entra patch for CVE-2026-1234",
}


def make(fake: FakeOllama) -> OllamaClient:
    return OllamaClient(
        "http://ollama.test",
        client=httpx.AsyncClient(transport=fake.transport()),
    )


async def run(fake: FakeOllama, **kw) -> DigestResult:
    args = {"model": "m1", "system": "SYS", "user": "USER", **kw}
    return await write_digest(make(fake), **args)


def reply(**changes):
    return {**VALID, **changes}


def test_schema():
    assert DIGEST_SCHEMA == {
        "type": "object",
        "properties": {
            "overview": {"type": "string", "minLength": 1, "maxLength": 1200},
            "headline": {"type": "string", "minLength": 1, "maxLength": 160},
        },
        "required": ["overview", "headline"],
    }


async def test_valid_reply_result():
    fake = FakeOllama(chat_replies=[VALID])
    r = await run(fake)
    assert r == DigestResult(
        overview=VALID["overview"],
        headline=VALID["headline"],
        raw=VALID,
        duration_ms=1500,
        eval_count=42,
    )


async def test_request_body():
    fake = FakeOllama(chat_replies=[VALID])
    await run(fake)
    body = fake.calls("/api/chat")[0]
    assert body["format"] == DIGEST_SCHEMA
    assert body["think"] is False
    assert body["model"] == "m1"
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert body["keep_alive"] == "10m"
    assert body["options"]["num_ctx"] == 8192
    assert len(fake.calls("/api/chat")) == 1


async def test_keep_alive_and_num_ctx_passed():
    fake = FakeOllama(chat_replies=[VALID])
    await run(fake, keep_alive="5m", num_ctx=4096)
    body = fake.calls("/api/chat")[0]
    assert body["keep_alive"] == "5m"
    assert body["options"]["num_ctx"] == 4096


async def test_urls_stripped():
    fake = FakeOllama(
        chat_replies=[
            reply(
                overview="Patch now https://evil.example/x before Friday (http://a.b) today.",
                headline="See <https://x.y/z> now",
            )
        ]
    )
    r = await run(fake)
    assert r.overview == "Patch now before Friday today."
    assert r.headline == "See now"
    assert r.raw["overview"] == (
        "Patch now https://evil.example/x before Friday (http://a.b) today."
    )


async def test_whitespace_collapsed():
    fake = FakeOllama(
        chat_replies=[
            reply(overview="Line one.\n\nLine  two.", headline="  Spaced   headline ")
        ]
    )
    r = await run(fake)
    assert r.overview == "Line one. Line two."
    assert r.headline == "Spaced headline"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("no links here", "no links here"),
        ("a https://x.y b", "a b"),
        ("http://only.example", ""),
        ("x (https://p.q/r) y", "x y"),
        ("x <http://p.q> y", "x y"),
        ("  spaced   out  ", "spaced out"),
    ],
)
def test_strip_urls_unit(text, expected):
    assert strip_urls(text) == expected


async def test_overview_too_long_invalid():
    fake = FakeOllama(
        chat_replies=[reply(overview="a" * 1201), reply(overview="a" * 1201)]
    )
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


async def test_headline_too_long_invalid():
    fake = FakeOllama(
        chat_replies=[reply(headline="h" * 161), reply(headline="h" * 161)]
    )
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


async def test_at_limit_ok():
    fake = FakeOllama(
        chat_replies=[reply(overview="a" * 1200, headline="h" * 160)]
    )
    r = await run(fake)
    assert r.overview == "a" * 1200
    assert r.headline == "h" * 160
    assert len(fake.calls("/api/chat")) == 1


async def test_empty_overview_invalid():
    fake = FakeOllama(chat_replies=[reply(overview=""), reply(overview="")])
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


async def test_empty_headline_invalid():
    fake = FakeOllama(chat_replies=[reply(headline=""), reply(headline="")])
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


async def test_missing_headline_invalid():
    fake = FakeOllama(chat_replies=[{"overview": "x"}, {"overview": "x"}])
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


async def test_non_string_overview_invalid():
    fake = FakeOllama(
        chat_replies=[reply(overview=["a", "b"]), reply(overview=["a", "b"])]
    )
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


async def test_invalid_then_valid_retries_once():
    fake = FakeOllama(chat_replies=[reply(headline=""), VALID])
    r = await run(fake)
    assert r.headline == VALID["headline"]
    assert len(fake.calls("/api/chat")) == 2


async def test_not_json_then_valid():
    fake = FakeOllama(chat_replies=["not json", VALID])
    r = await run(fake)
    assert r.overview == VALID["overview"]
    assert len(fake.calls("/api/chat")) == 2


async def test_unavailable_propagates():
    fake = FakeOllama(chat_replies=[VALID])
    fake.errors["/api/chat"] = httpx.Response(500, json={"error": "boom"})
    with pytest.raises(LLMUnavailable, match="boom"):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 1


async def test_stats_from_result():
    fake = FakeOllama(chat_replies=[VALID])
    fake.eval_count = 7
    fake.total_duration = 2_345_000_000
    r = await run(fake)
    assert r.duration_ms == 2345
    assert r.eval_count == 7


async def test_extra_keys_ignored():
    fake = FakeOllama(chat_replies=[reply(extra="x")])
    r = await run(fake)
    assert r.raw["extra"] == "x"
    assert r.headline == VALID["headline"]


async def test_url_only_headline_becomes_empty():
    fake = FakeOllama(chat_replies=[reply(headline="https://x.example/a")])
    r = await run(fake)
    assert r.headline == ""


def test_strip_urls_is_the_assess_helper():
    from sidereal.llm import assess

    assert strip_urls is assess.strip_urls


async def test_upper_case_urls_stripped_in_both_fields():
    fake = FakeOllama(
        chat_replies=[reply(overview="Read HTTPS://Evil.Example/X now.", headline="Go Http://a.b")]
    )
    r = await run(fake)
    assert r.overview == "Read now."
    assert r.headline == "Go"


async def test_url_only_overview_becomes_empty():
    fake = FakeOllama(chat_replies=[reply(overview="(https://x.example/a)")])
    r = await run(fake)
    assert r.overview == ""
    assert r.headline == VALID["headline"]


async def test_result_is_frozen():
    fake = FakeOllama(chat_replies=[VALID])
    r = await run(fake)
    with pytest.raises(dataclasses.FrozenInstanceError, match="overview"):
        r.overview = "x"

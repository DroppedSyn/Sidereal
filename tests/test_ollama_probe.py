"""Tests for OllamaClient.probe() and the timeout kwarg on _request (plan §7.5)."""

from __future__ import annotations

import httpx
import pytest

from sidereal.llm.ollama import LLMUnavailable, OllamaClient, ProbeResult
from tests.fake_ollama import FakeOllama


def make(fake: FakeOllama) -> OllamaClient:
    return OllamaClient(
        "http://ollama.test",
        client=httpx.AsyncClient(transport=fake.transport()),
    )


async def test_probe_request_body():
    fake = FakeOllama()
    await make(fake).probe("m1", timeout_s=30.0)
    assert fake.calls("/api/generate") == [
        {
            "model": "m1",
            "prompt": "ok",
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {"num_predict": 1},
        },
    ]


async def test_probe_parses_durations():
    fake = FakeOllama()
    fake.errors["/api/generate"] = httpx.Response(
        200,
        json={
            "done": True,
            "total_duration": 2_500_000_000,
            "load_duration": 1_200_000_000,
        },
    )
    result = await make(fake).probe("m1", timeout_s=30.0)
    assert result == ProbeResult(total_ms=2500, load_ms=1200)


async def test_probe_missing_durations_are_zero():
    fake = FakeOllama()
    # Default fake reply has load_duration: 0, no total_duration
    result = await make(fake).probe("m1", timeout_s=30.0)
    assert result == ProbeResult(total_ms=0, load_ms=0)


async def test_probe_uses_given_timeout():
    fake = FakeOllama()
    seen: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"]["read"])
        return fake.handler(request)

    inner = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        timeout=5.0,
    )
    client = OllamaClient(
        "http://ollama.test",
        client=inner,
    )
    result = await client.probe("m1", timeout_s=7.0)
    assert seen == [7.0]
    assert isinstance(result, ProbeResult)


async def test_probe_http_error_is_unavailable():
    fake = FakeOllama()
    fake.errors["/api/generate"] = httpx.Response(500, json={"error": "boom"})
    with pytest.raises(LLMUnavailable, match="boom"):
        await make(fake).probe("m1", timeout_s=30.0)


async def test_probe_timeout_is_unavailable():
    fake = FakeOllama()
    fake.errors["/api/generate"] = httpx.ReadTimeout("slow")
    with pytest.raises(LLMUnavailable, match="timed out"):
        await make(fake).probe("m1", timeout_s=30.0)

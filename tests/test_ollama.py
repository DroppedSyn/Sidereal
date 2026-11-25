import httpx
import pytest
from pydantic import BaseModel

from sidereal.llm.ollama import (
    RETRY_LINE,
    ChatResult,
    LLMError,
    LLMOutputInvalid,
    LLMUnavailable,
    LoadedModel,
    OllamaClient,
)
from tests.fake_ollama import FakeOllama

SCHEMA = {"type": "object", "properties": {"relevance": {"type": "integer"}},
          "required": ["relevance"]}
RETRY_TEXT = "Your previous reply was not valid JSON for the schema. Reply with JSON only."


class Rel(BaseModel):
    relevance: int


def make(fake: FakeOllama, **kw) -> OllamaClient:
    return OllamaClient("http://ollama.test", client=httpx.AsyncClient(transport=fake.transport()),
                        **kw)


async def chat(c: OllamaClient, **kw) -> ChatResult:
    args = {"model": "m1", "system": "SYS", "user": "USR", "schema": SCHEMA, **kw}
    return await c.chat_json(**args)


async def test_request_body_exact():
    fake = FakeOllama([{"relevance": 2}])
    await chat(make(fake))
    assert fake.calls("/api/chat") == [{
        "model": "m1", "stream": False, "think": False, "format": SCHEMA,
        "options": {"temperature": 0.0, "num_ctx": 8192}, "keep_alive": "10m",
        "messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}],
    }]
    assert fake.requests[0][:2] == ("POST", "/api/chat")


async def test_request_options_passed():
    fake = FakeOllama([{"relevance": 2}])
    await chat(make(fake), num_ctx=4096, temperature=0.2, keep_alive="5m", think=True)
    body = fake.calls("/api/chat")[0]
    assert body["options"] == {"temperature": 0.2, "num_ctx": 4096}
    assert body["keep_alive"] == "5m"
    assert body["think"] is True


async def test_parses_content_json():
    result = await chat(make(FakeOllama([{"relevance": 2}])))
    assert isinstance(result, ChatResult)
    assert result.content == {"relevance": 2}
    assert result.parsed is None


async def test_stats_and_total_ms():
    fake = FakeOllama([{"relevance": 2}])
    fake.total_duration = 2_345_678_901
    fake.eval_count = 7
    fake.prompt_eval_count = 99
    result = await chat(make(fake))
    assert result.total_ms == 2345
    assert result.eval_count == 7
    assert result.prompt_eval_count == 99


async def test_validator_sets_parsed():
    result = await chat(make(FakeOllama([{"relevance": 2}])), validator=Rel)
    assert result.parsed == Rel(relevance=2)
    assert result.content == {"relevance": 2}


async def test_invalid_json_then_valid_retries_once():
    fake = FakeOllama(["not json", {"relevance": 3}])
    result = await chat(make(fake))
    assert result.content == {"relevance": 3}
    calls = fake.calls("/api/chat")
    assert len(calls) == 2
    first, second = calls
    assert second["messages"] == first["messages"] + [{"role": "user", "content": RETRY_TEXT}]
    assert {k: v for k, v in second.items() if k != "messages"} == \
        {k: v for k, v in first.items() if k != "messages"}
    assert RETRY_LINE == RETRY_TEXT


async def test_retry_stats_come_from_successful_reply():
    bad = httpx.Response(200, json={"message": {"content": "bad"}, "eval_count": 1,
                                    "prompt_eval_count": 2, "total_duration": 3_000_000})
    fake = FakeOllama([bad, {"relevance": 5}])
    fake.eval_count = 11
    result = await chat(make(fake))
    assert result.content == {"relevance": 5}
    assert (result.eval_count, result.prompt_eval_count, result.total_ms) == (11, 420, 1500)


async def test_invalid_twice_raises_output_invalid():
    fake = FakeOllama(["nope", "still nope", {"relevance": 1}])
    with pytest.raises(LLMOutputInvalid):
        await chat(make(fake))
    assert len(fake.calls("/api/chat")) == 2
    assert issubclass(LLMOutputInvalid, LLMError)


async def test_validation_failure_counts_as_invalid():
    fake = FakeOllama([{"relevance": "high"}, {"relevance": "high"}])
    with pytest.raises(LLMOutputInvalid):
        await chat(make(fake), validator=Rel)
    assert len(fake.calls("/api/chat")) == 2


async def test_validation_failure_then_valid():
    fake = FakeOllama([{"wrong": 1}, {"relevance": 4}])
    result = await chat(make(fake), validator=Rel)
    assert result.parsed == Rel(relevance=4)
    assert len(fake.calls("/api/chat")) == 2


async def test_non_object_json_is_invalid():
    fake = FakeOllama(["[1, 2]", "42"])
    with pytest.raises(LLMOutputInvalid):
        await chat(make(fake))


async def test_missing_message_is_invalid_not_crash():
    fake = FakeOllama([httpx.Response(200, json={"done": True}),
                       httpx.Response(200, json={"message": None})])
    with pytest.raises(LLMOutputInvalid):
        await chat(make(fake))


async def test_output_invalid_message_has_no_reply_text():
    fake = FakeOllama(["SECRET-REPLY", "SECRET-REPLY"])
    with pytest.raises(LLMOutputInvalid) as ei:
        await chat(make(fake), system="SECRET-SYS")
    assert "SECRET" not in str(ei.value)


async def test_http_error_is_unavailable_without_prompt():
    fake = FakeOllama([httpx.Response(500, json={"error": "model not found"})])
    with pytest.raises(LLMUnavailable) as ei:
        await chat(make(fake), system="SECRET-SYS", user="SECRET-USR")
    assert "model not found" in str(ei.value)
    assert "SECRET" not in str(ei.value)
    assert len(fake.calls("/api/chat")) == 1
    assert issubclass(LLMUnavailable, LLMError)


async def test_http_error_on_retry_is_unavailable():
    fake = FakeOllama(["not json", httpx.Response(503, text="busy")])
    with pytest.raises(LLMUnavailable, match="HTTP 503: busy"):
        await chat(make(fake))
    assert len(fake.calls("/api/chat")) == 2


async def test_connect_error_is_unavailable():
    fake = FakeOllama([httpx.ConnectError("refused")])
    with pytest.raises(LLMUnavailable, match="unreachable"):
        await chat(make(fake))
    assert len(fake.calls("/api/chat")) == 1


async def test_timeout_is_unavailable():
    fake = FakeOllama([httpx.ReadTimeout("slow")])
    with pytest.raises(LLMUnavailable, match="timed out"):
        await chat(make(fake))


async def test_non_json_200_is_unavailable():
    fake = FakeOllama([httpx.Response(200, text="<html>")])
    with pytest.raises(LLMUnavailable, match="not JSON"):
        await chat(make(fake))


async def test_ps_parses():
    fake = FakeOllama(loaded=["qwen3.6:35b-a3b-coding",
                              {"name": "qwen3.8:27b", "model": "qwen3.8:27b", "size": 5,
                               "size_vram": 4, "expires_at": "2026-11-25T13:00:00Z"}])
    assert await make(fake).ps() == [
        LoadedModel("qwen3.6:35b-a3b-coding", 1000, "2026-11-25T12:10:00Z"),
        LoadedModel("qwen3.8:27b", 4, "2026-11-25T13:00:00Z"),
    ]


async def test_ps_connect_error_is_unavailable():
    fake = FakeOllama()
    fake.errors["/api/ps"] = httpx.ConnectError("refused")
    with pytest.raises(LLMUnavailable):
        await make(fake).ps()


async def test_has_model_exact_and_latest():
    c = make(FakeOllama(models=["qwen3.8:27b", "llama3:latest"]))
    assert await c.has_model("qwen3.8:27b") is True
    assert await c.has_model("llama3") is True
    assert await c.has_model("qwen3.8") is False
    assert await c.has_model("llama3:8b") is False


async def test_never_unloads_protected_model():
    fake = FakeOllama(loaded=["qwen3.6:35b-a3b-coding", "qwen3.8:27b"])
    c = make(fake, never_unload=["qwen3.6:35b-a3b-coding"])
    await c.unload("qwen3.6:35b-a3b-coding")
    assert fake.requests == []
    await c.unload("qwen3.8:27b")
    assert fake.calls("/api/generate") == [{"model": "qwen3.8:27b", "keep_alive": 0}]
    assert fake.loaded == ["qwen3.6:35b-a3b-coding"]


async def test_unload_http_error_is_unavailable():
    fake = FakeOllama()
    fake.errors["/api/generate"] = httpx.Response(500, json={"error": "boom"})
    with pytest.raises(LLMUnavailable, match="boom"):
        await make(fake).unload("x")


async def test_owned_client_ignores_env_proxies():
    c = OllamaClient("http://ollama.test", timeout_s=12.0)
    assert c._client.trust_env is False
    assert c._client.timeout.read == 12.0
    await c.aclose()
    assert c._client.is_closed is True


async def test_aclose_leaves_passed_client_open():
    inner = httpx.AsyncClient(transport=FakeOllama().transport())
    c = OllamaClient("http://ollama.test", client=inner)
    await c.aclose()
    assert inner.is_closed is False
    await inner.aclose()


async def test_base_url_trailing_slash():
    fake = FakeOllama([{"relevance": 1}])
    c = OllamaClient("http://ollama.test/", client=httpx.AsyncClient(transport=fake.transport()))
    await chat(c)
    assert fake.requests[0][1] == "/api/chat"


async def test_fake_rule_matches_system_prompt():
    fake = FakeOllama([{"relevance": 1}])
    fake.on_chat(lambda b: "TRIAGE" in b["messages"][0]["content"], {"relevance": 9})
    c = make(fake)
    assert (await chat(c, system="TRIAGE v1")).content == {"relevance": 9}
    assert (await chat(c, system="TRIAGE v1")).content == {"relevance": 9}
    assert (await chat(c, system="OTHER")).content == {"relevance": 1}


async def test_fake_callable_reply():
    fake = FakeOllama()
    fake.on_chat(lambda b: True, lambda b: {"relevance": len(b["messages"])})
    assert (await chat(make(fake))).content == {"relevance": 2}


async def test_fake_records_errored_requests():
    fake = FakeOllama()
    fake.errors["/api/tags"] = httpx.ConnectError("refused")
    with pytest.raises(LLMUnavailable):
        await make(fake).has_model("x")
    assert fake.requests == [("GET", "/api/tags", {})]


async def test_passed_client_gets_per_request_timeout():
    fake = FakeOllama([{"relevance": 1}])
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"]["read"])
        return fake.handler(request)

    inner = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    await chat(OllamaClient("http://ollama.test", client=inner, timeout_s=42.0))
    assert seen == [42.0]

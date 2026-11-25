import logging

import httpx
import pytest

from sidereal.llm.assess import (
    AssessmentResult,
    assess_schema,
    assess_story,
    clean_tags,
    strip_urls,
)
from sidereal.llm.ollama import LLMOutputInvalid, LLMUnavailable, OllamaClient
from sidereal.pipeline.scoring import Rubric
from tests.fake_ollama import FakeOllama

KEYS = ["azure-networking", "entra-identity"]
VALID = {
    "relevance": 2,
    "urgency": 3,
    "actionability": 1,
    "novelty": 2,
    "focus": "azure-networking",
    "tags": ["Azure", "VNet"],
    "exploited_in_wild": True,
    "summary": "Azure changed VNet peering.",
    "why": "You run peered VNets.",
}


def make(fake: FakeOllama) -> OllamaClient:
    return OllamaClient(
        "http://ollama.test",
        client=httpx.AsyncClient(transport=fake.transport()),
    )


async def run(fake: FakeOllama, **kw) -> AssessmentResult:
    args = {
        "model": "m1",
        "system": "SYS",
        "user": "USER",
        "focus_keys": KEYS,
        **kw,
    }
    return await assess_story(make(fake), **args)


def reply(**changes):
    return {**VALID, **changes}


# 1. test_schema_enum_from_keys
async def test_schema_enum_from_keys():
    s = assess_schema(KEYS)
    assert s["properties"]["focus"] == {
        "type": "string",
        "enum": ["azure-networking", "entra-identity", "none"],
    }
    assert s["required"] == [
        "relevance",
        "urgency",
        "actionability",
        "novelty",
        "focus",
        "tags",
        "exploited_in_wild",
        "summary",
        "why",
    ]
    assert s["properties"]["relevance"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 3,
    }
    assert s["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": 5,
    }
    assert s["properties"]["summary"] == {
        "type": "string",
        "maxLength": 600,
    }
    assert s["properties"]["why"] == {
        "type": "string",
        "maxLength": 300,
    }
    assert s["properties"]["exploited_in_wild"] == {"type": "boolean"}
    assert s["type"] == "object"


# 2. test_schema_none_not_duplicated
async def test_schema_none_not_duplicated():
    s = assess_schema(["a", "none", "b"])
    assert s["properties"]["focus"]["enum"] == ["a", "b", "none"]
    s2 = assess_schema([])
    assert s2["properties"]["focus"]["enum"] == ["none"]


# 3. test_valid_reply_result
async def test_valid_reply_result():
    fake = FakeOllama(chat_replies=[VALID])
    r = await run(fake)
    assert r == AssessmentResult(
        rubric=Rubric(2, 3, 1, 2, True),
        focus="azure-networking",
        tags=("Azure", "VNet"),
        summary="Azure changed VNet peering.",
        why="You run peered VNets.",
        raw=VALID,
        duration_ms=1500,
        eval_count=42,
    )


# 4. test_request_body
async def test_request_body():
    fake = FakeOllama(chat_replies=[VALID])
    await run(fake)
    body = fake.calls("/api/chat")[0]
    assert body["format"] == assess_schema(KEYS)
    assert body["think"] is False
    assert body["model"] == "m1"
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]
    assert body["keep_alive"] == "10m"
    assert body["options"]["num_ctx"] == 8192
    assert len(fake.calls("/api/chat")) == 1


# 5. test_keep_alive_and_num_ctx_passed
async def test_keep_alive_and_num_ctx_passed():
    fake = FakeOllama(chat_replies=[VALID])
    await run(fake, keep_alive="5m", num_ctx=4096)
    body = fake.calls("/api/chat")[0]
    assert body["keep_alive"] == "5m"
    assert body["options"]["num_ctx"] == 4096


# 6. test_urls_stripped
async def test_urls_stripped():
    fake = FakeOllama(
        chat_replies=[
            reply(
                summary="Patch now https://evil.example/x before Friday (http://a.b) today.",
                why="See <https://x.y/z> for details.",
            )
        ]
    )
    r = await run(fake)
    assert r.summary == "Patch now before Friday today."
    assert r.why == "See for details."
    assert (
        r.raw["summary"]
        == "Patch now https://evil.example/x before Friday (http://a.b) today."
    )


# 7. test_strip_urls_unit
@pytest.mark.parametrize(
    "text, expected",
    [
        ("no links here", "no links here"),
        ("a https://x.y b", "a b"),
        ("http://only.example", ""),
        ("x (https://p.q/r) y", "x y"),
        ("  spaced   out  ", "spaced out"),
    ],
)
async def test_strip_urls_unit(text, expected):
    assert strip_urls(text) == expected


# 8. test_rubric_out_of_range_twice_invalid
async def test_rubric_out_of_range_twice_invalid():
    fake = FakeOllama(chat_replies=[reply(relevance=4), reply(relevance=4)])
    with pytest.raises(LLMOutputInvalid):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


# 9. test_negative_rubric_invalid
async def test_negative_rubric_invalid():
    fake = FakeOllama(chat_replies=[reply(urgency=-1), reply(urgency=-1)])
    with pytest.raises(LLMOutputInvalid):
        await run(fake)


# 10. test_string_rubric_invalid
async def test_string_rubric_invalid():
    fake = FakeOllama(chat_replies=[reply(novelty="2"), reply(novelty="2")])
    with pytest.raises(LLMOutputInvalid):
        await run(fake)


# 11. test_invalid_then_valid_retries_once
async def test_invalid_then_valid_retries_once():
    fake = FakeOllama(chat_replies=[reply(relevance=4), VALID])
    r = await run(fake)
    assert r.rubric == Rubric(2, 3, 1, 2, True)
    assert len(fake.calls("/api/chat")) == 2


# 12. test_not_json_then_valid
async def test_not_json_then_valid():
    fake = FakeOllama(chat_replies=["not json", VALID])
    r = await run(fake)
    assert r.rubric == Rubric(2, 3, 1, 2, True)
    assert len(fake.calls("/api/chat")) == 2


# 13. test_missing_field_invalid
async def test_missing_field_invalid():
    no_why = {k: v for k, v in VALID.items() if k != "why"}
    fake = FakeOllama(chat_replies=[no_why, no_why])
    with pytest.raises(LLMOutputInvalid):
        await run(fake)


# 14. test_unknown_focus_becomes_none
async def test_unknown_focus_becomes_none(caplog):
    fake = FakeOllama(chat_replies=[reply(focus="cooking")])
    with caplog.at_level(logging.INFO, logger="sidereal.llm.assess"):
        r = await run(fake)
    assert r.focus == "none"
    assert r.raw["focus"] == "cooking"
    assert len(fake.calls("/api/chat")) == 1
    assert "unknown focus 'cooking'" in caplog.text


# 15. test_focus_none_kept
async def test_focus_none_kept():
    fake = FakeOllama(chat_replies=[reply(focus="none")])
    r = await run(fake)
    assert r.focus == "none"

    fake2 = FakeOllama(chat_replies=[reply(focus="entra-identity")])
    r2 = await run(fake2)
    assert r2.focus == "entra-identity"


# 16. test_tags_trimmed
async def test_tags_trimmed():
    fake = FakeOllama(
        chat_replies=[reply(tags=["  Azure  ", "x" * 50, "   "])]
    )
    r = await run(fake)
    assert r.tags == ("Azure", "x" * 40)


# 17. test_clean_tags_unit
async def test_clean_tags_unit():
    assert clean_tags([]) == ()
    assert clean_tags([" a ", "b"]) == ("a", "b")


# 18. test_too_many_tags_invalid
async def test_too_many_tags_invalid():
    fake = FakeOllama(
        chat_replies=[reply(tags=["a", "b", "c", "d", "e", "f"])]
        + [reply(tags=["a", "b", "c", "d", "e", "f"])]
    )
    with pytest.raises(LLMOutputInvalid):
        await run(fake)

    fake2 = FakeOllama(
        chat_replies=[reply(tags=["a", "b", "c", "d", "e"])]
    )
    r = await run(fake2)
    assert r.tags == ("a", "b", "c", "d", "e")


# 19. test_summary_too_long_invalid
async def test_summary_too_long_invalid():
    fake = FakeOllama(
        chat_replies=[reply(summary="a" * 601)]
        + [reply(summary="a" * 601)]
    )
    with pytest.raises(LLMOutputInvalid):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


# 20. test_summary_at_limit_ok
async def test_summary_at_limit_ok():
    fake = FakeOllama(
        chat_replies=[reply(summary="a" * 600, why="b" * 300)]
    )
    r = await run(fake)
    assert r.summary == "a" * 600
    assert r.why == "b" * 300


# 21. test_why_too_long_invalid
async def test_why_too_long_invalid():
    fake = FakeOllama(
        chat_replies=[reply(why="b" * 301)]
        + [reply(why="b" * 301)]
    )
    with pytest.raises(LLMOutputInvalid):
        await run(fake)


# 22. test_unavailable_propagates
async def test_unavailable_propagates():
    fake = FakeOllama(chat_replies=[VALID])
    fake.errors["/api/chat"] = httpx.Response(
        500, json={"error": "boom"}
    )
    with pytest.raises(LLMUnavailable):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 1


# 23. test_stats_from_result
async def test_stats_from_result():
    fake = FakeOllama(chat_replies=[VALID])
    fake.eval_count = 7
    fake.total_duration = 2_345_000_000
    r = await run(fake)
    assert r.duration_ms == 2345
    assert r.eval_count == 7


# 24. test_extra_keys_ignored
async def test_extra_keys_ignored():
    fake = FakeOllama(chat_replies=[reply(extra="x")])
    r = await run(fake)
    assert r.raw["extra"] == "x"


# Review additions (r61)
@pytest.mark.parametrize("field", ["relevance", "urgency", "actionability", "novelty"])
async def test_bool_rubric_invalid(field):
    fake = FakeOllama(chat_replies=[reply(**{field: True}), reply(**{field: True})])
    with pytest.raises(LLMOutputInvalid):
        await run(fake)
    assert len(fake.calls("/api/chat")) == 2


@pytest.mark.parametrize("value", ["true", 1])
async def test_non_bool_exploited_invalid(value):
    fake = FakeOllama(chat_replies=[reply(exploited_in_wild=value)] * 2)
    with pytest.raises(LLMOutputInvalid):
        await run(fake)


@pytest.mark.parametrize("value", [0, 3])
async def test_rubric_bounds_accepted(value):
    fake = FakeOllama(chat_replies=[reply(relevance=value, novelty=value)])
    r = await run(fake)
    assert (r.rubric.relevance, r.rubric.novelty) == (value, value)


async def test_why_too_long_then_valid_not_truncated():
    fake = FakeOllama(chat_replies=[reply(why="b" * 301), VALID])
    r = await run(fake)
    assert r.why == "You run peered VNets."
    assert len(fake.calls("/api/chat")) == 2


async def test_known_focus_not_logged(caplog):
    fake = FakeOllama(chat_replies=[reply(focus="entra-identity")])
    with caplog.at_level(logging.INFO, logger="sidereal.llm.assess"):
        await run(fake)
    assert "unknown focus" not in caplog.text


def test_strip_urls_case_insensitive_and_wrapped():
    assert strip_urls("a HTTPS://X.Y/z b") == "a b"
    assert strip_urls("see <http://a.b/c> and (https://d.e)") == "see and"
    assert strip_urls("a\n\tb") == "a b"


def test_clean_tags_keeps_order_and_exact_limit():
    assert clean_tags(["b", "", " a ", "\t", "y" * 40]) == ("b", "a", "y" * 40)
    assert clean_tags([" " + "z" * 45 + " "]) == ("z" * 40,)


def test_schema_is_new_dict_each_call():
    a = assess_schema(KEYS)
    a["properties"]["focus"]["enum"].append("x")
    a["required"].append("x")
    b = assess_schema(KEYS)
    assert b["properties"]["focus"]["enum"] == ["azure-networking", "entra-identity", "none"]
    assert len(b["required"]) == 9

"""Tests for sidereal.llm.triage (plan §7.2/§7.3)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from sidereal.llm.ollama import LLMOutputInvalid, LLMUnavailable, OllamaClient
from sidereal.llm.triage import (
    MISSING_RELEVANCE,
    TRIAGE_SCHEMA,
    TriageReply,
    batches,
    keeps,
    run_batches,
    triage_batch,
)
from tests.fake_ollama import FakeOllama

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make(fake: Any) -> OllamaClient:
    return OllamaClient(
        "http://ollama.test",
        client=httpx.AsyncClient(transport=fake.transport()),
    )


def render(ids: list[int]) -> tuple[str, str]:
    return ("SYS", "ids=" + ",".join(str(i) for i in ids))


def reply(*pairs: tuple[int, int]) -> dict[str, Any]:
    return {"results": [{"id": i, "relevance": r} for i, r in pairs]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_schema_verbatim():
    expected = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "relevance": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 3,
                        },
                    },
                    "required": ["id", "relevance"],
                },
            },
        },
        "required": ["results"],
    }
    assert TRIAGE_SCHEMA == expected


def test_batches():
    assert batches([1, 2, 3, 4, 5], 2) == [(1, 2), (3, 4), (5,)]
    assert batches([], 3) == []
    assert batches([1, 2], 5) == [(1, 2)]
    with pytest.raises(ValueError, match="batch size must be >= 1"):
        batches([1], 0)


def test_keeps():
    assert keeps(2, 2) is True
    assert keeps(1, 2) is False
    assert keeps(0, 0) is True


def test_validator_accepts():
    parsed = TriageReply.model_validate(reply((1, 3)))
    assert parsed.results[0].id == 1
    assert parsed.results[0].relevance == 3


@pytest.mark.parametrize(
    "case",
    [
        {"results": [{"id": 1, "relevance": 4}]},
        {"results": [{"id": 1, "relevance": -1}]},
        {"results": [{"id": 1, "relevance": "2"}]},
        {"results": [{"id": "1", "relevance": 2}]},
        {"results": [{"id": 1, "relevance": True}]},
        {"results": [{"id": True, "relevance": 2}]},
        {"results": [{"id": 1}]},
        {},
    ],
)
def test_validator_rejects(case):
    with pytest.raises(ValidationError, match="validation error"):
        TriageReply.model_validate(case)


async def test_triage_batch_request():
    fake = FakeOllama(chat_replies=[reply((1, 3), (2, 0))])
    client = make(fake)
    result = await triage_batch(
        client, model="m", system="SYS", user="USR",
        ids=[1, 2], keep_alive="5m", num_ctx=4096,
    )
    assert result.relevance == {1: 3, 2: 0}
    assert result.missing == ()
    assert result.unknown == ()
    assert result.eval_count == 42
    assert result.duration_ms == 1500

    calls = fake.calls("/api/chat")
    assert len(calls) == 1
    body = calls[0]
    assert body["model"] == "m"
    assert body["think"] is False
    assert body["format"] == TRIAGE_SCHEMA
    assert body["keep_alive"] == "5m"
    assert body["options"]["num_ctx"] == 4096
    assert body["messages"][0]["content"] == "SYS"
    assert body["messages"][1]["content"] == "USR"


async def test_triage_batch_missing_unknown_duplicate(caplog):
    fake = FakeOllama(chat_replies=[reply((1, 2), (9, 3), (1, 0), (9, 1), (3, 1))])
    client = make(fake)
    result = await triage_batch(
        client, model="m", system="SYS", user="USR", ids=[1, 2, 3],
    )
    assert result.relevance == {1: 2, 3: 1}
    assert result.missing == (2,)
    assert result.unknown == (9,)

    assert "unknown ids" in caplog.text
    assert "SYS" not in caplog.text


async def test_triage_batch_invalid_twice():
    fake = FakeOllama(chat_replies=["nope", "nope"])
    client = make(fake)
    with pytest.raises(LLMOutputInvalid, match="after one retry"):
        await triage_batch(
            client, model="m", system="SYS", user="USR", ids=[1, 2],
        )
    assert len(fake.calls("/api/chat")) == 2


async def test_run_batches_happy():
    fake = FakeOllama(
        chat_replies=[
            reply((1, 3), (2, 1)),
            reply((3, 2), (4, 0)),
            reply((5, 2)),
        ],
    )
    client = make(fake)
    outcome = await run_batches(
        client, [1, 2, 3, 4, 5],
        render=render, model="m", keep_min=2, batch_size=2,
    )
    assert outcome.relevance == {1: 3, 2: 1, 3: 2, 4: 0, 5: 2}
    assert outcome.kept == (1, 3, 5)
    assert outcome.dropped == (2, 4)
    assert outcome.defaulted == ()
    assert outcome.unfinished == ()
    assert outcome.calls == 3
    assert outcome.eval_count == 126
    assert outcome.duration_ms == 4500

    users = [c["messages"][1]["content"] for c in fake.calls("/api/chat")]
    assert users == ["ids=1,2", "ids=3,4", "ids=5"]


async def test_missing_requeued_once_then_answered():
    fake = FakeOllama(
        chat_replies=[
            reply((1, 3)),
            reply((3, 2), (2, 0)),
        ],
    )
    client = make(fake)
    outcome = await run_batches(
        client, [1, 2, 3],
        render=render, model="m", keep_min=2, batch_size=3,
    )
    assert outcome.relevance == {1: 3, 2: 0, 3: 2}
    assert outcome.defaulted == ()
    assert outcome.calls == 2

    users = [c["messages"][1]["content"] for c in fake.calls("/api/chat")]
    assert users[1] == "ids=2,3"


async def test_missing_twice_defaults_to_one():
    fake = FakeOllama(
        chat_replies=[
            reply((1, 3)),
            reply(),
        ],
    )
    client = make(fake)
    outcome = await run_batches(
        client, [1, 2],
        render=render, model="m", keep_min=1, batch_size=2,
    )
    assert outcome.relevance[2] == MISSING_RELEVANCE == 1
    assert outcome.defaulted == (2,)
    assert outcome.kept == (1, 2)
    assert outcome.calls == 2
    assert len(fake.calls("/api/chat")) == 2


async def test_defaulted_dropped_at_keep_min_two():
    fake = FakeOllama(chat_replies=[reply((1, 3)), reply()])
    outcome = await run_batches(
        make(fake), [1, 2], render=render, model="m", keep_min=2, batch_size=2,
    )
    assert outcome.relevance == {1: 3, 2: 1}
    assert outcome.kept == (1,)
    assert outcome.dropped == (2,)
    assert outcome.defaulted == (2,)


async def test_requeue_batched_in_input_order():
    fake = FakeOllama(
        chat_replies=[
            reply((1, 3)),
            reply((3, 3)),
            reply((2, 2), (4, 2)),
        ],
    )
    client = make(fake)
    outcome = await run_batches(
        client, [1, 2, 3, 4],
        render=render, model="m", keep_min=2, batch_size=2,
    )
    assert outcome.calls == 3

    users = [c["messages"][1]["content"] for c in fake.calls("/api/chat")]
    assert users[2] == "ids=2,4"


async def test_invalid_batch_requeued():
    fake = FakeOllama(
        chat_replies=[
            "nope",
            "nope",
            reply((1, 2), (2, 3)),
        ],
    )
    client = make(fake)
    outcome = await run_batches(
        client, [1, 2],
        render=render, model="m", keep_min=2, batch_size=2,
    )
    assert outcome.invalid_batches == 1
    assert outcome.relevance == {1: 2, 2: 3}
    assert outcome.defaulted == ()
    assert outcome.calls == 2
    assert len(fake.calls("/api/chat")) == 3


async def test_invalid_twice_defaults():
    fake = FakeOllama(chat_replies=["nope"] * 4)
    client = make(fake)
    outcome = await run_batches(
        client, [1],
        render=render, model="m", keep_min=2, batch_size=1,
    )
    assert outcome.invalid_batches == 2
    assert outcome.defaulted == (1,)
    assert outcome.relevance == {1: 1}


async def test_deadline_stops_cleanly():
    calls_made = 0

    def deadline() -> bool:
        nonlocal calls_made
        return calls_made >= 1

    fake = FakeOllama(chat_replies=[reply((1, 2), (2, 2))])
    client = make(fake)

    def counting_render(ids: list[int]) -> tuple[str, str]:
        nonlocal calls_made
        calls_made += 1
        return render(ids)

    outcome = await run_batches(
        client, [1, 2, 3, 4],
        render=counting_render, model="m", keep_min=2, batch_size=2,
        deadline=deadline,
    )
    assert outcome.unfinished == (3, 4)
    assert outcome.relevance == {1: 2, 2: 2}
    assert len(fake.calls("/api/chat")) == 1


async def test_deadline_marks_every_later_batch_unfinished():
    fake = FakeOllama(chat_replies=[reply((1, 0), (2, 3))])
    outcome = await run_batches(
        make(fake), [1, 2, 3, 4, 5], render=render, model="m", keep_min=2,
        batch_size=2, deadline=lambda: len(fake.calls("/api/chat")) >= 1,
    )
    assert outcome.unfinished == (3, 4, 5)
    assert outcome.relevance == {1: 0, 2: 3}
    assert outcome.calls == 1


async def test_deadline_before_requeue():
    renders = 0

    def counting_render(ids):
        nonlocal renders
        renders += 1
        return render(ids)

    fake = FakeOllama(chat_replies=[reply((1, 2))])
    outcome = await run_batches(
        make(fake), [1, 2], render=counting_render, model="m", keep_min=2,
        batch_size=2, deadline=lambda: renders >= 1,
    )
    assert outcome.unfinished == (2,)
    assert outcome.defaulted == ()
    assert 2 not in outcome.relevance
    assert outcome.kept == (1,)
    assert outcome.dropped == ()
    assert outcome.calls == 1
    assert len(fake.calls("/api/chat")) == 1


async def test_deadline_mid_requeue_keeps_rest_unfinished():
    # first pass [1,2] [3,4] leaves 1, 3, 4 missing; second pass [1,3] answers 1 only, then
    # the deadline skips [4]: 3 is defaulted, 4 stays unfinished
    renders = 0

    def counting_render(ids):
        nonlocal renders
        renders += 1
        return render(ids)

    fake = FakeOllama(chat_replies=[reply((2, 2)), reply(), reply((1, 3))])
    outcome = await run_batches(
        make(fake), [1, 2, 3, 4], render=counting_render, model="m", keep_min=2,
        batch_size=2, deadline=lambda: renders >= 3,
    )
    users = [c["messages"][1]["content"] for c in fake.calls("/api/chat")]
    assert users == ["ids=1,2", "ids=3,4", "ids=1,3"]
    assert outcome.relevance == {1: 3, 2: 2, 3: MISSING_RELEVANCE}
    assert outcome.defaulted == (3,)
    assert outcome.unfinished == (4,)
    assert outcome.kept == (1, 2)
    assert outcome.dropped == (3,)


async def test_deadline_checked_before_each_call():
    checks: list[int] = []
    fake = FakeOllama(chat_replies=[reply((1, 1))])

    def deadline():
        checks.append(len(fake.calls("/api/chat")))
        return len(checks) > 1

    outcome = await run_batches(
        make(fake), [1, 2], render=render, model="m", keep_min=2, batch_size=1,
        deadline=deadline,
    )
    assert checks == [0, 1]
    assert outcome.unfinished == (2,)
    assert outcome.dropped == (1,)


async def test_invalid_batch_logs_type_only(caplog):
    fake = FakeOllama(chat_replies=["SECRET reply", "SECRET reply", reply((1, 2))])
    with caplog.at_level("WARNING"):
        await run_batches(
            make(fake), [1], render=lambda ids: ("SYS-TEXT", "USER-TEXT"), model="m",
            keep_min=2, batch_size=1,
        )
    assert "LLMOutputInvalid" in caplog.text
    for secret in ("SECRET", "SYS-TEXT", "USER-TEXT"):
        assert secret not in caplog.text


async def test_default_batch_size_is_fifteen():
    ids = list(range(1, 17))
    fake = FakeOllama(
        chat_replies=[reply(*[(i, 2) for i in ids[:15]]), reply((16, 2))],
    )
    outcome = await run_batches(make(fake), ids, render=render, model="m", keep_min=2)
    users = [c["messages"][1]["content"] for c in fake.calls("/api/chat")]
    assert users == ["ids=" + ",".join(str(i) for i in ids[:15]), "ids=16"]
    assert outcome.kept == tuple(ids)


async def test_bad_batch_size_rejected():
    fake = FakeOllama()
    with pytest.raises(ValueError, match="batch size"):
        await run_batches(make(fake), [1], render=render, model="m", keep_min=2, batch_size=0)
    assert fake.calls("/api/chat") == []


async def test_unavailable_propagates():
    fake = FakeOllama(chat_replies=[])
    client = make(fake)
    with pytest.raises(LLMUnavailable, match="HTTP 500"):
        await run_batches(
            client, [1],
            render=render, model="m", keep_min=2, batch_size=1,
        )


async def test_duplicate_ids_rejected():
    fake = FakeOllama(chat_replies=[reply((1, 2))])
    client = make(fake)
    with pytest.raises(ValueError, match="duplicate ids"):
        await run_batches(
            client, [1, 1, 2],
            render=render, model="m", keep_min=2, batch_size=2,
        )
    assert len(fake.calls("/api/chat")) == 0


async def test_empty_ids():
    fake = FakeOllama()
    client = make(fake)
    outcome = await run_batches(
        client, [],
        render=render, model="m", keep_min=2, batch_size=2,
    )
    assert outcome.relevance == {}
    assert outcome.kept == ()
    assert outcome.dropped == ()
    assert outcome.defaulted == ()
    assert outcome.unfinished == ()
    assert outcome.calls == 0
    assert len(fake.calls("/api/chat")) == 0


async def test_keep_min_respected():
    fake = FakeOllama(chat_replies=[reply((1, 3), (2, 2))])
    client = make(fake)
    outcome = await run_batches(
        client, [1, 2],
        render=render, model="m", keep_min=3, batch_size=2,
    )
    assert outcome.kept == (1,)
    assert outcome.dropped == (2,)

"""Batched relevance triage (plan §7.2/§7.3): the caller renders prompts, code decides keep/drop.

The caller renders prompts (via a ``render`` callback); code, not the model, decides
keep/drop.  Imports: stdlib, pydantic, ``sidereal.llm.ollama`` only (no ``prompts.py``,
no httpx).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, StrictInt

from sidereal.llm.ollama import LLMOutputInvalid, OllamaClient

log = logging.getLogger(__name__)

MISSING_RELEVANCE = 1

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "relevance": {"type": "integer", "minimum": 0, "maximum": 3},
                },
                "required": ["id", "relevance"],
            },
        },
    },
    "required": ["results"],
}


class TriageEntry(BaseModel):
    """Validator mirrors the TRIAGE_SCHEMA items."""

    id: StrictInt
    relevance: StrictInt = Field(ge=0, le=3)


class TriageReply(BaseModel):
    """Validator for the full triage reply."""

    results: list[TriageEntry]


@dataclass(frozen=True)
class BatchResult:
    """Result from a single batch call."""

    relevance: dict[int, int]  # only ids of this batch; first occurrence in the reply wins
    missing: tuple[int, ...]  # batch ids absent from the reply, in batch order
    unknown: tuple[int, ...]  # reply ids not in the batch, in reply order, each once
    eval_count: int
    duration_ms: int  # ChatResult.total_ms


@dataclass(frozen=True)
class TriageOutcome:
    """Outcome from running all batches."""

    relevance: dict[int, int]  # every decided id → 0..3 (defaulted ids → MISSING_RELEVANCE)
    kept: tuple[int, ...]  # decided ids with relevance >= keep_min, in input order
    dropped: tuple[int, ...]  # decided ids with relevance < keep_min, in input order
    defaulted: tuple[int, ...]  # ids that got MISSING_RELEVANCE (missing twice), input order
    unfinished: tuple[int, ...]  # ids never decided because the deadline passed, input order
    calls: int  # triage_batch calls made (incl. ones that raised LLMOutputInvalid)
    invalid_batches: int  # batches whose call raised LLMOutputInvalid
    eval_count: int  # sum over successful calls
    duration_ms: int  # sum over successful calls


def batches(ids: Sequence[int], size: int) -> list[tuple[int, ...]]:
    """Split *ids* into consecutive chunks of *size*; last one shorter."""
    if size < 1:
        raise ValueError("batch size must be >= 1")
    return [tuple(ids[i:i + size]) for i in range(0, len(ids), size)]


def keeps(relevance: int, keep_min: int) -> bool:
    """Return True when *relevance* meets the minimum threshold."""
    return relevance >= keep_min


async def triage_batch(
    client: OllamaClient,
    *,
    model: str,
    system: str,
    user: str,
    ids: Sequence[int],
    keep_alive: str = "10m",
    num_ctx: int = 8192,
) -> BatchResult:
    """Call the LLM for one batch of ids and parse the result."""
    result = await client.chat_json(
        model=model,
        system=system,
        user=user,
        schema=TRIAGE_SCHEMA,
        validator=TriageReply,
        num_ctx=num_ctx,
        keep_alive=keep_alive,
        think=False,
    )

    seen: set[int] = set()
    relevance: dict[int, int] = {}
    unknown: list[int] = []
    batch_set = set(ids)

    for entry in result.parsed.results:  # type: ignore[union-attr]
        eid = entry.id
        if eid in batch_set and eid not in seen:
            seen.add(eid)
            relevance[eid] = entry.relevance
        elif eid not in batch_set and eid not in unknown:
            unknown.append(eid)

    if unknown:
        log.warning("triage: ignored %d unknown ids: %s", len(unknown), list(unknown))

    missing = tuple(i for i in ids if i not in seen)

    return BatchResult(
        relevance=relevance,
        missing=missing,
        unknown=tuple(unknown),
        eval_count=result.eval_count,
        duration_ms=result.total_ms,
    )


async def run_batches(
    client: OllamaClient,
    ids: Sequence[int],
    *,
    render: Callable[[Sequence[int]], tuple[str, str]],
    model: str,
    keep_min: int,
    batch_size: int = 15,
    deadline: Callable[[], bool] | None = None,
    keep_alive: str = "10m",
    num_ctx: int = 8192,
) -> TriageOutcome:
    """Triage *ids* in batches; missing ids are re-queued once, then get MISSING_RELEVANCE."""
    order = list(ids)
    if len(order) != len(set(order)):
        raise ValueError("duplicate ids")
    first = batches(order, batch_size)

    relevance: dict[int, int] = {}
    unfinished: set[int] = set()
    defaulted: set[int] = set()
    calls = invalid = eval_count = duration_ms = 0

    async def one_pass(groups: list[tuple[int, ...]], final: bool) -> list[int]:
        nonlocal calls, invalid, eval_count, duration_ms
        missing: list[int] = []
        for n, batch in enumerate(groups):
            if deadline is not None and deadline():
                for later in groups[n:]:
                    unfinished.update(later)
                break
            system, user = render(batch)
            calls += 1
            try:
                br = await triage_batch(
                    client, model=model, system=system, user=user,
                    ids=batch, keep_alive=keep_alive, num_ctx=num_ctx,
                )
            except LLMOutputInvalid as exc:
                invalid += 1
                log.warning("triage: batch output invalid (%s)", type(exc).__name__)
                missing.extend(batch)
                continue
            relevance.update(br.relevance)
            eval_count += br.eval_count
            duration_ms += br.duration_ms
            missing.extend(br.missing)
        if final:
            for i in missing:
                relevance[i] = MISSING_RELEVANCE
                defaulted.add(i)
        return missing

    requeue = set(await one_pass(first, final=False))
    if requeue:
        await one_pass(batches([i for i in order if i in requeue], batch_size), final=True)

    decided = [i for i in order if i in relevance]
    return TriageOutcome(
        relevance=relevance,
        kept=tuple(i for i in decided if keeps(relevance[i], keep_min)),
        dropped=tuple(i for i in decided if not keeps(relevance[i], keep_min)),
        defaulted=tuple(i for i in order if i in defaulted),
        unfinished=tuple(i for i in order if i in unfinished),
        calls=calls,
        invalid_batches=invalid,
        eval_count=eval_count,
        duration_ms=duration_ms,
    )

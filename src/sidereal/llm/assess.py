"""Per-story assessment call (plan §7.3, §7.4): schema, validator, URL stripping.

The caller renders the assess prompt and passes ``system``/``user``; errors from the client
(``LLMUnavailable``, ``LLMOutputInvalid``) propagate unchanged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, Field, StrictBool

from sidereal.llm.ollama import OllamaClient
from sidereal.pipeline.scoring import Rubric

log = logging.getLogger(__name__)

SUMMARY_MAX = 600
WHY_MAX = 300
TAGS_MAX = 5
TAG_CHARS = 40

_URL = re.compile(r"[(<]?https?://[^\s)>]+[)>]?", re.IGNORECASE)
_SPACES = re.compile(r"\s+")

Score = Annotated[int, Field(ge=0, le=3, strict=True)]


def assess_schema(focus_keys: Sequence[str]) -> dict[str, Any]:
    """Return the assess JSON schema for *focus_keys*."""
    keys = [k for k in focus_keys if k != "none"]
    return {
        "type": "object",
        "properties": {
            "relevance": {"type": "integer", "minimum": 0, "maximum": 3},
            "urgency": {"type": "integer", "minimum": 0, "maximum": 3},
            "actionability": {"type": "integer", "minimum": 0, "maximum": 3},
            "novelty": {"type": "integer", "minimum": 0, "maximum": 3},
            "focus": {"type": "string", "enum": [*keys, "none"]},
            "tags": {"type": "array", "items": {"type": "string"}, "maxItems": TAGS_MAX},
            "exploited_in_wild": {"type": "boolean"},
            "summary": {"type": "string", "maxLength": SUMMARY_MAX},
            "why": {"type": "string", "maxLength": WHY_MAX},
        },
        "required": [
            "relevance",
            "urgency",
            "actionability",
            "novelty",
            "focus",
            "tags",
            "exploited_in_wild",
            "summary",
            "why",
        ],
    }


class AssessReply(BaseModel):
    relevance: Score
    urgency: Score
    actionability: Score
    novelty: Score
    focus: str
    tags: Annotated[list[str], Field(max_length=TAGS_MAX)]
    exploited_in_wild: StrictBool
    summary: Annotated[str, Field(max_length=SUMMARY_MAX)]
    why: Annotated[str, Field(max_length=WHY_MAX)]


@dataclass(frozen=True)
class AssessmentResult:
    rubric: Rubric
    focus: str
    tags: tuple[str, ...]
    summary: str
    why: str
    raw: dict[str, Any]
    duration_ms: int
    eval_count: int


def strip_urls(text: str) -> str:
    """Remove any http/https URLs from *text*, collapsing whitespace."""
    return _SPACES.sub(" ", _URL.sub("", text)).strip()


def clean_tags(tags: Sequence[str]) -> tuple[str, ...]:
    """Strip, truncate to 40 chars, drop empty."""
    return tuple(t.strip()[:TAG_CHARS] for t in tags if t.strip())


async def assess_story(
    client: OllamaClient,
    *,
    model: str,
    system: str,
    user: str,
    focus_keys: Sequence[str],
    keep_alive: str = "10m",
    num_ctx: int = 8192,
) -> AssessmentResult:
    """Assess a single story and return the parsed result."""
    result = await client.chat_json(
        model=model,
        system=system,
        user=user,
        schema=assess_schema(focus_keys),
        validator=AssessReply,
        num_ctx=num_ctx,
        keep_alive=keep_alive,
        think=False,
    )
    reply = result.parsed
    assert isinstance(reply, AssessReply)

    focus = reply.focus if reply.focus in set(focus_keys) | {"none"} else "none"
    if focus != reply.focus:
        log.info("assess %s: unknown focus %r -> none", model, reply.focus[:40])

    return AssessmentResult(
        rubric=Rubric(
            reply.relevance,
            reply.urgency,
            reply.actionability,
            reply.novelty,
            reply.exploited_in_wild,
        ),
        focus=focus,
        tags=clean_tags(reply.tags),
        summary=strip_urls(reply.summary),
        why=strip_urls(reply.why),
        raw=result.content,
        duration_ms=result.total_ms,
        eval_count=result.eval_count,
    )

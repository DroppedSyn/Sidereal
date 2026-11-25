"""Week digest call (M29, prompt ``week_digest.v1``): schema, validator, URL stripping.

Like ``llm.digest`` but the overview is longer (the prompt asks for up to 250 words in one
paragraph per theme), so its cap is larger and paragraphs (blank-line separated) are kept:
``assess.strip_urls`` runs on each paragraph, which also one-lines it. The caller renders
the prompt and persists the result. Client errors propagate unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, Field

from sidereal.llm.assess import strip_urls
from sidereal.llm.ollama import OllamaClient

OVERVIEW_MAX = 2400
HEADLINE_MAX = 160

WEEK_DIGEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "minLength": 1, "maxLength": OVERVIEW_MAX},
        "headline": {"type": "string", "minLength": 1, "maxLength": HEADLINE_MAX},
    },
    "required": ["overview", "headline"],
}

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


class WeekDigestReply(BaseModel):
    overview: Annotated[str, Field(min_length=1, max_length=OVERVIEW_MAX)]
    headline: Annotated[str, Field(min_length=1, max_length=HEADLINE_MAX)]


@dataclass(frozen=True)
class WeekDigestResult:
    overview: str
    headline: str
    raw: dict[str, Any]
    duration_ms: int
    eval_count: int


def clean_overview(text: str) -> str:
    """URLs removed per paragraph, paragraphs joined by one blank line, empty ones dropped."""
    parts = (strip_urls(p) for p in _PARAGRAPH_BREAK.split(text))
    return "\n\n".join(p for p in parts if p)


async def write_week_digest(client: OllamaClient, *, model: str, system: str, user: str,
                            keep_alive: str = "10m", num_ctx: int = 8192) -> WeekDigestResult:
    result = await client.chat_json(
        model=model, system=system, user=user, schema=WEEK_DIGEST_SCHEMA,
        validator=WeekDigestReply, num_ctx=num_ctx, keep_alive=keep_alive, think=False)
    reply = result.parsed
    assert isinstance(reply, WeekDigestReply)
    return WeekDigestResult(
        overview=clean_overview(reply.overview), headline=strip_urls(reply.headline),
        raw=result.content, duration_ms=result.total_ms, eval_count=result.eval_count)

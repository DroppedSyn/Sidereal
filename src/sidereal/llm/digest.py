"""Day digest call (plan §7.3, §7.4): schema, validator, URL stripping.

The caller renders the ``day_digest`` prompt and passes ``system``/``user``, and persists the
result (``db.digests_repo``). URLs are removed with the shared ``assess.strip_urls``. Errors
from the client (``LLMUnavailable``, ``LLMOutputInvalid``) propagate unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, Field

from sidereal.llm.assess import strip_urls
from sidereal.llm.ollama import OllamaClient

OVERVIEW_MAX = 1200
HEADLINE_MAX = 160

DIGEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "minLength": 1, "maxLength": OVERVIEW_MAX},
        "headline": {"type": "string", "minLength": 1, "maxLength": HEADLINE_MAX},
    },
    "required": ["overview", "headline"],
}


class DigestReply(BaseModel):
    overview: Annotated[str, Field(min_length=1, max_length=OVERVIEW_MAX)]
    headline: Annotated[str, Field(min_length=1, max_length=HEADLINE_MAX)]


@dataclass(frozen=True)
class DigestResult:
    overview: str
    headline: str
    raw: dict[str, Any]
    duration_ms: int
    eval_count: int


async def write_digest(
    client: OllamaClient,
    *,
    model: str,
    system: str,
    user: str,
    keep_alive: str = "10m",
    num_ctx: int = 8192,
) -> DigestResult:
    result = await client.chat_json(
        model=model,
        system=system,
        user=user,
        schema=DIGEST_SCHEMA,
        validator=DigestReply,
        num_ctx=num_ctx,
        keep_alive=keep_alive,
        think=False,
    )
    reply = result.parsed
    assert isinstance(reply, DigestReply)
    return DigestResult(
        overview=strip_urls(reply.overview),
        headline=strip_urls(reply.headline),
        raw=result.content,
        duration_ms=result.total_ms,
        eval_count=result.eval_count,
    )

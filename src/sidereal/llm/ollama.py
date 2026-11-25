"""Ollama HTTP client (plan §7.1): JSON-schema chats, loaded-model listing, polite unload.

Errors never carry prompts or reply text: ``LLMUnavailable`` holds the path, the status and
Ollama's ``error`` string; ``LLMOutputInvalid`` holds the model and the failure type.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

RETRY_LINE = "Your previous reply was not valid JSON for the schema. Reply with JSON only."


class LLMError(Exception):
    """Base for LLM-layer failures."""


class LLMUnavailable(LLMError):
    """Ollama unreachable, timed out or returned an HTTP error."""


class LLMOutputInvalid(LLMError):
    """The model's reply was not valid JSON for the schema, twice."""


@dataclass(frozen=True)
class ChatResult:
    content: dict[str, Any]  # the parsed JSON object
    parsed: BaseModel | None  # validator instance, or None when no validator was given
    eval_count: int
    prompt_eval_count: int
    total_ms: int  # total_duration (ns) // 1_000_000


@dataclass(frozen=True)
class LoadedModel:
    name: str
    size_vram: int
    expires_at: str


@dataclass(frozen=True)
class ProbeResult:
    total_ms: int  # total_duration (ns) // 1_000_000
    load_ms: int   # load_duration (ns) // 1_000_000


class _Invalid(Exception):
    """Internal: one reply failed parsing/validation; ``args[0]`` is the reason type name."""


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 300.0,
        never_unload: Iterable[str] = (),
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self._never_unload = frozenset(never_unload)
        if client is None:
            # trust_env=False: Ollama is on the LAN; an HTTP(S)_PROXY in the env must not apply.
            self._client = httpx.AsyncClient(timeout=timeout_s, trust_env=False)
            self._owns_client = True
        else:
            self._client = client
            self._owns_client = False

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            resp = await self._client.request(
                method, self._base + path, json=body,
                timeout=self._timeout if timeout is None else timeout,
            )
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"ollama {path}: timed out ({type(exc).__name__})") from None
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"ollama {path}: unreachable ({type(exc).__name__})") from None
        if not resp.is_success:
            error: str | None = None
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                error = payload["error"]
            if error is None:
                error = resp.text[:200]
            raise LLMUnavailable(f"ollama {path}: HTTP {resp.status_code}: {error}")
        try:
            return resp.json()
        except ValueError:
            raise LLMUnavailable(f"ollama {path}: response is not JSON") from None

    @staticmethod
    def _parse(
        data: Any, validator: type[BaseModel] | None
    ) -> tuple[dict[str, Any], BaseModel | None]:
        message = data.get("message") if isinstance(data, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise _Invalid("MissingContent")
        try:
            obj = json.loads(text)
        except ValueError as exc:
            raise _Invalid(type(exc).__name__) from None
        if not isinstance(obj, dict):
            raise _Invalid(f"NotAnObject:{type(obj).__name__}")
        if validator is None:
            return obj, None
        try:
            return obj, validator.model_validate(obj)
        except ValidationError:
            raise _Invalid("ValidationError") from None

    async def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        validator: type[BaseModel] | None = None,
        num_ctx: int = 8192,
        temperature: float = 0.0,
        keep_alive: str = "10m",
        think: bool = False,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": model,
            "stream": False,
            "think": think,
            "format": schema,
            "options": {"temperature": temperature, "num_ctx": num_ctx},
            "keep_alive": keep_alive,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = await self._request("POST", "/api/chat", body)
        try:
            obj, parsed = self._parse(data, validator)
        except _Invalid as first:
            reason = first.args[0]
            log.info("ollama %s: reply invalid (%s), retrying once", model, reason)
            retry_msg = {"role": "user", "content": RETRY_LINE}
            retry = {**body, "messages": body["messages"] + [retry_msg]}
            data = await self._request("POST", "/api/chat", retry)
            try:
                obj, parsed = self._parse(data, validator)
            except _Invalid as second:
                raise LLMOutputInvalid(
                    f"ollama {model}: reply not valid for the schema after one retry"
                    f" ({second.args[0]})"
                ) from None
        return ChatResult(
            content=obj,
            parsed=parsed,
            eval_count=int(data.get("eval_count", 0)),
            prompt_eval_count=int(data.get("prompt_eval_count", 0)),
            total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        )

    async def ps(self) -> list[LoadedModel]:
        data = await self._request("GET", "/api/ps")
        return [
            LoadedModel(m["name"], int(m.get("size_vram", 0)), str(m.get("expires_at", "")))
            for m in data.get("models", [])
        ]

    async def has_model(self, name: str) -> bool:
        data = await self._request("GET", "/api/tags")
        names = {m.get("name") for m in data.get("models", [])}
        return name in names or f"{name}:latest" in names

    async def unload(self, model: str) -> None:
        if model in self._never_unload:
            log.info("ollama: not unloading protected model %s", model)
            return
        await self._request("POST", "/api/generate", {"model": model, "keep_alive": 0})

    async def probe(self, model: str, *, timeout_s: float, keep_alive: str = "10m") -> ProbeResult:
        """1-token generate used by the GPU gate (plan §7.5)."""
        body = {"model": model, "prompt": "ok", "stream": False, "think": False,
                "keep_alive": keep_alive, "options": {"num_predict": 1}}
        data = await self._request("POST", "/api/generate", body, timeout=timeout_s)
        return ProbeResult(int(data.get("total_duration", 0)) // 1_000_000,
                           int(data.get("load_duration", 0)) // 1_000_000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

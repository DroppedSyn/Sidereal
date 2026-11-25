"""A fake Ollama server for tests: an ``httpx.MockTransport`` handler (plan §14).

Usage::

    fake = FakeOllama(chat_replies=[{"relevance": 2}, "not json"])
    fake.on_chat(lambda body: "triage" in body["messages"][0]["content"], {"items": []})
    fake.errors["/api/ps"] = httpx.ConnectError("refused")
    client = httpx.AsyncClient(transport=fake.transport())
    ...
    assert fake.calls("/api/chat")[0]["model"] == "qwen3.8:27b"

``/api/chat``: rules registered with ``on_chat(match, reply)`` are checked first, in order;
the first whose ``match(body)`` is true answers **every time** (sticky). Otherwise the next
``chat_replies`` item is popped; an empty queue answers 500. A reply is a ``dict`` (sent as
JSON text), a ``str`` (raw content, e.g. invalid JSON), an ``httpx.Response`` (returned as
is), an ``Exception`` instance (raised from the handler, so it reaches the caller) or a
callable ``(body) -> one of those``. Every 200 chat reply carries the stats attributes
``eval_count``, ``prompt_eval_count``, ``total_duration`` (ns), ``load_duration`` and
``eval_duration``; set them to change the next replies.

``/api/tags`` lists ``models``; ``/api/ps`` lists ``loaded`` in Ollama's real shape (an entry
may be a str or a full dict); ``/api/generate`` with ``keep_alive == 0`` removes that model
from ``loaded``. ``errors[path]`` (Response or Exception) answers any path before normal
handling. Every request is recorded in ``requests`` first, including ones that then fail.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

Reply = Any  # dict | str | httpx.Response | Exception | Callable[[dict], ...]


class FakeOllama:
    def __init__(
        self,
        chat_replies: list[Reply] | None = None,
        models: list[str] | None = None,
        loaded: list[str | dict[str, Any]] | None = None,
    ) -> None:
        self.chat_replies: list[Reply] = list(chat_replies or [])
        self.models = list(models or ["qwen3.8:27b", "qwen3.6:35b-a3b-coding"])
        self.loaded: list[str | dict[str, Any]] = list(loaded or [])
        self.requests: list[tuple[str, str, dict[str, Any]]] = []  # (method, path, json body)
        self.errors: dict[str, httpx.Response | Exception] = {}
        self.rules: list[tuple[Callable[[dict[str, Any]], bool], Reply]] = []
        self.eval_count = 42
        self.prompt_eval_count = 420
        self.total_duration = 1_500_000_000
        self.load_duration = 0
        self.eval_duration = 1_000_000_000

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def on_chat(self, match: Callable[[dict[str, Any]], bool], reply: Reply) -> None:
        """Answer every ``/api/chat`` whose body matches with ``reply`` (sticky)."""
        self.rules.append((match, reply))

    def calls(self, path: str) -> list[dict[str, Any]]:
        """JSON bodies of the requests made to ``path``, in order."""
        return [body for _, p, body in self.requests if p == path]

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path in self.errors:
            return self._answer(self.errors[path], body)
        if path == "/api/chat" and request.method == "POST":
            return self._chat(body)
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if path == "/api/ps":
            return httpx.Response(200, json={"models": [self._ps_entry(m) for m in self.loaded]})
        if path == "/api/generate" and request.method == "POST":
            if body.get("keep_alive") == 0:
                self.loaded = [m for m in self.loaded if _name(m) != body.get("model")]
            return httpx.Response(200, json={"model": body.get("model"), "response": "",
                                             "done": True, "load_duration": 0})
        return httpx.Response(404, json={"error": f"fake ollama: no route {path}"})

    @staticmethod
    def _ps_entry(m: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(m, dict):
            return m
        return {"name": m, "model": m, "size": 1000, "size_vram": 1000,
                "expires_at": "2026-11-25T12:10:00Z"}

    def _chat(self, body: dict[str, Any]) -> httpx.Response:
        for match, reply in self.rules:
            if match(body):
                return self._answer(reply, body)
        if not self.chat_replies:
            return httpx.Response(500, json={"error": "fake ollama: no scripted reply left"})
        return self._answer(self.chat_replies.pop(0), body)

    def _answer(self, reply: Reply, body: dict[str, Any]) -> httpx.Response:
        if callable(reply) and not isinstance(reply, (httpx.Response, Exception)):
            reply = reply(body)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={
            "model": body.get("model"),
            "created_at": "2026-11-25T12:00:00Z",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": "stop",
            "total_duration": self.total_duration,
            "load_duration": self.load_duration,
            "prompt_eval_count": self.prompt_eval_count,
            "eval_count": self.eval_count,
            "eval_duration": self.eval_duration,
        })


def _name(m: str | dict[str, Any]) -> str:
    return m if isinstance(m, str) else str(m.get("name", ""))

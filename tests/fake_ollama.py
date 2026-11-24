"""A fake Ollama server for tests: an ``httpx.MockTransport`` handler (plan §14).

Skeleton from M0; M8 extends it (scripted replies per prompt kind, error injection).

    fake = FakeOllama(chat_replies=[{"relevance": 2}, "not json"])
    client = httpx.AsyncClient(transport=fake.transport(), base_url="http://ollama.test")
    ...
    assert fake.calls("/api/chat")[0]["model"] == "qwen3.8:27b"
"""

from __future__ import annotations

import json
from typing import Any

import httpx


class FakeOllama:
    def __init__(
        self,
        chat_replies: list[dict[str, Any] | str] | None = None,
        models: list[str] | None = None,
        loaded: list[str] | None = None,
    ) -> None:
        self.chat_replies: list[dict[str, Any] | str] = list(chat_replies or [])
        self.models = list(models or ["qwen3.8:27b", "qwen3.6:35b-a3b-coding"])
        self.loaded = list(loaded or [])
        self.requests: list[tuple[str, str, dict[str, Any]]] = []  # (method, path, json body)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def calls(self, path: str) -> list[dict[str, Any]]:
        """JSON bodies of the requests made to ``path``, in order."""
        return [body for _, p, body in self.requests if p == path]

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path == "/api/chat" and request.method == "POST":
            return self._chat(body)
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.loaded]})
        if path == "/api/generate" and request.method == "POST":
            if body.get("keep_alive") == 0 and body.get("model") in self.loaded:
                self.loaded.remove(body["model"])
            return httpx.Response(200, json={"model": body.get("model"), "response": "",
                                             "done": True, "load_duration": 0})
        return httpx.Response(404, json={"error": f"fake ollama: no route {path}"})

    def _chat(self, body: dict[str, Any]) -> httpx.Response:
        if not self.chat_replies:
            return httpx.Response(500, json={"error": "fake ollama: no scripted reply left"})
        reply = self.chat_replies.pop(0)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return httpx.Response(200, json={
            "model": body.get("model"),
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": "stop",
            "eval_count": 42,
            "prompt_eval_count": 420,
            "total_duration": 1_500_000_000,
        })

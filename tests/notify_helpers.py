"""Shared helpers for the M28 notification tests: a webhook secret, a Fetcher over a
MockTransport that records requests, and a fake ``smtplib.SMTP``."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from tests.adapter_helpers import fake_resolver

TOKEN = "S3cr3tT0ken-abcdefghijklmnop"
WEBHOOK = f"https://discord.com/api/webhooks/123456/{TOKEN}"
PASSWORD = "smtp-pa55word-xyz"


class Recorder:
    def __init__(self, answer: Callable[[httpx.Request], httpx.Response] | None = None):
        self.requests: list[httpx.Request] = []
        self.answer = answer or (lambda r: httpx.Response(204))
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    def payloads(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def fetcher(self) -> Fetcher:
        async def sleep(s: float) -> None:
            self.sleeps.append(s)

        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return Fetcher(client=client, guard=UrlGuard(resolver=fake_resolver), sleep=sleep)


class FakeSMTP:
    """Stands in for ``smtplib.SMTP`` / ``SMTP_SSL``; every instance lands in ``instances``."""

    instances: list[FakeSMTP] = []
    fail_on: str | None = None  # "login" | "send" | "connect"
    exc: BaseException | None = None

    def __init__(self, host: str, port: int, *, timeout: float, context: Any = None) -> None:
        if FakeSMTP.fail_on == "connect":
            raise FakeSMTP.exc or OSError("connection refused")
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls: list[tuple[str, Any]] = []
        self.messages: list[Any] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> None:
        self.calls.append(("quit", None))

    def starttls(self, *, context: Any) -> None:
        self.calls.append(("starttls", context))

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", (user, password)))
        if FakeSMTP.fail_on == "login":
            raise FakeSMTP.exc  # type: ignore[misc]

    def send_message(self, msg: Any) -> None:
        if FakeSMTP.fail_on == "send":
            raise FakeSMTP.exc  # type: ignore[misc]
        self.calls.append(("send", None))
        self.messages.append(msg)

    @classmethod
    def reset(cls) -> None:
        cls.instances, cls.fail_on, cls.exc = [], None, None

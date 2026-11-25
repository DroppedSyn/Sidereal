"""net/fetch.py ``Fetcher.post_json`` (M28, the Discord webhook's only way out)."""

from __future__ import annotations

import logging

import httpx
import pytest

from sidereal.net.fetch import FetchError, FetchHTTPError, UrlBlocked
from tests.notify_helpers import TOKEN, WEBHOOK, Recorder

DISCORD = ("discord.com", "discordapp.com")


async def test_posts_json_once():
    rec = Recorder(lambda r: httpx.Response(200, json={"id": "1"}))
    resp = await rec.fetcher().post_json(WEBHOOK, {"content": "hi"}, allow_hosts=DISCORD)
    assert resp.status == 200 and resp.content == b'{"id":"1"}'
    assert rec.payloads() == [{"content": "hi"}]
    assert rec.requests[0].method == "POST"


async def test_host_outside_allowlist_is_refused_without_a_request():
    rec = Recorder()
    with pytest.raises(UrlBlocked):
        await rec.fetcher().post_json("https://evil.example/api/webhooks/1/x", {},
                                      allow_hosts=DISCORD)
    assert rec.requests == []


async def test_private_address_is_refused():
    rec = Recorder()
    with pytest.raises(UrlBlocked):
        await rec.fetcher().post_json("http://127.0.0.1/api/webhooks/1/x", {},
                                      allow_hosts=["127.0.0.1"])
    assert rec.requests == []


async def test_redirect_is_not_followed():
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "https://evil.example/"}))
    with pytest.raises(FetchError, match="redirect from discord.com refused"):
        await rec.fetcher().post_json(WEBHOOK, {}, allow_hosts=DISCORD)
    assert len(rec.requests) == 1


async def test_5xx_is_not_retried():
    rec = Recorder(lambda r: httpx.Response(503))
    with pytest.raises(FetchHTTPError) as info:
        await rec.fetcher().post_json(WEBHOOK, {}, allow_hosts=DISCORD)
    assert info.value.status == 503 and len(rec.requests) == 1 and rec.sleeps == []


async def test_429_retry_after_is_honoured_once():
    answers = iter([httpx.Response(429, headers={"retry-after": "1.5"}), httpx.Response(204)])
    rec = Recorder(lambda r: next(answers))
    resp = await rec.fetcher().post_json(WEBHOOK, {"a": 1}, allow_hosts=DISCORD)
    assert resp.status == 204 and rec.sleeps == [1.5] and len(rec.requests) == 2


async def test_connect_error_retried_and_error_names_host_only(caplog):
    caplog.set_level(logging.DEBUG)

    def refuse(r):
        raise httpx.ConnectError("refused")

    rec = Recorder(refuse)
    with pytest.raises(FetchError) as info:
        await rec.fetcher().post_json(WEBHOOK, {}, allow_hosts=DISCORD)
    assert len(rec.requests) == 3
    assert "discord.com" in str(info.value) and TOKEN not in str(info.value)
    assert TOKEN not in caplog.text


async def test_get_still_reports_the_url():
    rec = Recorder(lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    with pytest.raises(FetchError, match="https://discord.com/x"):
        await rec.fetcher().get("https://discord.com/x")


async def test_httpx_request_log_line_has_no_token(caplog):
    caplog.set_level(logging.INFO)
    rec = Recorder(lambda r: httpx.Response(204))
    await rec.fetcher().post_json(WEBHOOK, {}, allow_hosts=DISCORD)
    lines = [r.getMessage() for r in caplog.records if r.name == "httpx"]
    assert lines and "POST https://discord.com/[redacted]" in lines[0]
    assert TOKEN not in caplog.text

"""notify/discord.py (M28): escaping, mention suppression, limits, the webhook URL check and the
POST through ``Fetcher.post_json``."""

from __future__ import annotations

import httpx
import pytest

from sidereal.notify.base import Notice, NotifyError
from sidereal.notify.discord import (
    MAX_DESCRIPTION,
    MAX_EMBEDS,
    MAX_MESSAGE_EMBED_CHARS,
    MAX_TITLE,
    DiscordChannel,
    build_messages,
    check_webhook_url,
    embed_for,
    escape_markdown,
)
from tests.notify_helpers import TOKEN, WEBHOOK, Recorder


def notice(i: int = 1, **kw) -> Notice:
    base = {"story_id": i, "title": f"Story {i}", "url": f"https://news.example/{i}",
            "sources": ("BleepingComputer",), "why": "Matters."}
    return Notice(**{**base, **kw})


@pytest.mark.parametrize(("raw", "escaped"), [
    ("**bold** _it_ ~~s~~", r"\*\*bold\*\* \_it\_ \~\~s\~\~"),
    ("`code` ||spoiler||", r"\`code\` \|\|spoiler\|\|"),
    ("[click](https://evil.example)", r"\[click\]\(https\://evil.example\)"),
    ("@everyone @here <@123> <@&9>", r"\@everyone \@here \<\@123\> \<\@&9\>"),
    ("# Heading\n> quote\n- item", r"\# Heading \> quote \- item"),
    ("back\\slash", r"back\\slash"),
])
def test_escape_markdown(raw, escaped):
    assert escape_markdown(raw) == escaped


def test_every_message_disables_mentions():
    msgs = build_messages([notice(i, title="@everyone hi") for i in range(25)],
                          heading="@here 25 stories")
    assert len(msgs) == 3
    for m in msgs:
        assert m["allowed_mentions"] == {"parse": []}
        assert m["content"].startswith(r"\@here")
    assert build_messages([], heading="x")[0]["allowed_mentions"] == {"parse": []}


def test_feed_text_is_escaped_in_every_field():
    e = embed_for(notice(title="*t*", why="_w_", sources=("`s`",)))
    assert (e["title"], e["description"], e["footer"]["text"]) == (r"\*t\*", r"\_w\_", r"\`s\`")


def test_at_most_ten_embeds_per_message():
    msgs = build_messages([notice(i) for i in range(MAX_EMBEDS + 1)], heading="h")
    assert [len(m["embeds"]) for m in msgs] == [MAX_EMBEDS, 1]


def test_long_fields_are_truncated():
    e = embed_for(notice(title="t" * 1000, why="w" * 10000))
    assert len(e["title"]) == MAX_TITLE and e["title"].endswith("…")
    assert len(e["description"]) <= MAX_DESCRIPTION


def test_truncation_never_leaves_a_dangling_escape():
    e = embed_for(notice(title="a" * (MAX_TITLE - 2) + "***"))
    assert len(e["title"]) <= MAX_TITLE
    body = e["title"].removesuffix("…")
    assert len(body) - len(body.rstrip("\\")) in (0, 2)  # an escape pair or none


def test_message_embed_characters_stay_under_6000():
    big = [notice(i, title="t" * 250, why="w" * 600) for i in range(10)]
    msgs = build_messages(big, heading="h")
    assert len(msgs) >= 2
    for m in msgs:
        total = sum(len(e["title"]) + len(e.get("description", "")) +
                    len(e.get("footer", {}).get("text", "")) for e in m["embeds"])
        assert total <= MAX_MESSAGE_EMBED_CHARS


def test_only_http_links_become_embed_urls():
    assert embed_for(notice(url="javascript:alert(1)")).get("url") is None
    assert embed_for(notice(url="")).get("url") is None
    assert embed_for(notice(url="https://a.example/x"))["url"] == "https://a.example/x"


@pytest.mark.parametrize("url", [
    "http://discord.com/api/webhooks/1/x",
    "https://evil.example/api/webhooks/1/x",
    "https://discord.com.evil.example/api/webhooks/1/x",
    "https://discord.com/other/1/x",
    "not a url",
])
def test_webhook_url_check_refuses(url):
    with pytest.raises(NotifyError) as info:
        check_webhook_url(url)
    assert url not in str(info.value)


def test_webhook_url_check_accepts_both_hosts():
    check_webhook_url(WEBHOOK)
    check_webhook_url("https://discordapp.com/api/webhooks/1/abc")


def test_channel_needs_a_webhook():
    with pytest.raises(NotifyError, match="SIDEREAL_DISCORD_WEBHOOK_URL"):
        DiscordChannel("", Recorder().fetcher())


async def test_send_posts_json_with_mentions_off():
    rec = Recorder()
    await DiscordChannel(WEBHOOK, rec.fetcher()).send([notice(1), notice(2)], heading="2 new")
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == WEBHOOK
    assert req.headers["content-type"] == "application/json"
    assert req.headers["user-agent"].startswith("Sidereal/")
    body = rec.payloads()[0]
    assert body["allowed_mentions"] == {"parse": []}
    assert [e["title"] for e in body["embeds"]] == ["Story 1", "Story 2"]
    assert TOKEN not in repr(DiscordChannel(WEBHOOK, rec.fetcher()))


async def test_send_failure_hides_the_webhook():
    rec = Recorder(lambda r: httpx.Response(500, text=f"boom {r.url}"))
    with pytest.raises(NotifyError) as info:
        await DiscordChannel(WEBHOOK, rec.fetcher()).send([notice()], heading="h")
    assert "500" in str(info.value)
    assert TOKEN not in str(info.value) and info.value.__cause__ is None
    assert len(rec.requests) == 1  # a 5xx POST is not retried (it may have landed)


async def test_send_passes_the_discord_allowlist_to_the_fetcher():
    calls = []

    class Spy:
        async def post_json(self, url, payload, *, allow_hosts):
            calls.append(tuple(allow_hosts))

    await DiscordChannel(WEBHOOK, Spy()).send([notice()], heading="h")
    assert calls == [("discord.com", "discordapp.com")]

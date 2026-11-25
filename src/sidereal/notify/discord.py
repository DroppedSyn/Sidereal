"""Discord channel webhook (M28, plan O10): one JSON POST per batch through
``Fetcher.post_json`` (rule 3: no HTTP client here), host allowlist ``discord.com`` /
``discordapp.com``.

Feed text is untrusted: every text field is escaped for Discord Markdown, ``allowed_mentions``
is ``{"parse": []}`` so nothing can ping ``@everyone``, a role or a user, and every field is cut
to Discord's limits (embed title 256, description 4096, footer 2048, ≤ 10 embeds and ≤ 6000
embed characters per message, content ≤ 2000). The webhook URL is a secret: errors name the
host only.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from sidereal.net.fetch import Fetcher, FetchError, UrlBlocked
from sidereal.notify.base import Notice, NotifyError
from sidereal.textclean import truncate
from sidereal.urls import is_http_url

ALLOWED_HOSTS = ("discord.com", "discordapp.com")
MAX_EMBEDS = 10
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FOOTER = 2048
MAX_CONTENT = 2000
MAX_MESSAGE_EMBED_CHARS = 6000
WHY_CHARS = 600
EMBED_COLOR = 0x2B6CB0
NO_MENTIONS = {"parse": []}

# Markdown and mention syntax: \ * _ ~ ` | > [ ] ( ) < # @ - : and the masked-link brackets.
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]()<#@:-])")
_WS = re.compile(r"\s+")


def escape_markdown(text: str) -> str:
    """One line of text with Discord Markdown/mention characters backslash-escaped."""
    return _MARKDOWN.sub(r"\\\1", _WS.sub(" ", text).strip())


def _cut(text: str, limit: int) -> str:
    """Escape, then cut to ``limit`` without leaving a dangling escape backslash."""
    out = escape_markdown(text)
    if len(out) <= limit:
        return out
    out = out[: limit - 1]
    if out.endswith("\\") and (len(out) - len(out.rstrip("\\"))) % 2:
        out = out[:-1]
    return out + "…"


def check_webhook_url(url: str) -> None:
    """https on an allowed host under ``/api/webhooks/``, else NotifyError (URL not echoed)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        raise NotifyError("discord webhook URL is malformed") from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise NotifyError("discord webhook URL must be https://discord.com/api/webhooks/...")
    if not parts.path.startswith("/api/webhooks/"):
        raise NotifyError("discord webhook URL must be https://discord.com/api/webhooks/...")


def embed_for(n: Notice) -> dict:
    embed: dict = {"title": _cut(n.title, MAX_TITLE), "color": EMBED_COLOR}
    if n.url and is_http_url(n.url):
        embed["url"] = n.url
    if n.why:
        embed["description"] = _cut(truncate(n.why, WHY_CHARS), MAX_DESCRIPTION)
    if n.sources:
        embed["footer"] = {"text": _cut(", ".join(n.sources), MAX_FOOTER)}
    return embed


def _embed_chars(e: dict) -> int:
    footer = e.get("footer", {}).get("text", "")
    return len(e["title"]) + len(e.get("description", "")) + len(footer)


def build_messages(notices: list[Notice], *, heading: str) -> list[dict]:
    """Payloads of ≤ 10 embeds and ≤ 6000 embed characters each; normally one message."""
    messages: list[dict] = []
    embeds: list[dict] = []
    chars = 0
    content = _cut(heading, MAX_CONTENT)
    for n in notices:
        e = embed_for(n)
        size = _embed_chars(e)
        if embeds and (len(embeds) == MAX_EMBEDS or chars + size > MAX_MESSAGE_EMBED_CHARS):
            messages.append({"content": content, "embeds": embeds,
                             "allowed_mentions": NO_MENTIONS})
            embeds, chars = [], 0
        embeds.append(e)
        chars += size
    if embeds or not messages:
        messages.append({"content": content, "embeds": embeds, "allowed_mentions": NO_MENTIONS})
    return messages


class DiscordChannel:
    name = "discord"

    def __init__(self, webhook_url: str, fetcher: Fetcher) -> None:
        if not webhook_url:
            raise NotifyError("discord: SIDEREAL_DISCORD_WEBHOOK_URL is not set")
        check_webhook_url(webhook_url)
        self._url = webhook_url
        self._fetcher = fetcher

    def __repr__(self) -> str:
        return "DiscordChannel()"

    async def send(self, notices: list[Notice], *, heading: str) -> None:
        for payload in build_messages(notices, heading=heading):
            try:
                await self._fetcher.post_json(self._url, payload, allow_hosts=ALLOWED_HOSTS)
            except (FetchError, UrlBlocked) as exc:
                raise NotifyError(f"discord: {type(exc).__name__}: {exc}") from None

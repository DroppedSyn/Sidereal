"""RSS / Atom source adapter (plan §6.1)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, ClassVar

import feedparser

from sidereal.net.fetch import Fetcher
from sidereal.sources.base import (
    FetchResult,
    RawItem,
    SourceBroken,
    SourceLike,
    apply_age_cap,
    newest_first,
    option_regex,
    register,
)
from sidereal.timeutil import entry_published
from sidereal.urls import is_http_url

__all__ = [
    "DEFAULT_ERROR_TITLE_REGEX",
    "FEED_ACCEPT",
    "RssAdapter",
    "check_error_feed",
    "filter_titles",
]

DEFAULT_ERROR_TITLE_REGEX = r"(?i)resource not found|page not found|error"
FEED_ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5"
)
_BOM = b"\xef\xbb\xbf"


@register
class RssAdapter:
    kind: ClassVar[str] = "rss"

    async def fetch(
        self,
        source: SourceLike,
        fetcher: Fetcher,
        now: datetime,
        *,
        max_age_hours: float | None = None,
    ) -> FetchResult:
        resp = await fetcher.get(
            source.url,
            etag=source.etag,
            last_modified=source.last_modified,
            max_bytes=source.options.get("max_bytes"),
            accept=FEED_ACCEPT,
        )
        if resp.not_modified:
            return FetchResult(
                items=[], not_modified=True, etag=resp.etag, last_modified=resp.last_modified
            )
        items, entry_count = self.parse_counted(
            source, resp.content, resp.content_type, now, max_age_hours=max_age_hours
        )
        return FetchResult(items=items, etag=resp.etag, last_modified=resp.last_modified,
                           entry_count=entry_count)

    def parse(
        self,
        source: SourceLike,
        content: bytes,
        content_type: str,
        now: datetime,
        *,
        max_age_hours: float | None = None,
    ) -> list[RawItem]:
        return self.parse_counted(
            source, content, content_type, now, max_age_hours=max_age_hours
        )[0]

    def parse_counted(
        self,
        source: SourceLike,
        content: bytes,
        content_type: str,
        now: datetime,
        *,
        max_age_hours: float | None = None,
    ) -> tuple[list[RawItem], int]:
        """Selected items and the feed's own entry count (before any filter or cap)."""
        # bytes only: feedparser treats a str as a URL or file path and would fetch it itself.
        if not isinstance(content, bytes):
            raise TypeError("feed content must be bytes")
        parsed = feedparser.parse(content)
        check_error_feed(source, parsed, content, content_type)
        items = [it for e in parsed.entries if (it := self.make_item(source, e, now)) is not None]
        return self.select(source, items, now, max_age_hours), len(parsed.entries)

    def make_item(
        self, source: SourceLike, entry: Mapping[str, Any], now: datetime
    ) -> RawItem | None:
        url = (entry.get("link") or "").strip()
        if not is_http_url(url):
            return None
        content = entry.get("content")
        first_content = content[0].get("value", "") if content else ""
        return RawItem(
            source_key=source.key,
            guid=(entry.get("id") or "").strip() or url,
            url=url,
            title=(entry.get("title") or "").strip(),
            published=entry_published(entry, now),
            author=entry.get("author") or None,
            excerpt_html=entry.get("summary") or first_content or "",
            extra={},
        )

    def select(
        self,
        source: SourceLike,
        items: list[RawItem],
        now: datetime,
        max_age_hours: float | None,
    ) -> list[RawItem]:
        """rss: title include/exclude → age cap → newest `max_items`."""
        items = filter_titles(items, source)
        items = apply_age_cap(items, now, max_age_hours)
        return newest_first(items, source.max_items)


def _looks_like_html(content: bytes, content_type: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = content[:512].lstrip()
    if head.startswith(_BOM):
        head = head[len(_BOM) :].lstrip()
    head = head.lower()
    return head.startswith((b"<!doctype html", b"<html"))


def check_error_feed(source: SourceLike, parsed: Any, content: bytes, content_type: str) -> None:
    """With 0 entries: an error-looking channel title, or an unparseable HTML page →
    SourceBroken. A well-formed feed with 0 entries is just quiet."""
    if len(parsed.entries) > 0:
        return
    title = parsed.feed.get("title") or ""
    error_re = option_regex(source, "error_title_regex", DEFAULT_ERROR_TITLE_REGEX)
    if error_re is not None and error_re.search(title):
        raise SourceBroken(f"{source.key}: error feed (title {title!r})")
    if parsed.bozo and _looks_like_html(content, content_type):
        raise SourceBroken(f"{source.key}: HTML page, not a feed")


def filter_titles(items: list[RawItem], source: SourceLike) -> list[RawItem]:
    """options.include_regex keeps only matching titles; options.exclude_regex drops matches."""
    include = option_regex(source, "include_regex")
    exclude = option_regex(source, "exclude_regex")
    return [
        it
        for it in items
        if (include is None or include.search(it.title))
        and (exclude is None or not exclude.search(it.title))
    ]

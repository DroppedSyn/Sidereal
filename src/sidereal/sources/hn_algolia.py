"""Hacker News Algolia search adapter (plan §6.1)."""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from sidereal.net.fetch import Fetcher
from sidereal.sources.base import (
    FetchResult,
    RawItem,
    SourceBroken,
    SourceLike,
    apply_age_cap,
    newest_first,
    register,
)
from sidereal.urls import is_http_url

JSON_ACCEPT = "application/json"
DEFAULT_MIN_POINTS = 40
DEFAULT_WINDOW_HOURS = 96
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"


@register
class HnAlgoliaAdapter:
    kind: ClassVar[str] = "hn_algolia"

    async def fetch(
        self,
        source: SourceLike,
        fetcher: Fetcher,
        now: datetime,
        *,
        max_age_hours: float | None = None,
    ) -> FetchResult:
        queries, min_points = hn_options(source)
        hours = DEFAULT_WINDOW_HOURS if max_age_hours is None else max_age_hours
        since = int((now - timedelta(hours=hours)).timestamp())
        merged: dict[str, RawItem] = {}
        for query in queries:
            resp = await fetcher.get(
                search_url(source.url, query, min_points, since),
                max_bytes=source.options.get("max_bytes"),
                accept=JSON_ACCEPT,
            )
            for item in parse_hits(source, resp.content):
                merged.setdefault(item.guid, item)
        items = apply_age_cap(list(merged.values()), now, max_age_hours)
        items = newest_first(items, source.max_items)
        return FetchResult(items=items, entry_count=len(merged))


def hn_options(source: SourceLike) -> tuple[list[str], int]:
    queries = source.options.get("queries")
    if (
        not isinstance(queries, list)
        or len(queries) == 0
        or not all(isinstance(q, str) and q for q in queries)
    ):
        raise ValueError(f"{source.key}: options.queries must be a non-empty list of strings")
    min_points = source.options.get("min_points", DEFAULT_MIN_POINTS)
    if isinstance(min_points, bool) or not isinstance(min_points, int):
        raise ValueError(f"{source.key}: options.min_points must be an integer")
    return queries, min_points


def search_url(base: str, query: str, min_points: int, since_epoch: int) -> str:
    return (
        base
        + "?"
        + urllib.parse.urlencode(
            {
                "query": query,
                "tags": "story",
                "numericFilters": f"points>={min_points},created_at_i>{since_epoch}",
            }
        )
    )


def parse_hits(source: SourceLike, content: bytes) -> list[RawItem]:
    try:
        data = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceBroken(f"{source.key}: not JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
        raise SourceBroken(f"{source.key}: no hits list")
    return [item for hit in data["hits"] if (item := hit_item(source, hit)) is not None]


def hit_item(source: SourceLike, hit: Any) -> RawItem | None:
    if not isinstance(hit, dict):
        return None
    object_id = str(hit.get("objectID") or "").strip()
    if not object_id:
        return None
    title = str(hit.get("title") or "").strip()
    if not title:
        return None
    item_link = HN_ITEM_URL.format(id=object_id)
    story = hit.get("url")
    if isinstance(story, str) and is_http_url(story.strip()):
        url = story.strip()
    else:
        url = item_link
    created = hit.get("created_at_i")
    if isinstance(created, int) and not isinstance(created, bool):
        published = datetime.fromtimestamp(created, UTC)
    else:
        published = None
    points = _int_or_zero(hit.get("points"))
    num_comments = _int_or_zero(hit.get("num_comments"))
    return RawItem(
        source_key=source.key,
        guid=f"hn:{object_id}",
        url=url,
        title=title,
        published=published,
        author=hit.get("author") or None,
        excerpt_html=hit.get("story_text") or "",
        extra={
            "hn_points": points,
            "hn_comments": num_comments,
            "hn_url": item_link,
        },
    )


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0

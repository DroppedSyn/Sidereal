"""Source adapter interface (plan §6.1): RawItem, FetchResult, SourceAdapter, REGISTRY."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Protocol

from sidereal.net.fetch import Fetcher


class SourceBroken(Exception):
    """The source answers, but with an error page or HTML instead of a feed (health 'broken')."""


class SourceLike(Protocol):
    """What adapters read from a source row (db SourceRow satisfies it)."""

    key: str
    url: str
    max_items: int
    options: dict[str, Any]
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class RawItem:
    source_key: str
    guid: str | None
    url: str
    title: str
    published: datetime | None  # aware, UTC
    author: str | None
    excerpt_html: str  # raw; textclean runs later
    extra: dict[str, Any]  # adapter-specific, e.g. {"cve_ids": [...], "kev": True}


@dataclass(frozen=True)
class FetchResult:
    items: list[RawItem]
    not_modified: bool = False
    etag: str | None = None
    last_modified: str | None = None


class SourceAdapter(Protocol):
    kind: ClassVar[str]

    async def fetch(
        self,
        source: SourceLike,
        fetcher: Fetcher,
        now: datetime,
        *,
        max_age_hours: float | None = None,
    ) -> FetchResult: ...


REGISTRY: dict[str, type[SourceAdapter]] = {}


def register[T: type](cls: T) -> T:
    """Class decorator: REGISTRY[cls.kind] = cls. A kind taken by another class → ValueError."""
    kind = cls.kind  # type: ignore[attr-defined]
    existing = REGISTRY.get(kind)
    if existing is not None and existing is not cls:
        raise ValueError(f"source kind {kind!r} already registered to {existing.__name__}")
    REGISTRY[kind] = cls  # type: ignore[assignment]
    return cls


def option_regex(
    source: SourceLike, name: str, default: str | None = None
) -> re.Pattern[str] | None:
    """Compile `source.options[name]` (or `default` when missing/empty); None when neither.
    A bad pattern raises ValueError naming the source and the option."""
    pattern = source.options.get(name) or default
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except (re.error, TypeError) as exc:
        raise ValueError(f"{source.key}: invalid options.{name} {pattern!r}: {exc}") from exc


def apply_age_cap(
    items: list[RawItem], now: datetime, max_age_hours: float | None
) -> list[RawItem]:
    """None → all items; else keep undated items and those at or after now - max_age_hours."""
    if max_age_hours is None:
        return list(items)
    cutoff = now - timedelta(hours=max_age_hours)
    return [it for it in items if it.published is None or it.published >= cutoff]


_UNDATED = datetime.min.replace(tzinfo=UTC)


def newest_first(items: list[RawItem], limit: int) -> list[RawItem]:
    """Stable sort newest first (undated last, ties in feed order), then the first `limit`."""
    ordered = sorted(items, key=lambda it: it.published or _UNDATED, reverse=True)
    return ordered[:limit]

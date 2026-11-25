"""Article text enrichment — fetch article pages, extract main text (plan §6.2).

No DB access (the runner, M13, persists outcomes via ``items_repo.set_content``).
All network access goes through the ``Fetcher`` which runs the SSRF guard on every hop.
"""

from __future__ import annotations

import asyncio
import codecs
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

with warnings.catch_warnings():  # trafilatura pulls in urllib3's SOCKS module; never used
    warnings.filterwarnings("ignore", message="SOCKS support in urllib3")
    import trafilatura

from sidereal.net.fetch import (
    Fetcher,
    FetchError,
    FetchHTTPError,
    UrlBlocked,
)
from sidereal.textclean import to_text, truncate

__all__ = [
    "ACCEPT",
    "ARTICLE_MAX_BYTES",
    "ERROR_MAX_CHARS",
    "HTML_TYPES",
    "STATUSES",
    "ArticleTarget",
    "EnrichOutcome",
    "allowlist_for",
    "charset_of",
    "extract_text",
    "enrich_many",
    "enrich_one",
]

STATUSES: tuple[str, ...] = ("ok", "blocked", "failed", "skipped")
ARTICLE_MAX_BYTES: int = 2_000_000
MAX_CHARS: int = 20_000
ERROR_MAX_CHARS: int = 200
HTML_TYPES: tuple[str, ...] = ("text/html", "application/xhtml+xml")
ACCEPT: str = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1"


@dataclass(frozen=True)
class ArticleTarget:
    item_id: int
    url: str
    source_key: str
    allow_hosts: tuple[str, ...]


@dataclass(frozen=True)
class EnrichOutcome:
    item_id: int
    status: str  # one of STATUSES
    text: str | None  # set only when status == "ok"
    error: str | None  # None only when status == "ok"


def allowlist_for(options: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract the article-host allowlist from a source's options dict.

    Returns a deduplicated, first-order tuple of lowercased, stripped host
    names (trailing dots removed).  Non-str entries are skipped.
    """
    raw = options.get("article_hosts")
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ValueError("options.article_hosts must be a list of host names")
    seen: dict[str, None] = {}
    for entry in raw:
        if not isinstance(entry, str):
            continue
        h = entry.strip().lower().rstrip(".")
        if h:
            seen[h] = None
    return tuple(seen.keys())


def charset_of(content_type: str) -> str | None:
    """Extract the charset from a ``Content-Type`` header value.

    Splits on ``;``, finds the ``charset`` parameter (case-insensitive name),
    strips spaces and quotes, returns lowercase.  ``None`` if absent.
    """
    if not content_type:
        return None
    for part in content_type.split(";"):
        name, _, value = part.partition("=")
        if name.strip().lower() == "charset":
            return value.strip().strip('"').strip("'").lower()
    return None


def extract_text(
    html: bytes | str,
    *,
    charset: str | None = None,
    max_chars: int = MAX_CHARS,
) -> str | None:
    """Extract article text from HTML bytes.

    Decodes with *charset* if known, else utf-8 (with ``replace``).
    Calls ``trafilatura.extract`` inside a ``try/except`` (never raises).
    Returns the cleaned, truncated plain text or ``None``.
    """
    if not html:
        return None
    # Decode bytes if needed.
    if isinstance(html, bytes):
        html = _decode(html, charset)
    # trafilatura.extract never raises on bad input, but wrap anyway.
    try:
        out = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            output_format="txt",
        )
    except Exception:
        return None
    if out is None:
        return None
    cleaned = to_text(out).strip()
    if not cleaned:
        return None
    return truncate(cleaned, max_chars)


async def enrich_one(
    target: ArticleTarget,
    fetcher: Fetcher,
    *,
    max_bytes: int = ARTICLE_MAX_BYTES,
    max_chars: int = MAX_CHARS,
) -> EnrichOutcome:
    """Fetch one article page and extract its text.

    Returns an ``EnrichOutcome`` with status ``ok``, ``blocked``, ``failed``
    or ``skipped``.
    """
    # 1. Empty allowlist → skip immediately.
    if not target.allow_hosts:
        return EnrichOutcome(
            item_id=target.item_id,
            status="skipped",
            text=None,
            error="NoAllowlist: source has no article_hosts",
        )
    # 2. Fetch.
    try:
        resp = await fetcher.get(
            target.url,
            max_bytes=max_bytes,
            accept=ACCEPT,
            allow_hosts=target.allow_hosts,
        )
    except UrlBlocked as exc:
        return EnrichOutcome(
            item_id=target.item_id,
            status="blocked",
            text=None,
            error=_cut(f"UrlBlocked: {exc.reason}"),
        )
    except FetchHTTPError as exc:
        return EnrichOutcome(
            item_id=target.item_id,
            status="failed",
            text=None,
            error=_cut(f"FetchHTTPError: HTTP {exc.status}"),
        )
    except FetchError as exc:  # FetchTooLarge and the rest
        return EnrichOutcome(
            item_id=target.item_id,
            status="failed",
            text=None,
            error=_cut(f"{type(exc).__name__}: {exc}"),
        )
    # 3. Check content type.
    media = resp.content_type.split(";")[0].strip().lower()
    if media not in HTML_TYPES:
        return EnrichOutcome(
            item_id=target.item_id,
            status="failed",
            text=None,
            error=_cut(f"NotHtml: {media or '(none)'}"),
        )
    # 4. Extract text in a thread.
    text = await asyncio.to_thread(
        extract_text,
        resp.content,
        charset=charset_of(resp.content_type),
        max_chars=max_chars,
    )
    if text is None:
        return EnrichOutcome(
            item_id=target.item_id,
            status="failed",
            text=None,
            error="NoText: no article text extracted",
        )
    return EnrichOutcome(
        item_id=target.item_id,
        status="ok",
        text=text,
        error=None,
    )


async def enrich_many(
    targets: Sequence[ArticleTarget],
    fetcher: Fetcher,
    *,
    concurrency: int = 4,
    deadline: Callable[[], bool] | None = None,
    max_bytes: int = ARTICLE_MAX_BYTES,
    max_chars: int = MAX_CHARS,
) -> list[EnrichOutcome]:
    """Fetch many articles concurrently.

    * ``concurrency < 1`` raises ``ValueError``.
    * A semaphore gates parallel requests.
    * Each task checks ``deadline`` first (when given); if true, the task
      returns ``skipped`` without making a request.
    * Results are returned in input order.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")

    semaphore = asyncio.Semaphore(concurrency)

    async def _task(idx: int, tgt: ArticleTarget) -> EnrichOutcome:
        async with semaphore:
            # Check deadline before fetching.
            if deadline is not None and deadline():
                return EnrichOutcome(
                    item_id=tgt.item_id,
                    status="skipped",
                    text=None,
                    error="Deadline: run time budget reached",
                )
            return await enrich_one(tgt, fetcher, max_bytes=max_bytes, max_chars=max_chars)

    tasks = [_task(i, t) for i, t in enumerate(targets)]
    return await asyncio.gather(*tasks)


def _decode(data: bytes, charset: str | None) -> str:
    """Decode with *charset* if it is a usable text codec, else utf-8; never raises.

    A server-chosen charset can name a codec that fails even with ``errors="replace"``
    (``idna``, ``undefined``) or a bytes-to-bytes codec (``hex``, ``zlib``): utf-8 then.
    """
    if charset:
        try:
            codecs.lookup(charset)
            return data.decode(charset, errors="replace")
        except (LookupError, UnicodeError, ValueError, TypeError):
            pass
    return data.decode("utf-8", errors="replace")


def _cut(text: str) -> str:
    """Cut an error string to ``ERROR_MAX_CHARS`` (callers never put page content in it)."""
    return text[:ERROR_MAX_CHARS]

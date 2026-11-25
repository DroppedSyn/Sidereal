"""Full-text search over stories (M26): the ``story_search`` FTS5 table from ``0004_search``.

User input never reaches FTS5 as syntax: ``fts_query`` turns it into quoted terms (implicit
AND), so ``"``, ``*``, ``:``, ``(``, ``OR``, ``NEAR`` and column filters are plain words.
A trailing ``*`` on a word of 2+ letters/digits becomes a prefix query (``"ent"*``).

Snippets mark matches with the control characters ``HIT_START`` (U+0002) and ``HIT_END``
(U+0003). Stored text never contains control characters (``textclean`` turns them into
spaces), and the front end splits on them and renders every piece as text, never HTML.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

HIT_START = "\x02"
HIT_END = "\x03"
MAX_TERMS = 16
MAX_TERM_CHARS = 64

_WORD_CHAR = re.compile(r"[^\W_]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

# bm25 column weights: title 10, summary 5, why 2, tags 4, excerpt 1. Snippet: best column,
# up to 24 tokens, "…" where text was cut.
_SEARCH_SQL = (
    "SELECT story_search.rowid AS story_id,"
    " bm25(story_search, 10.0, 5.0, 2.0, 4.0, 1.0) AS rank,"
    " snippet(story_search, -1, char(2), char(3), '…', 24) AS snippet"
    " FROM story_search JOIN stories AS s ON s.id = story_search.rowid"
    " WHERE story_search MATCH ?"
    " AND (s.bucket IS NOT NULL OR s.state = 'assess_failed')"
    " AND NOT EXISTS (SELECT 1 FROM feedback AS fb WHERE fb.story_id = s.id"
    " AND fb.kind = 'hide')"
    " AND (? IS NULL OR s.id < ?)"
    " ORDER BY s.id DESC LIMIT ?"
)


class SearchQueryError(ValueError):
    """FTS5 refused the query (should not happen after ``fts_query``); the API answers 400."""


@dataclass(frozen=True)
class SearchHit:
    story_id: int
    rank: float  # FTS5 bm25 with column weights; lower (more negative) = better
    snippet: str  # plain text, matches between HIT_START and HIT_END


def fts_query(text: str) -> str | None:
    """User text → a safe FTS5 query of quoted terms, or None when nothing searchable is
    left. Quotes inside a word are dropped; words without a letter or digit are skipped;
    at most ``MAX_TERMS`` words of ``MAX_TERM_CHARS`` characters each."""
    terms: list[str] = []
    for raw in _CONTROL.sub(" ", text).split():
        prefix = raw.endswith("*")
        word = raw.replace('"', "").replace("*", "")[:MAX_TERM_CHARS]
        letters = len(_WORD_CHAR.findall(word))
        if letters == 0:
            continue
        terms.append(f'"{word}"' + ("*" if prefix and letters >= 2 else ""))
        if len(terms) == MAX_TERMS:
            break
    return " ".join(terms) if terms else None


def search(conn: sqlite3.Connection, text: str, *, limit: int = 20,
           before: int | None = None) -> list[SearchHit]:
    """Visible, not hidden stories matching *text*, newest first (story id descending);
    *before* is an exclusive story-id cursor. Nothing searchable → ``[]``."""
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit!r}")
    query = fts_query(text)
    if query is None:
        return []
    try:
        rows = conn.execute(_SEARCH_SQL, (query, before, before, limit)).fetchall()
    except sqlite3.OperationalError as exc:
        raise SearchQueryError("invalid search query") from exc
    return [SearchHit(story_id=r["story_id"], rank=float(r["rank"]), snippet=r["snippet"] or "")
            for r in rows]

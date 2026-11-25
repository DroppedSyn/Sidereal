"""Story dedupe and clustering (plan §6.7). Pure: no DB, no I/O.

The caller (M13) loads the recent stories (72 h window via ``recent_stories(since)``), turns
them and the run's new items into ``KnownStory`` / ``NewItem`` and applies the assignments.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence, Set
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

JACCARD_MIN = 0.6
MIN_TOKENS = 4
MAX_STORY_CVES = 3
ROLLUP_MIN_ITEMS = 5
STOP_WORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or "
    "that the this to was were what why will with".split()
)


@dataclass(frozen=True)
class NewItem:
    key: int  # the caller's index
    source_key: str
    guid: str | None
    canonical_url: str
    title: str
    cve_ids: tuple[str, ...] = ()
    published: datetime | None = None
    is_msrc: bool = False


@dataclass(frozen=True)
class KnownStory:
    story_id: int
    title_norms: tuple[str, ...]
    cve_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assignment:
    item_key: int
    kind: Literal["duplicate", "existing", "new"]
    story_id: int | None = None
    new_group: int | None = None
    rollup_date: date | None = None


def normalize_title(title: str) -> str:
    """NFKC, lowercase, apostrophes deleted, other punctuation → space, stop words dropped,
    trailing plural ``s`` stripped (len > 3, not ``ss``)."""
    t = unicodedata.normalize("NFKC", title).lower()
    t = t.replace("'", "").replace("’", "")
    t = "".join(c if c.isalnum() or c.isspace() else " " for c in t)
    out = []
    for tok in t.split():
        if tok in STOP_WORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return " ".join(out)


def title_tokens(title_norm: str) -> frozenset[str]:
    return frozenset(title_norm.split())


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def rollup_title(day: date, n_cves: int) -> str:
    return f"Microsoft security updates: {day.isoformat()} ({n_cves} CVEs)"


@dataclass
class _Cluster:
    """A known story (``ident`` = story_id) or an open batch group (``ident`` = group number)."""

    ident: int
    token_sets: list[frozenset[str]] = field(default_factory=list)
    cve_ids: set[str] = field(default_factory=set)


def _match(tokens: frozenset[str], cves: tuple[str, ...], clusters: list[_Cluster]) -> int | None:
    """Rule 3 (CVE) then rule 4 (title) against ``clusters``; ties → lowest ident."""
    ordered = sorted(clusters, key=lambda c: c.ident)
    if cves:
        for c in ordered:
            if len(c.cve_ids) <= MAX_STORY_CVES and not c.cve_ids.isdisjoint(cves):
                return c.ident
    if len(tokens) < MIN_TOKENS:
        return None
    best_ident, best_score = None, 0.0
    for c in ordered:
        score = max(
            (jaccard(tokens, ts) for ts in c.token_sets if len(ts) >= MIN_TOKENS), default=0.0
        )
        if score >= JACCARD_MIN and score > best_score:
            best_ident, best_score = c.ident, score
    return best_ident


def assign_stories(
    items: Sequence[NewItem],
    known: Sequence[KnownStory],
    *,
    known_urls: Set[str] = frozenset(),
    known_guids: Set[tuple[str, str]] = frozenset(),
) -> list[Assignment]:
    """One Assignment per item, in input order. Precedence: duplicate → MSRC roll-up (closed
    group) → CVE vs known → title vs known → same rules vs this batch's groups → new group."""
    # 1. duplicates: against known urls/guids and earlier items of this batch
    seen_urls = set(known_urls)
    seen_guids = set(known_guids)
    dup: set[int] = set()
    for i, it in enumerate(items):
        gkey = (it.source_key, it.guid) if it.guid is not None else None
        if it.canonical_url in seen_urls or (gkey is not None and gkey in seen_guids):
            dup.add(i)
        seen_urls.add(it.canonical_url)
        if gkey is not None:
            seen_guids.add(gkey)

    # 2. MSRC roll-up, decided up front over the non-duplicate items
    by_day: dict[date, list[int]] = {}
    for i, it in enumerate(items):
        if i not in dup and it.is_msrc and it.published is not None:
            by_day.setdefault(it.published.astimezone(UTC).date(), []).append(i)
    rollup_of: dict[int, date] = {
        i: day for day, idx in by_day.items() if len(idx) >= ROLLUP_MIN_ITEMS for i in idx
    }

    known_clusters = [
        _Cluster(k.story_id, [title_tokens(n) for n in k.title_norms], set(k.cve_ids))
        for k in known
    ]
    groups: list[_Cluster] = []  # open batch groups; roll-up groups never go in here
    rollup_group: dict[date, int] = {}
    next_group = 0
    out: list[Assignment] = []
    for i, it in enumerate(items):
        if i in dup:
            out.append(Assignment(it.key, "duplicate"))
            continue
        day = rollup_of.get(i)
        if day is not None:
            if day not in rollup_group:
                rollup_group[day] = next_group
                next_group += 1
            out.append(Assignment(it.key, "new", new_group=rollup_group[day], rollup_date=day))
            continue
        tokens = title_tokens(normalize_title(it.title))
        sid = _match(tokens, it.cve_ids, known_clusters)
        if sid is not None:
            out.append(Assignment(it.key, "existing", story_id=sid))
            continue
        gid = _match(tokens, it.cve_ids, groups)
        if gid is None:
            gid = next_group
            next_group += 1
            groups.append(_Cluster(gid))
        group = next(g for g in groups if g.ident == gid)
        group.token_sets.append(tokens)
        group.cve_ids.update(it.cve_ids)
        out.append(Assignment(it.key, "new", new_group=gid))
    return out

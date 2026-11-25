"""Prefilter (plan §6.8): drop muted/stale candidates, always-keep the obvious ones, queue the rest
for triage ordered by hint score within age bands (§7.2)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

TIER_WEIGHTS: dict[str, int] = {"primary": 3, "secondary": 2, "side": 1}
TRUSTED_WEIGHT: float = 1.3
AGE_BANDS_HOURS: tuple[int, int] = (12, 48)

REASONS: tuple[str, ...] = (
    "muted_source",
    "muted_keyword",
    "too_old",
    "kev_microsoft",
    "trusted_source",
    "primary_keyword",
    "triage",
)


@dataclass(frozen=True)
class FocusArea:
    key: str
    tier: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Mutes:
    sources: frozenset[str] = field(default_factory=frozenset)
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    story_id: int
    title: str
    source_keys: tuple[str, ...]
    max_source_weight: float
    published: datetime | None
    first_seen: datetime
    kev_vendor: str | None = None


@dataclass(frozen=True)
class Decision:
    keep: bool
    always: bool
    reason: str
    hint_score: int
    focus_hits: tuple[str, ...]


@lru_cache(maxsize=128)
def keyword_pattern(keyword: str) -> re.Pattern[str]:
    kw = re.escape(keyword.lower())
    pat = f"(?<![a-z0-9]){kw}"
    if len(keyword) <= 4 and keyword[-1].isalnum():
        pat += r"s?(?![a-z0-9])"
    return re.compile(pat)


def match_keywords(title: str, focus_areas: Sequence[FocusArea]) -> dict[str, int]:
    lower = title.lower()
    result: dict[str, int] = {}
    for area in focus_areas:
        hits = 0
        for kw in dict.fromkeys(area.keywords):
            if keyword_pattern(kw).search(lower):
                hits += 1
        if hits > 0:
            result[area.key] = hits
    return result


def _hint_score(focus_hits: dict[str, int], focus_areas: Sequence[FocusArea]) -> int:
    score = 0
    for area in focus_areas:
        if area.key in focus_hits:
            score += TIER_WEIGHTS[area.tier] * focus_hits[area.key]
    return score


def prefilter(
    c: Candidate,
    focus_areas: Sequence[FocusArea],
    mutes: Mutes,
    *,
    now: datetime,
    max_age_hours: int,
) -> Decision:
    focus_hits = match_keywords(c.title, focus_areas)
    hint = _hint_score(focus_hits, focus_areas)
    hit_keys = tuple(focus_hits)

    # 1. muted_source
    if c.source_keys and all(k in mutes.sources for k in c.source_keys):
        return Decision(False, False, "muted_source", hint, hit_keys)

    # 2. muted_keyword
    lower = c.title.lower()
    if any(keyword_pattern(kw).search(lower) for kw in mutes.keywords):
        return Decision(False, False, "muted_keyword", hint, hit_keys)

    # 3. too_old
    if _age_hours(c, now) > max_age_hours:
        return Decision(False, False, "too_old", hint, hit_keys)

    # 4. kev_microsoft
    if c.kev_vendor is not None and c.kev_vendor.strip().lower() == "microsoft":
        return Decision(True, True, "kev_microsoft", hint, hit_keys)

    # 5. trusted_source
    if c.max_source_weight >= TRUSTED_WEIGHT:
        return Decision(True, True, "trusted_source", hint, hit_keys)

    # 6. primary_keyword
    for area in focus_areas:
        if area.tier == "primary" and area.key in focus_hits:
            return Decision(True, True, "primary_keyword", hint, hit_keys)

    # 7. triage
    return Decision(True, False, "triage", hint, hit_keys)


def _age_hours(c: Candidate, now: datetime) -> float:
    ref = c.published or c.first_seen
    return (now - ref).total_seconds() / 3600


def age_band(c: Candidate, *, now: datetime) -> int:
    age_h = _age_hours(c, now)
    if age_h >= AGE_BANDS_HOURS[1]:
        return 0
    if age_h >= AGE_BANDS_HOURS[0]:
        return 1
    return 2


def order_for_triage(
    pairs: list[tuple[Candidate, Decision]],
    *,
    now: datetime,
) -> list[tuple[Candidate, Decision]]:
    def sort_key(pair: tuple[Candidate, Decision]) -> tuple[int, int, datetime, int]:
        c, d = pair
        return (age_band(c, now=now), -d.hint_score, c.first_seen, c.story_id)

    return sorted(pairs, key=sort_key)

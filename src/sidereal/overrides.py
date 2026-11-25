"""Config overrides edited in the settings UI (M27, plan §16 M27 "weights, thresholds, budget").

Only the ``[scoring]``, ``[budget]`` and ``[triage]`` sections can be overridden. Overrides are
stored in the ``settings`` table (one row per section) and win over the TOML file and env for the
keys they name; everything else stays read-only in the UI. They take effect where a run, a
rescore or a view reads the settings: ``effective_settings(settings, conn)``.

Bounds are tighter than the file's (a UI typo must not wreck placement): see the ``*Overrides``
models. A stored section that no longer validates (bounds changed in code) is ignored with a
warning instead of failing a run.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sidereal.config import Settings
from sidereal.db import Connection, settings_repo

log = logging.getLogger(__name__)

Weight = Annotated[float, Field(ge=0.0, le=1.0)] | None
Bonus = Annotated[float, Field(ge=0.0, le=50.0)] | None
Threshold = Annotated[float, Field(ge=0.0, le=100.0)] | None


def _int(lo: int, hi: int) -> Any:
    return Annotated[int, Field(ge=lo, le=hi)] | None


def _float(lo: float, hi: float) -> Any:
    return Annotated[float, Field(ge=lo, le=hi)] | None


class _Overrides(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ScoringOverrides(_Overrides):
    w_relevance: Weight = None
    w_urgency: Weight = None
    w_actionability: Weight = None
    w_novelty: Weight = None
    source_bonus_factor: Bonus = None
    kev_bonus: Bonus = None
    exploited_bonus: Bonus = None
    cvss9_bonus: Bonus = None
    cvss7_bonus: Bonus = None
    corroboration_bonus: Bonus = None
    corroboration_max: Bonus = None
    primary_bonus: Bonus = None
    side_penalty: Bonus = None
    top_threshold: Threshold = None
    relevant_threshold: Threshold = None
    side_threshold: Threshold = None
    top_cap: _int(1, 100) = None
    relevant_cap: _int(1, 500) = None
    recency_full_hours: _float(0.0, 24.0) = None
    recency_floor: _float(0.0, 1.0) = None


class BudgetOverrides(_Overrides):
    max_triage_per_run: _int(0, 2000) = None
    triage_batch_size: _int(1, 50) = None
    max_assess_per_run: _int(0, 500) = None
    # the run unit's TimeoutStartSec is 3 h and the gate may wait 90 min first (M22)
    max_run_minutes: _int(5, 85) = None
    assess_excerpt_chars: _int(100, 1500) = None
    assess_content_chars: _int(0, 20000) = None


class TriageOverrides(_Overrides):
    keep_min: _int(0, 3) = None


SECTIONS: dict[str, type[_Overrides]] = {
    "scoring": ScoringOverrides,
    "budget": BudgetOverrides,
    "triage": TriageOverrides,
}


class OverrideError(ValueError):
    """Overrides that fail validation; the message is safe to show."""


def _clean(section: str, values: dict[str, Any]) -> dict[str, Any]:
    """Validated ``{field: value}`` without None entries (None = "use the file")."""
    model = SECTIONS[section]
    try:
        parsed = model.model_validate(values)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise OverrideError(f"{section}.{where}: {first['msg']}") from None
    return {k: v for k, v in parsed.model_dump().items() if v is not None}


def _check_consistency(settings: Settings) -> None:
    s = settings.scoring
    if not s.top_threshold > s.relevant_threshold > s.side_threshold:
        raise OverrideError("scoring thresholds must satisfy top > relevant > side")
    if s.corroboration_max < s.corroboration_bonus:
        raise OverrideError("scoring.corroboration_max must be >= corroboration_bonus")


def _merge(settings: Settings, overrides: dict[str, dict[str, Any]]) -> Settings:
    update = {name: getattr(settings, name).model_copy(update=values)
              for name, values in overrides.items() if values}
    return settings.model_copy(update=update)


def validate_overrides(settings: Settings,
                       overrides: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Check new overrides against ``settings`` (the file's values): unknown sections or keys,
    bounds, and the cross-field rules on the merged result. Returns the cleaned overrides
    (every editable section present, possibly empty) or raises ``OverrideError``."""
    unknown = sorted(set(overrides) - set(SECTIONS))
    if unknown:
        raise OverrideError(f"not editable: {', '.join(unknown)}")
    cleaned = {name: _clean(name, overrides.get(name) or {}) for name in SECTIONS}
    _check_consistency(_merge(settings, cleaned))
    return cleaned


def apply_overrides(settings: Settings, stored: dict[str, dict[str, Any]]) -> Settings:
    """``settings`` with the stored overrides applied; a section that does not validate any
    more is skipped (logged), and so is the whole set if the merge breaks a cross-field rule."""
    usable: dict[str, dict[str, Any]] = {}
    for name in SECTIONS:
        values = stored.get(name)
        if not values:
            continue
        try:
            usable[name] = _clean(name, values)
        except OverrideError as exc:
            log.warning("ignoring stored %s overrides: %s", name, exc)
    merged = _merge(settings, usable)
    try:
        _check_consistency(merged)
    except OverrideError as exc:
        log.warning("ignoring stored overrides: %s", exc)
        return settings
    return merged


def effective_settings(settings: Settings, conn: Connection) -> Settings:
    """The settings a run, rescore or view should use: file + env + stored overrides."""
    return apply_overrides(settings, settings_repo.get_overrides(conn))

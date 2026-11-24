"""Load the seed TOMLs (``config/defaults/sources.toml`` and ``focus.toml``)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sidereal.config import ConfigError

SourceKind = Literal["rss", "msrc", "cisa_kev", "hn_algolia"]


class SourceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    kind: SourceKind
    url: str = Field(pattern=r"^https://")
    weight: float = Field(default=1.0, ge=0.5, le=1.5)
    max_items: int = Field(default=50, ge=1)
    enabled: bool = True
    options: dict[str, Any] = {}


class FocusSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    tier: Literal["primary", "secondary", "side"]
    description: str = Field(min_length=40)
    keywords: list[str]
    enabled: bool = True


def _read(path: Path, table: str) -> list[dict[str, Any]]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    rows = data.get(table)
    if not isinstance(rows, list) or not rows:
        raise ConfigError(f"{path}: expected a non-empty [[{table}]] array")
    return rows


def _unique(path: Path, keys: list[str]) -> None:
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise ConfigError(f"{path}: duplicate keys {dupes}")


def load_sources(path: Path) -> list[SourceSeed]:
    try:
        seeds = [SourceSeed.model_validate(row) for row in _read(path, "source")]
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    _unique(path, [s.key for s in seeds])
    return seeds


def load_focus_areas(path: Path) -> list[FocusSeed]:
    try:
        seeds = [FocusSeed.model_validate(row) for row in _read(path, "focus")]
    except ValidationError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    _unique(path, [f.key for f in seeds])
    return seeds

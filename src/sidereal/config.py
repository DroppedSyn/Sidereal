"""Settings: TOML file (``paths.config_file()``) + env overrides ``SIDEREAL_<SECTION>__<KEY>``.

Env values are parsed as JSON when they parse (numbers, booleans, lists), else taken as plain
strings: ``SIDEREAL_WEB__PORT=8471``, ``SIDEREAL_WEB__ALLOWED_HOSTS='["127.0.0.1","vm.lan"]'``.
Unknown sections or keys are errors (typos must not pass silently). Secrets never live here
(plan §12.3).
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from sidereal import paths

ENV_PREFIX = "SIDEREAL_"


class ConfigError(Exception):
    """Settings could not be read or are invalid (CLI exit code 2)."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebSettings(_Section):
    host: str = "127.0.0.1"
    port: int = Field(default=8470, ge=1, le=65535)
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    # Extra origins accepted on writes, e.g. "http://localhost:5173" for the Vite dev server.
    # Origins on an allowed host with port `port` are always accepted.
    allowed_origins: list[str] = []
    https: bool = False
    trusted_proxies: list[str] = []


class AuthSettings(_Section):
    mode: Literal["off", "on"] = "off"
    require_totp: bool = False


class OllamaSettings(_Section):
    url: str = "http://192.168.221.1:11434"


class ModelSettings(_Section):
    triage: str = "qwen3.8:27b"
    assess: str = "qwen3.8:27b"
    digest: str = "qwen3.8:27b"
    never_unload: list[str] = ["qwen3.6:35b-a3b-coding"]
    keep_alive: str = "10m"


class BudgetSettings(_Section):
    max_triage_per_run: int = 150
    triage_batch_size: int = 15
    max_assess_per_run: int = 40
    max_run_minutes: int = 45
    assess_excerpt_chars: int = 1500
    assess_content_chars: int = 6000


class IngestSettings(_Section):
    max_age_hours: int = 96
    backfill_hours: int = 72
    dedupe_window_hours: int = 72


class TriageSettings(_Section):
    keep_min: int = Field(default=2, ge=0, le=3)


class GateSettings(_Section):
    pi_bridge_runs_dir: str = "~/.pi-bridge/runs"
    probe_busy_seconds: float = 20.0
    poll_seconds: float = 60.0
    max_wait_minutes: float = 90.0


class ScoringSettings(_Section):
    w_relevance: float = 0.40
    w_urgency: float = 0.25
    w_actionability: float = 0.20
    w_novelty: float = 0.15
    source_bonus_factor: float = 10.0
    kev_bonus: float = 12.0
    exploited_bonus: float = 8.0
    cvss9_bonus: float = 8.0
    cvss7_bonus: float = 4.0
    corroboration_bonus: float = 4.0
    corroboration_max: float = 12.0
    primary_bonus: float = 5.0
    side_penalty: float = 5.0
    top_threshold: float = 72.0
    relevant_threshold: float = 48.0
    side_threshold: float = 25.0
    top_cap: int = 8
    relevant_cap: int = 30
    recency_full_hours: float = 6.0
    recency_floor: float = 0.8


class ScheduleSettings(_Section):
    tz: str = "Europe/London"

    @field_validator("tz")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value


class NotifySettings(_Section):
    channels: list[Literal["email", "discord"]] = []
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_ssl: bool = False
    smtp_user: str = ""
    smtp_from: str = ""
    smtp_to: list[str] = []


class RetentionSettings(_Section):
    """Data lifecycle (plan §12.4): article text kept ``content_days``, dropped/filtered stories
    deleted after ``drop_days``, ``backup_keep`` newest backups kept."""

    content_days: int = Field(default=30, ge=1)
    drop_days: int = Field(default=90, ge=1)
    backup_keep: int = Field(default=14, ge=1)


class PathSettings(_Section):
    state_dir: Path | None = None  # None → $XDG_DATA_HOME/sidereal

    @field_validator("state_dir")
    @classmethod
    def _expand(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None


class Settings(_Section):
    web: WebSettings = WebSettings()
    auth: AuthSettings = AuthSettings()
    ollama: OllamaSettings = OllamaSettings()
    models: ModelSettings = ModelSettings()
    budget: BudgetSettings = BudgetSettings()
    ingest: IngestSettings = IngestSettings()
    triage: TriageSettings = TriageSettings()
    gate: GateSettings = GateSettings()
    scoring: ScoringSettings = ScoringSettings()
    schedule: ScheduleSettings = ScheduleSettings()
    notify: NotifySettings = NotifySettings()
    retention: RetentionSettings = RetentionSettings()
    paths: PathSettings = PathSettings()

    @property
    def state_dir(self) -> Path:
        return self.paths.state_dir or paths.default_state_dir()

    @property
    def db_path(self) -> Path:
        return self.state_dir / "sidereal.db"


def _env_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def env_overrides(env: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """``SIDEREAL_WEB__PORT=1`` → ``{"web": {"port": 1}}``. Variables without ``__`` are ignored."""
    out: dict[str, dict[str, Any]] = {}
    for name, raw in env.items():
        if not name.startswith(ENV_PREFIX) or "__" not in name:
            continue
        section, _, key = name[len(ENV_PREFIX) :].lower().partition("__")
        if section not in Settings.model_fields:
            raise ConfigError(f"{name}: unknown settings section {section!r}")
        out.setdefault(section, {})[key] = _env_value(raw)
    return out


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the TOML file (missing file = all defaults), apply env overrides, validate."""
    env = os.environ if env is None else env
    path = paths.config_file(env)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc
    for section, values in env_overrides(env).items():
        current = data.setdefault(section, {})
        if not isinstance(current, dict):
            raise ConfigError(f"{path}: [{section}] must be a table")
        current.update(values)
    try:
        settings = Settings.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid settings ({path}): {exc}") from exc
    if settings.paths.state_dir is None:
        default = paths.default_state_dir(env)
        settings = settings.model_copy(
            update={"paths": PathSettings(state_dir=default)}
        )
    return settings

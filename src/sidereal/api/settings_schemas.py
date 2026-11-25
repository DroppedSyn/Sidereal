"""Request/response models of the settings API (M27). Input models validate strictly (422):
keys, tiers, kinds, weight 0.5..1.5, keywords as non-empty one-line strings, source URLs via
``sources.validate.check_source_url``. Kind-specific source options are checked in the route
(they need the kind and key together): ``sources.validate.clean_options``."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from sidereal.sources.validate import check_source_url

KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{0,39}$"
MAX_KEYWORDS = 60
MAX_KEYWORD = 60
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")
_CONTROL_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")

Tier = Literal["primary", "secondary", "side"]
Kind = Literal["rss", "msrc", "cisa_kev", "hn_algolia"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


def one_line(value: str, what: str, max_len: int) -> str:
    if _CONTROL_LINE.search(value):
        raise ValueError(f"{what} must be one line without control characters")
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"{what} must not be empty")
    if len(value) > max_len:
        raise ValueError(f"{what} is longer than {max_len} characters")
    return value


# --- focus areas -------------------------------------------------------------------------


class FocusFields(_In):
    name: str
    tier: Tier
    description: str = Field(min_length=40, max_length=2000)
    keywords: list[str] = Field(max_length=MAX_KEYWORDS)
    enabled: StrictBool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return one_line(v, "name", 80)

    @field_validator("description")
    @classmethod
    def _description(cls, v: str) -> str:
        if _CONTROL.search(v):
            raise ValueError("description must not contain control characters")
        v = v.strip()
        if len(v) < 40:
            raise ValueError("description must be at least 40 characters")
        return v

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for kw in v:
            kw = one_line(kw, "keyword", MAX_KEYWORD).lower()
            if kw not in out:
                out.append(kw)
        return out


class FocusIn(FocusFields):
    key: str = Field(pattern=KEY_PATTERN)

    @field_validator("key")
    @classmethod
    def _not_none(cls, v: str) -> str:
        if v == "none":
            raise ValueError('"none" is reserved (it means "no focus area")')
        return v


class FocusOut(BaseModel):
    key: str
    name: str
    tier: Tier
    description: str
    keywords: list[str]
    enabled: bool


# --- sources -----------------------------------------------------------------------------


class SourceFields(_In):
    name: str
    url: str
    enabled: StrictBool = True
    weight: float = Field(default=1.0, ge=0.5, le=1.5, strict=True)
    max_items: int = Field(default=50, ge=1, le=500, strict=True)
    options: dict[str, Any] = {}

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return one_line(v, "name", 100)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return check_source_url(v)


class SourceIn(SourceFields):
    key: str = Field(pattern=KEY_PATTERN)
    kind: Kind


class SourceConfig(BaseModel):
    id: int
    key: str
    name: str
    kind: str
    url: str
    enabled: bool
    weight: float
    max_items: int
    options: dict[str, Any]


class FeedTestIn(_In):
    kind: Kind
    url: str
    max_items: int = Field(default=50, ge=1, le=500, strict=True)
    options: dict[str, Any] = {}

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        return check_source_url(v)


class FeedTestOut(BaseModel):
    ok: bool
    entries: int  # entries in the answer before filters
    items: int  # items a run would keep (filters, cap; no age cap)
    titles: list[str]  # first few kept titles, plain text
    error: str | None


# --- overrides, notify, effective config --------------------------------------------------


class OverridesIn(_In):
    scoring: dict[str, Any] = {}
    budget: dict[str, Any] = {}
    triage: dict[str, Any] = {}


class NotifyChannel(BaseModel):
    name: Literal["email", "discord"]
    enabled: bool  # listed in notify.channels
    configured: bool  # settings and secret present (the secret itself is never returned)
    problem: str | None  # why it is not configured, safe text


class SettingsOut(BaseModel):
    config: dict[str, Any]  # effective settings (file + env + overrides); never secrets
    overrides: dict[str, dict[str, Any]]
    editable: dict[str, list[str]]  # section → keys the UI may override
    notify: list[NotifyChannel]


class NotifyTestIn(_In):
    channel: Literal["email", "discord"]


class NotifyTestOut(BaseModel):
    channel: str
    ok: bool
    error: str | None

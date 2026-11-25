"""Settings API (M27, plan §16 M27, §12.3): effective config (read-only), overrides of the
scoring / budget / triage sections, notification status + test send, focus-area CRUD. Sources
are in ``routes_settings_sources``. Changes take effect at the next run.

Secrets are never returned (rule 8, plan §12.3): channels report ``configured`` only, and every
string in a response passes ``redact`` against the loaded secrets as a second line of defence.
Writes go through the write guard and the auth middleware like every other route.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from sidereal import overrides as ov
from sidereal.api.deps import get_settings, open_db
from sidereal.api.settings_schemas import (
    KEY_PATTERN,
    FocusFields,
    FocusIn,
    FocusOut,
    NotifyChannel,
    NotifyTestIn,
    NotifyTestOut,
    OverridesIn,
    SettingsOut,
)
from sidereal.config import Settings
from sidereal.db import focus_repo, settings_repo
from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from sidereal.notify.base import NotifyError, Secrets, load_secrets
from sidereal.notify.dispatcher import make_channel, send_test

log = logging.getLogger(__name__)
router = APIRouter()
CHANNELS = ("email", "discord")
FocusKey = Annotated[str, Path(pattern=KEY_PATTERN)]


def make_fetcher() -> Fetcher:
    """The notify test's fetcher (tests replace it)."""
    return Fetcher(guard=UrlGuard())


def secrets_or_error() -> tuple[Secrets, str | None]:
    try:
        return load_secrets(), None
    except NotifyError as exc:
        return Secrets(), str(exc)


def redact(value: Any, secrets: Secrets) -> Any:
    """``value`` with every secret string replaced by ``[redacted]`` (recursively)."""
    if isinstance(value, str):
        for s in secrets.values():
            value = value.replace(s, "[redacted]")
        return value
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    return value


def channel_status(settings: Settings, secrets: Secrets,
                   problem: str | None) -> list[NotifyChannel]:
    out = []
    for name in CHANNELS:
        why = problem
        if why is None:
            try:
                make_channel(name, settings, secrets, None)  # type: ignore[arg-type]
            except NotifyError as exc:
                why = str(exc)
        out.append(NotifyChannel(name=name, enabled=name in settings.notify.channels,
                                 configured=why is None,
                                 problem=None if why is None else redact(why, secrets)))
    return out


def _settings_out(settings: Settings, stored: dict[str, dict[str, Any]]) -> SettingsOut:
    effective = ov.apply_overrides(settings, stored)
    secrets, problem = secrets_or_error()
    return SettingsOut(
        config=redact(effective.model_dump(mode="json"), secrets),
        overrides={name: stored.get(name, {}) for name in ov.SECTIONS},
        editable={name: list(model.model_fields) for name, model in ov.SECTIONS.items()},
        notify=channel_status(settings, secrets, problem))


@router.get("/api/settings", response_model=SettingsOut)
def get_settings_view(settings: Annotated[Settings, Depends(get_settings)]) -> SettingsOut:
    with open_db(settings) as conn:
        stored = settings_repo.get_overrides(conn)
    return _settings_out(settings, stored)


@router.put("/api/settings/overrides", response_model=SettingsOut)
def put_overrides(body: OverridesIn,
                  settings: Annotated[Settings, Depends(get_settings)]) -> SettingsOut:
    """Replace every override (a missing or null key = back to the file's value)."""
    try:
        cleaned = ov.validate_overrides(settings, body.model_dump())
    except ov.OverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    with open_db(settings) as conn:
        for name, values in cleaned.items():
            settings_repo.set_override(conn, name, values)
        stored = settings_repo.get_overrides(conn)
    log.info("settings: overrides updated (%s)", ", ".join(k for k, v in cleaned.items() if v)
             or "none")
    return _settings_out(settings, stored)


@router.post("/api/settings/notify/test", response_model=NotifyTestOut)
async def notify_test(body: NotifyTestIn,
                      settings: Annotated[Settings, Depends(get_settings)]) -> NotifyTestOut:
    """Send the fixed test message on one channel; failures come back as ``ok: false``."""
    secrets, problem = secrets_or_error()
    if problem is not None:
        return NotifyTestOut(channel=body.channel, ok=False, error=redact(problem, secrets))
    fetcher = make_fetcher()
    try:
        await send_test(settings, body.channel, fetcher=fetcher, secrets=secrets)
    except NotifyError as exc:
        return NotifyTestOut(channel=body.channel, ok=False, error=redact(str(exc), secrets))
    finally:
        await fetcher.aclose()
    return NotifyTestOut(channel=body.channel, ok=True, error=None)


# --- focus areas -------------------------------------------------------------------------


def _focus_out(conn: Any, key: str) -> FocusOut:
    for f in focus_repo.list_focus_areas(conn, enabled_only=False):
        if f.key == key:
            return FocusOut(key=f.key, name=f.name, tier=f.tier,  # type: ignore[arg-type]
                            description=f.description, keywords=list(f.keywords),
                            enabled=f.enabled)
    raise HTTPException(status_code=404, detail="focus area not found")


@router.get("/api/settings/focus", response_model=list[FocusOut])
def list_focus(settings: Annotated[Settings, Depends(get_settings)]) -> list[FocusOut]:
    with open_db(settings) as conn:
        rows = focus_repo.list_focus_areas(conn, enabled_only=False)
    return [FocusOut(key=f.key, name=f.name, tier=f.tier,  # type: ignore[arg-type]
                     description=f.description, keywords=list(f.keywords), enabled=f.enabled)
            for f in rows]


@router.post("/api/settings/focus", response_model=FocusOut, status_code=201)
def add_focus(body: FocusIn, settings: Annotated[Settings, Depends(get_settings)]) -> FocusOut:
    with open_db(settings) as conn:
        try:
            settings_repo.add_focus_area(conn, **body.model_dump())
        except settings_repo.KeyTaken:
            raise HTTPException(status_code=409, detail="a focus area with this key exists") \
                from None
        return _focus_out(conn, body.key)


@router.put("/api/settings/focus/{key}", response_model=FocusOut)
def edit_focus(key: FocusKey, body: FocusFields,
               settings: Annotated[Settings, Depends(get_settings)]) -> FocusOut:
    with open_db(settings) as conn:
        try:
            settings_repo.update_focus_area(conn, key, **body.model_dump())
        except KeyError:
            raise HTTPException(status_code=404, detail="focus area not found") from None
        return _focus_out(conn, key)


@router.delete("/api/settings/focus/{key}", status_code=204)
def delete_focus(key: FocusKey, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    with open_db(settings) as conn:
        try:
            settings_repo.delete_focus_area(conn, key)
        except KeyError:
            raise HTTPException(status_code=404, detail="focus area not found") from None
    return Response(status_code=204)

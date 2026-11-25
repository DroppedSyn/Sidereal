"""Settings API for sources (M27, plan §16 M27): list / add / edit / delete, and "Test feed"
(fetch through the URL guard with the source's adapter, report the parsed count; nothing is
stored). Validation: ``settings_schemas`` (URL static guard rules, weight, max_items) plus
``sources.validate.clean_options`` per kind (422). Key and kind are fixed once created.
A source with items cannot be deleted (409): disable it instead."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from sidereal.api.deps import get_now, get_settings, open_db
from sidereal.api.settings_schemas import (
    FeedTestIn,
    FeedTestOut,
    SourceConfig,
    SourceFields,
    SourceIn,
)
from sidereal.config import Settings
from sidereal.db import settings_repo, sources_repo
from sidereal.net.fetch import Fetcher, FetchError, FetchHTTPError
from sidereal.net.guard import UrlBlocked, UrlGuard
from sidereal.sources import REGISTRY
from sidereal.sources.base import SourceBroken
from sidereal.sources.validate import ProbeSource, clean_options
from sidereal.textclean import clean_title

log = logging.getLogger(__name__)
router = APIRouter()
SourceId = Annotated[int, Path(ge=1)]
TEST_TITLES = 5


def make_fetcher() -> Fetcher:
    """The "Test feed" fetcher: the real guard (DNS checked on every hop). Tests replace it."""
    return Fetcher(guard=UrlGuard())


def _options(kind: str, key: str, options: dict[str, Any]) -> dict[str, Any]:
    try:
        return clean_options(kind, key, options)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _out(row: sources_repo.SourceRow) -> SourceConfig:
    return SourceConfig(id=row.id, key=row.key, name=row.name, kind=row.kind, url=row.url,
                        enabled=row.enabled, weight=row.weight, max_items=row.max_items,
                        options=row.options)


def _get(conn: Any, source_id: int) -> sources_repo.SourceRow:
    row = sources_repo.get_source(conn, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="source not found")
    return row


@router.get("/api/settings/sources", response_model=list[SourceConfig])
def list_source_configs(settings: Annotated[Settings, Depends(get_settings)]) -> list[SourceConfig]:
    with open_db(settings) as conn:
        return [_out(s) for s in sources_repo.list_sources(conn)]


@router.post("/api/settings/sources", response_model=SourceConfig, status_code=201)
def add_source(body: SourceIn, settings: Annotated[Settings, Depends(get_settings)],
               now: Annotated[datetime, Depends(get_now)]) -> SourceConfig:
    options = _options(body.kind, body.key, body.options)
    with open_db(settings) as conn:
        try:
            new_id = settings_repo.add_source(
                conn, key=body.key, name=body.name, kind=body.kind, url=body.url,
                enabled=body.enabled, weight=body.weight, max_items=body.max_items,
                options=options, at=now)
        except settings_repo.KeyTaken:
            raise HTTPException(status_code=409, detail="a source with this key exists") from None
        log.info("settings: source %s added", body.key)
        return _out(_get(conn, new_id))


@router.put("/api/settings/sources/{source_id}", response_model=SourceConfig)
def edit_source(source_id: SourceId, body: SourceFields,
                settings: Annotated[Settings, Depends(get_settings)]) -> SourceConfig:
    with open_db(settings) as conn:
        row = _get(conn, source_id)
        options = _options(row.kind, row.key, body.options)
        settings_repo.update_source(conn, source_id, name=body.name, url=body.url,
                                    enabled=body.enabled, weight=body.weight,
                                    max_items=body.max_items, options=options)
        log.info("settings: source %s edited", row.key)
        return _out(_get(conn, source_id))


@router.delete("/api/settings/sources/{source_id}", status_code=204)
def delete_source(source_id: SourceId,
                  settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    with open_db(settings) as conn:
        row = _get(conn, source_id)
        if settings_repo.source_item_count(conn, source_id):
            raise HTTPException(status_code=409,
                                detail="this source has items: disable it instead")
        settings_repo.delete_source(conn, source_id)
        log.info("settings: source %s deleted", row.key)
    return Response(status_code=204)


def _failure(exc: Exception) -> str:
    if isinstance(exc, UrlBlocked):
        return f"URL refused: {exc.reason}"
    if isinstance(exc, SourceBroken):
        return f"not a feed: {exc}"[:200]
    if isinstance(exc, FetchHTTPError):
        return f"HTTP {exc.status}"
    if isinstance(exc, FetchError):
        return f"fetch failed: {exc}"[:200]
    return f"{type(exc).__name__}: {exc}"[:200]


@router.post("/api/settings/sources/test", response_model=FeedTestOut)
async def test_feed(body: FeedTestIn, now: Annotated[datetime, Depends(get_now)]) -> FeedTestOut:
    """Fetch ``url`` once with the adapter of ``kind`` (no conditional GET, no age cap)."""
    options = _options(body.kind, "test", body.options)
    probe = ProbeSource(key="test", options=options, url=body.url, max_items=body.max_items)
    adapter = REGISTRY[body.kind]()
    fetcher = make_fetcher()
    try:
        result = await adapter.fetch(probe, fetcher, now, max_age_hours=None)
    except (UrlBlocked, SourceBroken, FetchError, ValueError) as exc:
        return FeedTestOut(ok=False, entries=0, items=0, titles=[], error=_failure(exc))
    finally:
        await fetcher.aclose()
    entries = result.entry_count if result.entry_count is not None else len(result.items)
    return FeedTestOut(ok=True, entries=entries, items=len(result.items),
                       titles=[clean_title(i.title, 200) for i in result.items[:TEST_TITLES]],
                       error=None)

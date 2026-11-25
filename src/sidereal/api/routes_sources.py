"""GET /api/sources: every source with computed health (plan §10.1, §10.2, §6.5)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends

from sidereal.api.deps import get_now, get_settings, open_db
from sidereal.api.schemas import SourceStatus
from sidereal.config import Settings
from sidereal.db.sources_repo import health, last_item_times, list_sources
from sidereal.db.views_repo import item_counts_since
from sidereal.timeutil import iso_z
from sidereal.urls import is_http_url

router = APIRouter()
RECENT = timedelta(days=7)


@router.get("/api/sources", response_model=list[SourceStatus])
def sources(
    settings: Annotated[Settings, Depends(get_settings)],
    now: Annotated[datetime, Depends(get_now)],
) -> list[SourceStatus]:
    with open_db(settings) as conn:
        rows = list_sources(conn)
        last = last_item_times(conn)
        recent = item_counts_since(conn, since=now - RECENT)
    out = []
    for s in rows:
        newest = last.get(s.id)
        out.append(SourceStatus(
            id=s.id, key=s.key, name=s.name, kind=s.kind,
            url=s.url if is_http_url(s.url) else None, enabled=s.enabled, weight=s.weight,
            health=health(s, now=now, last_new_item_at=newest),
            last_fetch_at=s.last_fetch_at, last_ok_at=s.last_ok_at, last_error=s.last_error,
            consecutive_failures=s.consecutive_failures,
            last_item_at=iso_z(newest) if newest is not None else None,
            items_7d=recent.get(s.id, 0)))
    return out

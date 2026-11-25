"""GET /api/days and /api/days/{day}: the Daily view (plan §10.1)."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from sidereal.api.deps import check_day, get_settings, open_db
from sidereal.api.present import build_sections, placed_counts
from sidereal.api.schemas import DayDetail, DayRun, DaySummary
from sidereal.config import Settings
from sidereal.db.digests_repo import get_day_digest
from sidereal.db.views_repo import day_summaries, day_views, runs_between
from sidereal.timeutil import day_key, day_label, parse_iso_z

router = APIRouter()


def day_bounds(day: str, tz: str) -> tuple[datetime, datetime]:
    """UTC start (inclusive) and end (exclusive) of local ``day`` in ``tz``."""
    zone = ZoneInfo(tz)
    d = date.fromisoformat(day)
    start = datetime.combine(d, time(0), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(d + timedelta(days=1), time(0), tzinfo=zone).astimezone(UTC)
    return start, end


@router.get("/api/days", response_model=list[DaySummary])
def list_days(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=365)] = 60,
    before: str | None = None,
) -> list[DaySummary]:
    if before is not None:
        check_day(before, name="before")
    tz = settings.schedule.tz
    with open_db(settings) as conn:
        rows = day_summaries(conn, limit=limit, before=before)
        runs = []
        if rows:
            start, _ = day_bounds(rows[-1].day, tz)
            _, end = day_bounds(rows[0].day, tz)
            runs = runs_between(conn, start=start, end=end)
    per_day = Counter(day_key(parse_iso_z(r.started_at), tz) for r in runs)
    return [DaySummary(day=r.day, label=day_label(r.day),
                       counts=placed_counts(r.top, r.relevant, r.side, settings.scoring),
                       run_count=per_day.get(r.day, 0), headline=r.headline)
            for r in rows]


@router.get("/api/days/{day}", response_model=DayDetail)
def get_day(
    day: str,
    settings: Annotated[Settings, Depends(get_settings)],
    include_drop: bool = False,
) -> DayDetail:
    check_day(day)
    start, end = day_bounds(day, settings.schedule.tz)
    with open_db(settings) as conn:
        views = day_views(conn, day)
        digest = get_day_digest(conn, day)
        runs = runs_between(conn, start=start, end=end)
    sections, counts = build_sections(views, settings.scoring, now=None, include_drop=include_drop)
    return DayDetail(
        day=day, label=day_label(day),
        overview=digest.overview if digest else None,
        headline=digest.headline if digest else None,
        runs=[DayRun(id=r.id, started_at=r.started_at, finished_at=r.finished_at,
                     trigger=r.trigger, status=r.status) for r in runs],
        sections=sections, counts=counts,
    )

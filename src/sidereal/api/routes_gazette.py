"""GET /api/gazette: the rolling-window front page (plan §10.1, §8)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from sidereal.api.deps import get_now, get_settings, open_db
from sidereal.api.present import build_sections
from sidereal.api.schemas import Gazette
from sidereal.config import Settings
from sidereal.db.feedback_repo import story_feedback
from sidereal.db.views_repo import gazette_views
from sidereal.overrides import effective_settings
from sidereal.timeutil import iso_z

router = APIRouter()


@router.get("/api/gazette", response_model=Gazette)
def gazette(
    settings: Annotated[Settings, Depends(get_settings)],
    now: Annotated[datetime, Depends(get_now)],
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
    include_drop: bool = False,
) -> Gazette:
    since = now - timedelta(hours=hours)
    with open_db(settings) as conn:
        views = gazette_views(conn, since=since)
        feedback = story_feedback(conn, [v.id for v in views])
        scoring = effective_settings(settings, conn).scoring
    sections, counts = build_sections(views, scoring, now=now,
                                      include_drop=include_drop, feedback=feedback)
    return Gazette(generated_at=iso_z(now), window_start=iso_z(since), sections=sections,
                   counts=counts)

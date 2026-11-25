"""GET /api/weeks, /api/weeks/{week} and /api/weeks/{week}/export.md: the weekly digest (M29).

The list shows weeks that have a digest. A week's detail is served for any real ISO week:
the digest (or nulls before a run wrote one) plus the week's TOP and best Relevant stories as
they are placed now (``week_step.week_set``: hidden stories left out), so the page matches
what the next digest would be built from.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from sidereal.api.deps import get_settings, open_db
from sidereal.api.present import story_out
from sidereal.api.schemas import Counts, Sections, Story, WeekDetail, WeekSummary
from sidereal.api.week_export import week_markdown
from sidereal.config import Settings
from sidereal.db import Connection
from sidereal.db.feedback_repo import story_feedback
from sidereal.db.views_repo import views_for_ids
from sidereal.db.week_digests_repo import get_week_digest, list_week_digests
from sidereal.overrides import effective_settings
from sidereal.pipeline.week_step import week_set
from sidereal.weeks import is_week, week_days, week_label

router = APIRouter()


def check_week(value: str, *, name: str = "week") -> str:
    """*value* if it is a real ISO week ``YYYY-Www`` (``2025-W53`` is not), else HTTP 422."""
    if not is_week(value):
        raise HTTPException(status_code=422, detail=f"{name} must be an ISO week like 2026-W48")
    return value


def _week_stories(conn: Connection, week: str, settings: Settings) -> dict[str, list[Story]]:
    entries = week_set(conn, week, effective_settings(settings, conn))
    views = {v.id: v for v in views_for_ids(conn, [e.story_id for e in entries])}
    feedback = story_feedback(conn, list(views))
    out: dict[str, list[Story]] = {"top": [], "relevant": []}
    for e in entries:
        v = views.get(e.story_id)
        if v is not None and not feedback[v.id].hidden:
            out[e.bucket].append(story_out(v, bucket=e.bucket, fb=feedback[v.id]))
    return out


@router.get("/api/weeks", response_model=list[WeekSummary])
def list_weeks(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=260)] = 52,
    before: str | None = None,
) -> list[WeekSummary]:
    if before is not None:
        check_week(before, name="before")
    with open_db(settings) as conn:
        rows = list_week_digests(conn, limit=limit, before=before)
    return [WeekSummary(week=r.week, label=week_label(r.week), start_day=r.start_day,
                        end_day=r.end_day, headline=r.headline, story_count=len(r.story_ids),
                        updated_at=r.updated_at) for r in rows]


@router.get("/api/weeks/{week}", response_model=WeekDetail)
def get_week(week: str, settings: Annotated[Settings, Depends(get_settings)]) -> WeekDetail:
    check_week(week)
    with open_db(settings) as conn:
        digest = get_week_digest(conn, week)
        stories = _week_stories(conn, week, settings)
    days = week_days(week)
    return WeekDetail(
        week=week, label=week_label(week), start_day=days[0], end_day=days[-1],
        overview=digest.overview if digest else None,
        headline=digest.headline if digest else None,
        updated_at=digest.updated_at if digest else None,
        sections=Sections(top=stories["top"], relevant=stories["relevant"], side=[], drop=[]),
        counts=Counts(top=len(stories["top"]), relevant=len(stories["relevant"]), side=0,
                      drop=0),
    )


@router.get("/api/weeks/{week}/export.md", response_class=Response,
            responses={200: {"content": {"text/markdown": {}}}})
def export_week(week: str, settings: Annotated[Settings, Depends(get_settings)]) -> Response:
    check_week(week)
    with open_db(settings) as conn:
        digest = get_week_digest(conn, week)
        stories = _week_stories(conn, week, settings)
    body = week_markdown(label=week_label(week),
                         headline=digest.headline if digest else None,
                         overview=digest.overview if digest else None,
                         top=stories["top"], relevant=stories["relevant"])
    return Response(body, media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="sidereal-{week}.md"'})

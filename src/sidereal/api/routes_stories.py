"""GET /api/stories/{id}: one story with all items and its assessment (plan §10.1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from sidereal.api.deps import get_settings, open_db
from sidereal.api.present import story_detail_out
from sidereal.api.schemas import StoryDetail
from sidereal.config import Settings
from sidereal.db.feedback_repo import get_feedback
from sidereal.db.views_repo import story_detail

router = APIRouter()


@router.get("/api/stories/{story_id}", response_model=StoryDetail,
            responses={404: {"description": "unknown or hidden story"}})
def get_story(
    settings: Annotated[Settings, Depends(get_settings)],
    story_id: Annotated[int, Path(ge=1)],
) -> StoryDetail:
    with open_db(settings) as conn:
        detail = story_detail(conn, story_id)
        fb = get_feedback(conn, story_id) if detail is not None else None
    if detail is None or fb is None:
        raise HTTPException(status_code=404, detail="story not found")
    return story_detail_out(detail, fb)

"""Feedback and mutes (plan §16 M24): vote, read, hide, mark a day read, mute/unmute.

Writes pass the write guard (``X-Sidereal: 1`` + allowed Origin) and, with auth on, the session
check; both run as middleware before these routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from sidereal.api.deps import check_day, get_now, get_settings, open_db
from sidereal.config import Settings
from sidereal.db import feedback_repo, sources_repo, stories_repo
from sidereal.db.connect import Connection

router = APIRouter()

StoryId = Annotated[int, Path(ge=1)]
NOT_FOUND = {404: {"description": "unknown story"}}


class FeedbackOut(BaseModel):
    story_id: int
    vote: Literal["up", "down"] | None
    read: bool
    hidden: bool


class VoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vote: Literal["up", "down"] | None  # required key; null clears


class ReadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: StrictBool


class HiddenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: StrictBool


class DayReadOut(BaseModel):
    day: str
    marked: int


class MuteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["source", "keyword"]
    value: str = Field(min_length=1, max_length=feedback_repo.MAX_MUTE_LEN)


class MuteOut(BaseModel):
    id: int
    kind: Literal["source", "keyword"]
    value: str
    created_at: str


def _out(conn: Connection, story_id: int) -> FeedbackOut:
    fb = feedback_repo.get_feedback(conn, story_id)
    return FeedbackOut(story_id=story_id, vote=fb.vote, read=fb.read, hidden=fb.hidden)


def _story_404() -> HTTPException:
    return HTTPException(status_code=404, detail="story not found")


@router.get("/api/stories/{story_id}/feedback", response_model=FeedbackOut,
            responses=NOT_FOUND)
def get_feedback(settings: Annotated[Settings, Depends(get_settings)],
                 story_id: StoryId) -> FeedbackOut:
    with open_db(settings) as conn:
        if stories_repo.get_story(conn, story_id) is None:
            raise _story_404()
        return _out(conn, story_id)


@router.put("/api/stories/{story_id}/vote", response_model=FeedbackOut, responses=NOT_FOUND)
def put_vote(settings: Annotated[Settings, Depends(get_settings)],
             now: Annotated[datetime, Depends(get_now)],
             story_id: StoryId, body: VoteIn) -> FeedbackOut:
    with open_db(settings) as conn:
        try:
            feedback_repo.set_vote(conn, story_id, body.vote, at=now)
        except KeyError:
            raise _story_404() from None
        return _out(conn, story_id)


@router.put("/api/stories/{story_id}/read", response_model=FeedbackOut, responses=NOT_FOUND)
def put_read(settings: Annotated[Settings, Depends(get_settings)],
             now: Annotated[datetime, Depends(get_now)],
             story_id: StoryId, body: ReadIn) -> FeedbackOut:
    with open_db(settings) as conn:
        try:
            feedback_repo.set_read(conn, story_id, body.read, at=now)
        except KeyError:
            raise _story_404() from None
        return _out(conn, story_id)


@router.put("/api/stories/{story_id}/hidden", response_model=FeedbackOut, responses=NOT_FOUND)
def put_hidden(settings: Annotated[Settings, Depends(get_settings)],
               now: Annotated[datetime, Depends(get_now)],
               story_id: StoryId, body: HiddenIn) -> FeedbackOut:
    with open_db(settings) as conn:
        try:
            feedback_repo.set_hidden(conn, story_id, body.hidden, at=now)
        except KeyError:
            raise _story_404() from None
        return _out(conn, story_id)


@router.post("/api/days/{day}/read", response_model=DayReadOut)
def mark_day_read(day: str, settings: Annotated[Settings, Depends(get_settings)],
                  now: Annotated[datetime, Depends(get_now)]) -> DayReadOut:
    check_day(day)
    with open_db(settings) as conn:
        marked = feedback_repo.mark_day_read(conn, day, at=now)
    return DayReadOut(day=day, marked=marked)


def _mute_out(m: feedback_repo.MuteRow) -> MuteOut:
    return MuteOut(id=m.id, kind=m.kind, value=m.value, created_at=m.created_at)


@router.get("/api/mutes", response_model=list[MuteOut])
def list_mutes(settings: Annotated[Settings, Depends(get_settings)]) -> list[MuteOut]:
    with open_db(settings) as conn:
        return [_mute_out(m) for m in feedback_repo.list_mutes(conn)]


@router.post("/api/mutes", response_model=MuteOut, status_code=201,
             responses={422: {"description": "unknown source or invalid value"}})
def add_mute(settings: Annotated[Settings, Depends(get_settings)],
             now: Annotated[datetime, Depends(get_now)], body: MuteIn) -> MuteOut:
    with open_db(settings) as conn:
        if body.kind == "source" and sources_repo.get_by_key(conn, body.value.strip()) is None:
            raise HTTPException(status_code=422, detail="unknown source")
        try:
            row = feedback_repo.add_mute(conn, body.kind, body.value, at=now)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return _mute_out(row)


@router.delete("/api/mutes/{mute_id}", status_code=204,
               responses={404: {"description": "unknown mute"}})
def delete_mute(settings: Annotated[Settings, Depends(get_settings)],
                mute_id: Annotated[int, Path(ge=1)]) -> Response:
    with open_db(settings) as conn:
        removed = feedback_repo.remove_mute(conn, mute_id)
    if not removed:
        raise HTTPException(status_code=404, detail="mute not found")
    return Response(status_code=204)

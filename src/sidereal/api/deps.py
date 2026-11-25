"""Shared helpers for API routes: settings, clock, DB connection, day checks."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi import HTTPException, Request

from sidereal.config import Settings
from sidereal.db.connect import Connection, connect
from sidereal.timeutil import day_label, utc_now

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_now() -> datetime:
    """The request clock; tests replace it with ``app.dependency_overrides[get_now]``."""
    return utc_now()


@contextmanager
def open_db(settings: Settings) -> Iterator[Connection]:
    """A connection for one request, opened and closed in the route's own thread."""
    path = settings.db_path
    if not path.exists():
        raise HTTPException(status_code=503, detail="database not initialised (run sidereal init)")
    conn = connect(path)
    try:
        yield conn
    finally:
        conn.close()


def check_day(value: str, *, name: str = "day") -> str:
    """``value`` if it is a real YYYY-MM-DD date, else HTTP 422."""
    if not _DAY.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"{name} must be a YYYY-MM-DD date")
    try:
        day_label(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be a YYYY-MM-DD date") from None
    return value

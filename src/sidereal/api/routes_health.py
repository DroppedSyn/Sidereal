"""GET /api/health (plan §10.1). Ollama and last-run fields arrive with their milestones.
With auth on and no session only ``status`` is filled."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from sidereal import __version__
from sidereal.db.connect import ping

router = APIRouter()


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str | None  # None: auth on and no session (minimal body, plan §10.1)
    db: Literal["ok", "error"] | None


@router.get("/api/health", response_model=Health)
def health(request: Request) -> Health:
    db_ok = ping(request.app.state.settings.db_path)
    if request.app.state.settings.auth.mode == "on" and request.state.user is None:
        return Health(status="ok" if db_ok else "degraded", version=None, db=None)
    return Health(
        status="ok" if db_ok else "degraded",
        version=__version__,
        db="ok" if db_ok else "error",
    )

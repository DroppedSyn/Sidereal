"""Runs: list, detail, and POST run-now (plan §10.1, §12.1).

The only module allowed to use ``subprocess`` (rule 12): POST /api/runs asks the user's systemd
manager to start the manual run unit with a fixed argv, no shell and nothing from the request.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from sidereal.api.deps import get_settings, open_db
from sidereal.api.schemas import RunOut, RunStarted
from sidereal.config import Settings
from sidereal.db.runs_repo import RunRow, get_run, list_runs
from sidereal.pipeline import lock
from sidereal.timeutil import parse_iso_z

log = logging.getLogger(__name__)
router = APIRouter()

RUN_UNIT = "sidereal-run-manual.service"  # deploy/: `sidereal run --trigger manual`
# --no-block: systemctl only queues the start job and returns; the run lives in its own unit.
START_ARGV: tuple[str, ...] = ("systemctl", "--user", "start", "--no-block", RUN_UNIT)
START_TIMEOUT_S = 15.0


class RunStartError(Exception):
    """systemctl could not queue the run (not installed, no user manager, timeout)."""


def spawn_run() -> None:
    """Queue the manual run unit. Fixed argv, no shell, no request data (rule 12)."""
    try:
        done = subprocess.run(list(START_ARGV), stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=START_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunStartError(type(exc).__name__) from None
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()[:200]
        log.warning("systemctl start %s failed (exit %d): %s", RUN_UNIT, done.returncode, detail)
        raise RunStartError(f"systemctl exit {done.returncode}")


def run_out(r: RunRow) -> RunOut:
    duration = None
    if r.finished_at is not None:
        duration = (parse_iso_z(r.finished_at) - parse_iso_z(r.started_at)).total_seconds()
    return RunOut(id=r.id, started_at=r.started_at, finished_at=r.finished_at,
                  trigger=r.trigger, status=r.status, duration_s=duration, stats=r.stats,
                  error=r.error)


@router.get("/api/runs", response_model=list[RunOut])
def runs(
    settings: Annotated[Settings, Depends(get_settings)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[int | None, Query(ge=1, description="run id cursor (exclusive)")] = None,
) -> list[RunOut]:
    with open_db(settings) as conn:
        rows = list_runs(conn, limit=limit, before_id=before)
    return [run_out(r) for r in rows]


@router.get("/api/runs/{run_id}", response_model=RunOut,
            responses={404: {"description": "unknown run"}})
def run_detail(
    settings: Annotated[Settings, Depends(get_settings)],
    run_id: Annotated[int, Path(ge=1)],
) -> RunOut:
    with open_db(settings) as conn:
        row = get_run(conn, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run_out(row)


@router.post("/api/runs", status_code=202, response_model=RunStarted,
             responses={409: {"description": "a run is in progress"},
                        503: {"description": "the run unit could not be started"}})
def start_run(settings: Annotated[Settings, Depends(get_settings)]) -> RunStarted:
    if lock.is_held(lock.lock_path(settings.state_dir)):
        raise HTTPException(status_code=409, detail="a run is already in progress")
    try:
        spawn_run()
    except RunStartError as exc:
        raise HTTPException(status_code=503,
                            detail=f"could not start {RUN_UNIT} ({exc})") from None
    return RunStarted(status="started", unit=RUN_UNIT)

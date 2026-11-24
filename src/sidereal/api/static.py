"""Serve the built React app (``web/dist``) with an SPA fallback (plan §10.3)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

NOT_BUILT = "UI not built: run npm run build (in web/)\n"


def resolve_asset(dist: Path, rel: str) -> Path | None:
    """The file under ``dist`` for URL path ``rel``, or None (missing or outside ``dist``)."""
    if not rel:
        return None
    root = dist.resolve()
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def mount_ui(app: FastAPI, dist: Path) -> None:
    """Register the catch-all GET route. Must be added after every /api route."""

    @app.get("/{rel:path}", include_in_schema=False)
    async def ui(rel: str) -> Response:
        if rel == "api" or rel.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        index = dist / "index.html"
        if not index.is_file():
            return PlainTextResponse(NOT_BUILT, status_code=503)
        asset = resolve_asset(dist, rel)
        return FileResponse(asset if asset is not None else index)

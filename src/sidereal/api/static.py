"""Serve the built React app (``web/dist``) with an SPA fallback (plan §10.3).

Cache policy: hashed files under ``assets/`` are immutable for a year; ``index.html``, the SPA
fallback and any other file are ``no-cache`` (always revalidated). ``/api`` gets ``no-store`` in
``security.make_guard``. A missing ``assets/`` file is a 404, never the SPA shell (a stale bundle
must fail loudly, not run HTML as JavaScript).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path, PurePosixPath

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

NOT_BUILT = "UI not built: run npm run build (in web/)\n"
ASSET_CACHE = "public, max-age=31536000, immutable"
PAGE_CACHE = "no-cache"
ASSETS_PREFIX = "assets/"
# Fixed types for what Vite emits, so serving does not depend on the host's /etc/mime.types.
MEDIA_TYPES = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain",
    ".webmanifest": "application/manifest+json",
}


def is_unsafe_path(rel: str) -> bool:
    """True for a URL path that tries to leave ``dist``: absolute, ``..``, backslash or NUL."""
    if rel.startswith(("/", "\\")) or "\\" in rel or "\x00" in rel:
        return True
    return ".." in PurePosixPath(rel).parts


def resolve_asset(dist: Path, rel: str) -> Path | None:
    """The file under ``dist`` for URL path ``rel``, or None (missing or outside ``dist``).

    The resolved path must stay inside ``dist`` even after symlinks are followed.
    """
    if not rel:
        return None
    root = dist.resolve()
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


def media_type_for(path: Path) -> str:
    known = MEDIA_TYPES.get(path.suffix.lower())
    if known is not None:
        return known
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _not_found() -> Response:
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def mount_ui(app: FastAPI, dist: Path) -> None:
    """Register the catch-all GET route. Must be added after every /api route."""

    @app.get("/{rel:path}", include_in_schema=False)
    async def ui(rel: str) -> Response:
        if rel == "api" or rel.startswith("api/") or is_unsafe_path(rel):
            return _not_found()
        index = dist / "index.html"
        if not index.is_file():
            no_store = {"Cache-Control": "no-store"}
            return PlainTextResponse(NOT_BUILT, status_code=503, headers=no_store)
        asset = resolve_asset(dist, rel)
        if asset is None:
            if rel.startswith(ASSETS_PREFIX):
                return _not_found()
            asset = index
        cache = ASSET_CACHE if rel.startswith(ASSETS_PREFIX) else PAGE_CACHE
        headers = {"Cache-Control": cache}
        return FileResponse(asset, media_type=media_type_for(asset), headers=headers)

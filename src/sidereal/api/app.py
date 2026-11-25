"""``create_app(settings)``: middleware, routers, static UI. Thin: no business logic here."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sidereal import __version__, paths
from sidereal.api import (
    routes_auth,
    routes_days,
    routes_feedback,
    routes_gazette,
    routes_health,
    routes_runs,
    routes_search,
    routes_sources,
    routes_stories,
)
from sidereal.api.security import make_guard
from sidereal.api.static import mount_ui
from sidereal.auth.middleware import make_auth_middleware
from sidereal.config import Settings


def create_app(settings: Settings, *, dist_dir: Path | None = None) -> FastAPI:
    """Build the app. Touches no files or DB at creation (``sidereal openapi`` relies on it)."""
    app = FastAPI(title="Sidereal", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.include_router(routes_health.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_gazette.router)
    app.include_router(routes_days.router)
    app.include_router(routes_stories.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_sources.router)
    app.include_router(routes_feedback.router)
    app.include_router(routes_search.router)
    mount_ui(app, dist_dir or paths.web_dist_dir())  # last: catch-all GET
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.middleware("http")(make_auth_middleware(settings))  # inner: runs after the write guard
    app.middleware("http")(make_guard(settings.web))
    # Added last = outermost: a bad Host is refused before anything else runs.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.web.allowed_hosts)
    return app


async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
    """422 as usual, except under ``/api/auth/``: there the error list drops ``input`` and
    ``ctx`` so a password is never echoed back."""
    if not request.url.path.startswith("/api/auth/"):
        return await request_validation_exception_handler(request, exc)
    errors = [{k: v for k, v in e.items() if k not in ("input", "ctx", "url")}
              for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)

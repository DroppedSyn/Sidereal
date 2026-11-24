"""``create_app(settings)``: middleware, routers, static UI. Thin: no business logic here."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sidereal import __version__, paths
from sidereal.api import routes_health
from sidereal.api.security import make_guard
from sidereal.api.static import mount_ui
from sidereal.config import Settings


def create_app(settings: Settings, *, dist_dir: Path | None = None) -> FastAPI:
    """Build the app. Touches no files or DB at creation (``sidereal openapi`` relies on it)."""
    app = FastAPI(title="Sidereal", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.include_router(routes_health.router)
    mount_ui(app, dist_dir or paths.web_dist_dir())  # last: catch-all GET
    app.middleware("http")(make_guard(settings.web))
    # Added last = outermost: a bad Host is refused before anything else runs.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.web.allowed_hosts)
    return app

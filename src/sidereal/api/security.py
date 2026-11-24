"""Always-on request rules (plan §10.4, §11.1): write guard, security headers, no-store on /api.

TrustedHostMiddleware (Host allowlist, against DNS rebinding) is added in ``app.create_app``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sidereal.config import WebSettings

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

CallNext = Callable[[Request], Awaitable[Response]]


def _origin_of(url: str) -> tuple[str, str, int] | None:
    """``(scheme, host, port)`` of an Origin/Referer value, or None if unusable."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.scheme, parts.hostname.lower(), port or (443 if parts.scheme == "https" else 80)


def origin_allowed(value: str | None, web: WebSettings) -> bool:
    """An Origin (or Referer) is allowed if listed in ``allowed_origins``, or if its host is in
    ``allowed_hosts`` and its port is the app's port."""
    if not value:
        return False
    got = _origin_of(value)
    if got is None:
        return False
    listed = {o for o in (_origin_of(x) for x in web.allowed_origins) if o is not None}
    if got in listed:
        return True
    hosts = {h.lower() for h in web.allowed_hosts}
    return got[1] in hosts and got[2] == web.port


def write_rejection(request: Request, web: WebSettings) -> str | None:
    """Why a state-changing request must be refused, or None if it may proceed."""
    if request.method not in WRITE_METHODS:
        return None
    if request.headers.get("x-sidereal") != "1":
        return "missing X-Sidereal header"
    source = request.headers.get("origin") or request.headers.get("referer")
    if not origin_allowed(source, web):
        return "origin not allowed"
    return None


def make_guard(web: WebSettings) -> Callable[[Request, CallNext], Awaitable[Response]]:
    """HTTP middleware: refuse forged writes, then add headers to every response."""

    async def guard(request: Request, call_next: CallNext) -> Response:
        reason = write_rejection(request, web)
        if reason is not None:
            response: Response = JSONResponse({"detail": reason}, status_code=403)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path == "/api" or request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return guard

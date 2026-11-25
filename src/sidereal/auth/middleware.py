"""Session check for ``/api`` (plan §11.2) and the client IP used by the rate limit.

With ``auth.mode = "on"`` every ``/api`` path needs a valid session except ``PUBLIC``;
``request.state.user`` is the ``SessionUser`` or None (also on public paths, so health can answer
minimally). Paths outside ``/api`` (the SPA shell and its assets) are served without a session:
they hold no data. With auth off nothing is checked and ``request.state.user`` is None.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sidereal.auth import sessions
from sidereal.config import Settings, proxy_networks
from sidereal.db.connect import connect
from sidereal.timeutil import utc_now

PUBLIC = frozenset({"/api/health", "/api/auth/login", "/api/auth/logout"})
CallNext = Callable[[Request], Awaitable[Response]]


IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _ip(value: str) -> IPAddress | None:
    try:
        ip = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped  # ::ffff:127.0.0.1 from a dual-stack socket is 127.0.0.1
    return ip


def is_trusted(ip: IPAddress, networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network,
                                              ...]) -> bool:
    return any(ip.version == net.version and ip in net for net in networks)


def client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """The peer address; ``X-Forwarded-For`` is used only when the peer is in a trusted proxy
    network (single IPs or CIDRs, validated by ``config``), read from the right, skipping trusted
    hops (plan §11.3)."""
    peer = request.client.host if request.client else "unknown"
    trusted = proxy_networks(trusted_proxies)
    peer_ip = _ip(peer)
    if peer_ip is None or not is_trusted(peer_ip, trusted):
        return peer
    hops = [h for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        hop_ip = _ip(hop)
        if hop_ip is None:
            return peer
        if not is_trusted(hop_ip, trusted):
            return str(hop_ip)
    return peer


def lookup(settings: Settings, token: str | None, now: datetime) -> sessions.SessionUser | None:
    if not token or not settings.db_path.exists():
        return None
    conn = connect(settings.db_path)
    try:
        return sessions.resolve(conn, token, now=now)
    finally:
        conn.close()


def is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def make_auth_middleware(
    settings: Settings, *, clock: Callable[[], datetime] = utc_now
) -> Callable[[Request, CallNext], Awaitable[Response]]:
    async def auth(request: Request, call_next: CallNext) -> Response:
        request.state.user = None
        if settings.auth.mode != "on" or not is_api(request.url.path):
            return await call_next(request)
        token = request.cookies.get(sessions.COOKIE_NAME)
        user = await run_in_threadpool(lookup, settings, token, clock())
        request.state.user = user
        if user is None and request.url.path not in PUBLIC:
            response = JSONResponse({"detail": "authentication required"}, status_code=401)
            if token is not None:
                sessions.clear_cookie(response, secure=settings.web.https)
            return response
        return await call_next(request)

    return auth

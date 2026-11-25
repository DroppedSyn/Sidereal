"""Session tokens and cookies (plan §11.2).

The cookie carries a random 32-byte token (``secrets.token_urlsafe(32)``); the DB stores only its
SHA-256. Idle timeout 7 days, absolute 30 days; a login always creates a fresh session (rotation)
and drops the one the browser presented. ``last_seen_at`` is written at most every
``TOUCH_EVERY`` so reads don't turn into a write per request.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from starlette.responses import Response

from sidereal.db import users_repo
from sidereal.db.connect import Connection
from sidereal.timeutil import parse_iso_z

COOKIE_NAME = "sidereal_session"
TOKEN_BYTES = 32
IDLE = timedelta(days=7)
ABSOLUTE = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=5)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")  # token_urlsafe(32): 43 chars, no padding


@dataclass(frozen=True)
class SessionUser:
    user_id: int
    username: str


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create(conn: Connection, user_id: int, *, now: datetime, user_agent: str | None,
           ip: str | None) -> str:
    """Store a new session and return its token (the only time the token exists server-side)."""
    token = new_token()
    users_repo.create_session(conn, token_hash(token), user_id, now=now, expires_at=now + ABSOLUTE,
                              user_agent=(user_agent or "")[:200] or None, ip=ip)
    return token


def resolve(conn: Connection, token: str | None, *, now: datetime) -> SessionUser | None:
    """The user behind a cookie token, or None (missing, malformed, unknown, expired, disabled).

    Expired sessions are deleted on sight. The stored hash is compared with
    ``hmac.compare_digest`` after the lookup (defence in depth: the lookup itself is by hash)."""
    if not token or not _TOKEN.fullmatch(token):
        return None
    digest = token_hash(token)
    row = users_repo.get_session(conn, digest)
    if row is None or not hmac.compare_digest(row.id_hash, digest):
        return None
    last_seen = parse_iso_z(row.last_seen_at)
    if now >= parse_iso_z(row.expires_at) or now - last_seen >= IDLE:
        users_repo.delete_session(conn, digest)
        return None
    if row.disabled:
        return None
    if now - last_seen >= TOUCH_EVERY:
        users_repo.touch_session(conn, digest, now=now)
    return SessionUser(user_id=row.user_id, username=row.username)


def revoke(conn: Connection, token: str | None) -> None:
    if token and _TOKEN.fullmatch(token):
        users_repo.delete_session(conn, token_hash(token))


def set_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=int(ABSOLUTE.total_seconds()), path="/",
                        httponly=True, samesite="strict", secure=secure)


def clear_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict", secure=secure)

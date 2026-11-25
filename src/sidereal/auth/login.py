"""The login decision (plan §11.2): rate limit → password (dummy hash for unknown/disabled users)
→ TOTP → fresh session. Every failure looks the same to the caller; logs carry the client IP and
never the password, the code, the token or the submitted username.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sidereal.auth import passwords, ratelimit, sessions, totp
from sidereal.config import AuthSettings
from sidereal.db import users_repo
from sidereal.db.connect import Connection

log = logging.getLogger("sidereal.auth")

USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_USERNAME = 64

# Last TOTP step accepted per (user id, secret): a code is accepted once (RFC 6238 §5.2, no replay).
# In-process like the rate-limit lock (one uvicorn worker); a restart forgets it, and a code is
# only valid for about 90 s anyway.
_TOTP_LOCK = threading.Lock()
_last_totp_step: dict[tuple[int, str], int] = {}


@dataclass(frozen=True)
class LoginResult:
    status: Literal["ok", "invalid", "limited"]
    token: str | None = None
    username: str | None = None


def normalize_username(name: str) -> str:
    return name.strip().lower()


def valid_username(name: str) -> bool:
    return USERNAME.fullmatch(name) is not None


def _second_factor(user: users_repo.UserRow, code: str | None, auth: AuthSettings,
                   now: datetime) -> bool:
    if user.totp_secret is None:
        if auth.require_totp:
            log.warning("auth: login refused, auth.require_totp is on and user id %d has no TOTP"
                        " (sidereal user totp NAME)", user.id)
            return False
        return True
    step = totp.matching_step(user.totp_secret, code, now.timestamp())
    if step is None:
        return False
    with _TOTP_LOCK:
        key = (user.id, user.totp_secret)
        if step <= _last_totp_step.get(key, -1):
            log.warning("auth: TOTP code reused for user id %d", user.id)
            return False
        _last_totp_step[key] = step
    return True


def authenticate(conn: Connection, auth: AuthSettings, *, username: str, password: str,
                 code: str | None, ip: str, user_agent: str | None, now: datetime,
                 old_token: str | None = None) -> LoginResult:
    name = normalize_username(username)[:MAX_USERNAME]
    attempt_id = ratelimit.reserve(conn, name, ip, now=now)
    if attempt_id is None:
        log.warning("auth: login rate-limited ip=%s", ip)
        return LoginResult("limited")
    user = users_repo.get_by_username(conn, name) if valid_username(name) else None
    if user is None or user.disabled:
        passwords.dummy_verify(password)
        ok = False
    else:
        ok = passwords.verify(user.pw_hash, password) and _second_factor(user, code, auth, now)
    if not ok or user is None:
        log.warning("auth: login failed ip=%s", ip)
        return LoginResult("invalid")
    ratelimit.succeeded(conn, attempt_id)
    if passwords.needs_rehash(user.pw_hash):
        users_repo.set_password(conn, user.id, passwords.hash_password(password))
    sessions.revoke(conn, old_token)  # rotation: never keep a pre-login session id
    users_repo.delete_expired_sessions(conn, now=now, idle_before=now - sessions.IDLE)
    token = sessions.create(conn, user.id, now=now, user_agent=user_agent, ip=ip)
    log.info("auth: login ok user_id=%d ip=%s", user.id, ip)
    return LoginResult("ok", token=token, username=user.username)

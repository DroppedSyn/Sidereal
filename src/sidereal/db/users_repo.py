"""Repository for ``users``, ``sessions`` and ``login_attempts`` (M25, plan §11.2).

Only hashes are stored: ``pw_hash`` is an Argon2id string, ``sessions.id_hash`` the SHA-256 of
the cookie token. Times are passed in as aware datetimes and stored via ``iso_z``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sidereal.db.connect import connect_readonly
from sidereal.timeutil import iso_z


class UserExists(Exception):
    """``add_user`` with a username that is already taken."""


@dataclass(frozen=True)
class UserRow:
    id: int
    username: str
    pw_hash: str
    created_at: str
    totp_secret: str | None
    disabled: bool


@dataclass(frozen=True)
class SessionRow:
    id_hash: str
    user_id: int
    username: str
    disabled: bool
    created_at: str
    last_seen_at: str
    expires_at: str


def _user(row: sqlite3.Row | None) -> UserRow | None:
    if row is None:
        return None
    return UserRow(id=row["id"], username=row["username"], pw_hash=row["pw_hash"],
                   created_at=row["created_at"], totp_secret=row["totp_secret"],
                   disabled=bool(row["disabled"]))


# --- users ---------------------------------------------------------------------------------

def add_user(conn: sqlite3.Connection, username: str, pw_hash: str, *, now: datetime) -> int:
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, pw_hash, created_at) VALUES (?, ?, ?)",
                (username, pw_hash, iso_z(now)),
            )
    except sqlite3.IntegrityError:
        raise UserExists(username) from None
    return int(cur.lastrowid)


def get_user(conn: sqlite3.Connection, user_id: int) -> UserRow | None:
    return _user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_by_username(conn: sqlite3.Connection, username: str) -> UserRow | None:
    return _user(conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone())


def list_users(conn: sqlite3.Connection) -> list[UserRow]:
    return [_user(r) for r in conn.execute("SELECT * FROM users ORDER BY username").fetchall()]


def count_active_users(conn: sqlite3.Connection) -> int:
    """Users that can log in (rule 9 counts these)."""
    return int(conn.execute("SELECT count(*) FROM users WHERE disabled = 0").fetchone()[0])


def count_active_users_at(path: Path) -> int:
    """``count_active_users`` on the DB at ``path`` opened read-only (never creates it); 0 when
    the file or the ``users`` table is missing (used by ``serve`` before migrating)."""
    if not Path(path).exists():
        return 0
    try:
        conn = connect_readonly(path)
    except sqlite3.Error:
        return 0
    try:
        return count_active_users(conn)
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def set_password(conn: sqlite3.Connection, user_id: int, pw_hash: str) -> None:
    with conn:
        cur = conn.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (pw_hash, user_id))
    if cur.rowcount == 0:
        raise KeyError(user_id)


def set_totp(conn: sqlite3.Connection, user_id: int, secret: str | None) -> None:
    with conn:
        cur = conn.execute("UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user_id))
    if cur.rowcount == 0:
        raise KeyError(user_id)


def delete_user(conn: sqlite3.Connection, user_id: int) -> bool:
    """Delete the user and (ON DELETE CASCADE) their sessions. False if unknown."""
    with conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


# --- sessions ------------------------------------------------------------------------------

def create_session(conn: sqlite3.Connection, id_hash: str, user_id: int, *, now: datetime,
                   expires_at: datetime, user_agent: str | None, ip: str | None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO sessions (id_hash, user_id, created_at, last_seen_at, expires_at,"
            " user_agent, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_hash, user_id, iso_z(now), iso_z(now), iso_z(expires_at), user_agent, ip),
        )


def get_session(conn: sqlite3.Connection, id_hash: str) -> SessionRow | None:
    row = conn.execute(
        "SELECT s.id_hash, s.user_id, u.username, u.disabled, s.created_at, s.last_seen_at,"
        " s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id_hash = ?",
        (id_hash,),
    ).fetchone()
    if row is None:
        return None
    return SessionRow(id_hash=row["id_hash"], user_id=row["user_id"], username=row["username"],
                      disabled=bool(row["disabled"]), created_at=row["created_at"],
                      last_seen_at=row["last_seen_at"], expires_at=row["expires_at"])


def touch_session(conn: sqlite3.Connection, id_hash: str, *, now: datetime) -> None:
    with conn:
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id_hash = ?",
                     (iso_z(now), id_hash))


def delete_session(conn: sqlite3.Connection, id_hash: str) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE id_hash = ?", (id_hash,))
    return cur.rowcount > 0


def delete_user_sessions(conn: sqlite3.Connection, user_id: int) -> int:
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return cur.rowcount


def delete_expired_sessions(conn: sqlite3.Connection, *, now: datetime,
                            idle_before: datetime) -> int:
    """Sessions past their absolute expiry or last seen before ``idle_before``."""
    with conn:
        cur = conn.execute(
            "DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at < ?",
            (iso_z(now), iso_z(idle_before)),
        )
    return cur.rowcount


def count_sessions(conn: sqlite3.Connection, user_id: int) -> int:
    return int(conn.execute("SELECT count(*) FROM sessions WHERE user_id = ?",
                            (user_id,)).fetchone()[0])


# --- login attempts ------------------------------------------------------------------------

def record_attempt(conn: sqlite3.Connection, username: str, ip: str, *, at: datetime,
                   ok: bool) -> None:
    with conn:
        conn.execute("INSERT INTO login_attempts (username, ip, at, ok) VALUES (?, ?, ?, ?)",
                     (username, ip, iso_z(at), int(ok)))


@dataclass(frozen=True)
class FailureCounts:
    user_ip: int
    user: int
    ip: int


def count_failures(conn: sqlite3.Connection, username: str, ip: str, *,
                   since: datetime) -> FailureCounts:
    """Failed attempts at or after ``since``: for this username+IP, the username, the IP."""
    row = conn.execute(
        "SELECT"
        " coalesce(sum(username = ? AND ip = ?), 0) AS user_ip,"
        " coalesce(sum(username = ?), 0) AS user,"
        " coalesce(sum(ip = ?), 0) AS ip"
        " FROM login_attempts WHERE ok = 0 AND at >= ? AND (username = ? OR ip = ?)",
        (username, ip, username, ip, iso_z(since), username, ip),
    ).fetchone()
    return FailureCounts(user_ip=int(row["user_ip"]), user=int(row["user"]), ip=int(row["ip"]))


def prune_attempts(conn: sqlite3.Connection, *, before: datetime) -> int:
    with conn:
        cur = conn.execute("DELETE FROM login_attempts WHERE at < ?", (iso_z(before),))
    return cur.rowcount

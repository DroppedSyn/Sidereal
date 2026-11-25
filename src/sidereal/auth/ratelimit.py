"""Login rate limit, kept in the DB so it survives restarts (plan §11.2).

Failed attempts in the last ``WINDOW``: 5 per username+IP (the plan's rule), plus 20 per IP across
usernames (password spraying) and 50 per username across IPs (distributed guessing; a bounded
lockout risk for that name, accepted). Counts are by the *submitted* username, so an unknown
name is limited exactly like a real one.

``reserve`` checks the limit and records the attempt as a failure under one process-wide lock,
before the (slow) password check; a success then flips it with ``succeeded``. Checking first and
recording after the check would let parallel requests all pass the limit at once.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from sidereal.db import users_repo
from sidereal.db.connect import Connection

WINDOW = timedelta(minutes=15)
MAX_PER_USER_IP = 5
MAX_PER_IP = 20
MAX_PER_USER = 50
KEEP = timedelta(days=1)

_LOCK = threading.Lock()


def is_limited(conn: Connection, username: str, ip: str, *, now: datetime) -> bool:
    c = users_repo.count_failures(conn, username, ip, since=now - WINDOW)
    return c.user_ip >= MAX_PER_USER_IP or c.ip >= MAX_PER_IP or c.user >= MAX_PER_USER


def reserve(conn: Connection, username: str, ip: str, *, now: datetime) -> int | None:
    """None if limited; else the id of a new attempt row, recorded as failed until
    ``succeeded``. Check and insert are atomic within this process (one uvicorn worker)."""
    with _LOCK:
        if is_limited(conn, username, ip, now=now):
            return None
        attempt_id = users_repo.record_attempt(conn, username, ip, at=now, ok=False)
    users_repo.prune_attempts(conn, before=now - KEEP)
    return attempt_id


def succeeded(conn: Connection, attempt_id: int) -> None:
    users_repo.mark_attempt_ok(conn, attempt_id)


def retry_after_s() -> int:
    return int(WINDOW.total_seconds())

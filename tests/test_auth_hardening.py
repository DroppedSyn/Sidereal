"""Regression tests from the M25 security review: timing on over-long passwords, the rate limit
under parallel requests, TOTP replay."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from sidereal.auth import login as lg
from sidereal.auth import passwords, ratelimit, totp
from sidereal.config import AuthSettings
from sidereal.db import users_repo
from sidereal.db.connect import connect
from tests.auth_helpers import NOW, PASSWORD, add_user, fast_hasher  # noqa: F401

pytestmark = pytest.mark.usefixtures("fast_hasher")
ON = AuthSettings(mode="on")
IP = "10.0.0.5"


def attempt(conn, name="owner", password=PASSWORD, *, code=None, now=NOW):
    return lg.authenticate(conn, ON, username=name, password=password, code=code, ip=IP,
                           user_agent="pytest", now=now)


def _count_argon2(monkeypatch) -> list[str]:
    calls: list[str] = []
    real = passwords._check

    def spy(h, pw):
        calls.append(h)
        return real(h, pw)

    monkeypatch.setattr(passwords, "_check", spy)
    return calls


def test_overlong_password_for_known_user_still_costs_argon2(db, monkeypatch):
    """A known user must not answer faster than an unknown one (user enumeration by timing)."""
    add_user(db)
    calls = _count_argon2(monkeypatch)
    assert attempt(db, password="x" * (passwords.MAX_LENGTH + 1)).status == "invalid"
    known = len(calls)
    assert attempt(db, name="nobody", password="x" * (passwords.MAX_LENGTH + 1)).status == "invalid"
    assert known == 1 and len(calls) == 2


def test_overlong_password_never_matches(db):
    long = "y" * (passwords.MAX_LENGTH + 5)
    users_repo.add_user(db, "longpw", passwords.hash_password(long), now=NOW)
    assert attempt(db, "longpw", long).status == "invalid"


def test_parallel_failures_cannot_exceed_the_limit(db, settings, monkeypatch):
    """Check and record are atomic: a burst of parallel wrong passwords gets 5 tries, not 20."""
    add_user(db)
    real = passwords.verify
    gate = threading.Barrier(20, timeout=5)

    def slow_verify(h, pw):
        try:
            gate.wait()  # all requests reach the password check together (if they can)
        except threading.BrokenBarrierError:
            pass
        return real(h, pw)

    monkeypatch.setattr(passwords, "verify", slow_verify)

    def one(i: int) -> str:
        conn = connect(settings.db_path)
        try:
            return attempt(conn, password=f"wrong password {i}").status
        finally:
            conn.close()

    with ThreadPoolExecutor(20) as ex:
        results = list(ex.map(one, range(20)))
    assert results.count("invalid") == ratelimit.MAX_PER_USER_IP
    assert results.count("limited") == 20 - ratelimit.MAX_PER_USER_IP


def test_successful_logins_do_not_count_as_failures(db):
    add_user(db)
    for i in range(ratelimit.MAX_PER_USER_IP + 2):
        assert attempt(db, now=NOW + timedelta(seconds=i)).status == "ok"
    counts = users_repo.count_failures(db, "owner", IP, since=NOW - ratelimit.WINDOW)
    assert counts.user_ip == 0


def test_failure_then_success_counts_one_failure(db):
    add_user(db)
    attempt(db, password="wrong password!")
    attempt(db)
    assert users_repo.count_failures(db, "owner", IP, since=NOW - ratelimit.WINDOW).user_ip == 1


def test_totp_code_is_accepted_once(db):
    uid = add_user(db)
    secret = totp.new_secret()
    users_repo.set_totp(db, uid, secret)
    t = NOW.timestamp()
    code = totp.code_at(secret, t)
    assert attempt(db, code=code).status == "ok"
    assert attempt(db, code=code, now=NOW + timedelta(seconds=5)).status == "invalid"
    # an older step inside the window is refused too; the next step works
    assert attempt(db, code=totp.code_at(secret, t - 30)).status == "invalid"
    assert attempt(db, code=totp.code_at(secret, t + 30)).status == "ok"


def test_matching_step_returns_the_counter():
    secret = totp.new_secret()
    t = time.time()
    assert totp.matching_step(secret, totp.code_at(secret, t), t) == int(t // 30)
    assert totp.matching_step(secret, totp.code_at(secret, t + 30), t) == int(t // 30) + 1
    assert totp.matching_step(secret, "abcdef", t) is None
    assert totp.matching_step(secret, None, t) is None

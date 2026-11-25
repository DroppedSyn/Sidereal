"""auth/login.py + auth/ratelimit.py (M25): the login decision and its rate limit."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from sidereal.auth import login as lg
from sidereal.auth import passwords, ratelimit, sessions, totp
from sidereal.config import AuthSettings
from sidereal.db import users_repo
from tests.auth_helpers import NOW, PASSWORD, add_user, fast_hasher  # noqa: F401

pytestmark = pytest.mark.usefixtures("fast_hasher")
ON = AuthSettings(mode="on")
IP = "10.0.0.5"


def attempt(db, name="owner", password=PASSWORD, *, code=None, ip=IP, now=NOW, auth=ON,
            old_token=None):
    return lg.authenticate(db, auth, username=name, password=password, code=code, ip=ip,
                           user_agent="pytest", now=now, old_token=old_token)


def test_success_creates_session(db):
    uid = add_user(db)
    res = attempt(db, " Owner ")  # normalised: stripped, lower-case
    assert (res.status, res.username) == ("ok", "owner")
    assert sessions.resolve(db, res.token, now=NOW) == sessions.SessionUser(uid, "owner")


def test_wrong_password_and_unknown_user_look_the_same(db):
    add_user(db)
    wrong = attempt(db, password="wrong password!")
    unknown = attempt(db, name="nobody", password="wrong password!")
    bad_name = attempt(db, name="Ünïcode name with spaces")
    assert wrong == unknown == bad_name == lg.LoginResult("invalid")


def test_unknown_and_disabled_user_do_argon2_work(db, monkeypatch):
    uid = add_user(db)
    db.execute("UPDATE users SET disabled = 1 WHERE id = ?", (uid,))
    db.commit()
    calls = []
    monkeypatch.setattr(passwords, "dummy_verify", lambda pw: calls.append("dummy"))
    assert attempt(db, name="nobody").status == "invalid"
    assert attempt(db).status == "invalid"  # disabled, even with the right password
    assert calls == ["dummy", "dummy"]


def test_rate_limit_per_user_and_ip(db):
    add_user(db)
    for _ in range(ratelimit.MAX_PER_USER_IP):
        assert attempt(db, password="wrong password!").status == "invalid"
    # Locked even with the right password, for this user from this IP.
    assert attempt(db).status == "limited"
    assert attempt(db, ip="10.0.0.6").status == "ok"
    # The window passes.
    assert attempt(db, now=NOW + ratelimit.WINDOW + timedelta(seconds=1)).status == "ok"


def test_rate_limit_unknown_user_same_as_known(db):
    add_user(db)
    for _ in range(ratelimit.MAX_PER_USER_IP):
        attempt(db, name="nobody", password="wrong password!")
        attempt(db, password="wrong password!", ip="10.9.9.9")
    assert attempt(db, name="nobody").status == "limited"
    assert attempt(db, ip="10.9.9.9", password="wrong password!").status == "limited"


def test_rate_limit_per_ip_across_usernames(db):
    add_user(db)
    for i in range(ratelimit.MAX_PER_IP):
        attempt(db, name=f"spray{i}", password="wrong password!")
    assert attempt(db).status == "limited"
    assert attempt(db, ip="10.0.0.6").status == "ok"


def test_rate_limit_per_user_across_ips(db):
    add_user(db)
    for i in range(ratelimit.MAX_PER_USER):
        attempt(db, password="wrong password!", ip=f"10.1.{i // 250}.{i % 250}")
    assert attempt(db, ip="10.2.0.1").status == "limited"
    assert attempt(db, name="other", ip="10.2.0.1").status == "invalid"  # IP itself fine


def test_old_attempts_pruned(db):
    attempt(db, name="x", password="wrong password!", now=NOW - timedelta(days=2))
    attempt(db, name="x", password="wrong password!")
    assert db.execute("SELECT count(*) FROM login_attempts").fetchone()[0] == 1


def test_login_rotates_session(db):
    uid = add_user(db)
    first = attempt(db).token
    second = attempt(db, old_token=first).token
    assert second != first
    assert sessions.resolve(db, first, now=NOW) is None
    assert sessions.resolve(db, second, now=NOW) is not None
    assert users_repo.count_sessions(db, uid) == 1


def test_login_prunes_expired_sessions(db):
    uid = add_user(db)
    attempt(db)
    attempt(db, now=NOW + timedelta(days=8))
    assert users_repo.count_sessions(db, uid) == 1


def test_weak_hash_rehashed_on_login(db, monkeypatch):
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    uid = users_repo.add_user(db, "owner", weak, now=NOW)
    monkeypatch.setattr(passwords, "_hasher",
                        PasswordHasher(time_cost=2, memory_cost=16, parallelism=1))
    assert attempt(db).status == "ok"
    new = users_repo.get_user(db, uid).pw_hash
    assert new != weak and passwords.verify(new, PASSWORD)


def test_totp_required_for_user_with_secret(db):
    uid = add_user(db)
    secret = totp.new_secret()
    users_repo.set_totp(db, uid, secret)
    good = totp.code_at(secret, NOW.timestamp())
    assert attempt(db).status == "invalid"  # no code
    assert attempt(db, code="000000" if good != "000000" else "111111").status == "invalid"
    assert attempt(db, password="wrong password!", code=good).status == "invalid"
    assert attempt(db, code=good).status == "ok"


def test_require_totp_refuses_user_without_secret(db, caplog):
    add_user(db)
    caplog.set_level(logging.WARNING, logger="sidereal.auth")
    assert attempt(db, auth=AuthSettings(mode="on", require_totp=True)).status == "invalid"
    assert "require_totp" in caplog.text


def test_logs_never_hold_secrets(db, caplog):
    add_user(db)
    caplog.set_level(logging.DEBUG)
    attempt(db, password="wrong password!")
    ok = attempt(db)
    attempt(db, name="nobody", password="other secret!")
    text = caplog.text
    for secret in (PASSWORD, "wrong password!", "other secret!", ok.token, "nobody"):
        assert secret not in text
    assert f"login failed ip={IP}" in text and f"login ok user_id=1 ip={IP}" in text

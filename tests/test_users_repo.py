"""db/users_repo.py (M25): users, sessions, login attempts."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from sidereal.db import users_repo as r
from sidereal.db.connect import connect
from sidereal.db.migrations import apply_migrations
from tests.auth_helpers import NOW


def test_add_get_list_and_duplicate(db):
    uid = r.add_user(db, "owner", "hash-1", now=NOW)
    u = r.get_user(db, uid)
    assert (u.username, u.pw_hash, u.created_at, u.totp_secret, u.disabled) == (
        "owner", "hash-1", "2026-07-14T08:00:00Z", None, False)
    assert r.get_by_username(db, "owner") == u
    assert r.get_by_username(db, "nobody") is None and r.get_user(db, 999) is None
    with pytest.raises(r.UserExists):
        r.add_user(db, "owner", "hash-2", now=NOW)
    r.add_user(db, "alice", "h", now=NOW)
    assert [x.username for x in r.list_users(db)] == ["alice", "owner"]


def test_count_active_users_skips_disabled(db):
    assert r.count_active_users(db) == 0
    a = r.add_user(db, "a", "h", now=NOW)
    r.add_user(db, "b", "h", now=NOW)
    db.execute("UPDATE users SET disabled = 1 WHERE id = ?", (a,))
    db.commit()
    assert r.count_active_users(db) == 1


def test_count_active_users_at(tmp_path):
    path = tmp_path / "x.db"
    assert r.count_active_users_at(path) == 0
    assert not path.exists()  # never creates
    conn = connect(path)
    conn.execute("CREATE TABLE schema_version (version INTEGER, applied_at TEXT)")
    conn.commit()
    assert r.count_active_users_at(path) == 0  # no users table yet
    apply_migrations(conn)
    r.add_user(conn, "owner", "h", now=NOW)
    conn.close()
    assert r.count_active_users_at(path) == 1


def test_set_password_totp_and_unknown(db):
    uid = r.add_user(db, "owner", "old", now=NOW)
    r.set_password(db, uid, "new")
    r.set_totp(db, uid, "SECRET")
    u = r.get_user(db, uid)
    assert (u.pw_hash, u.totp_secret) == ("new", "SECRET")
    r.set_totp(db, uid, None)
    assert r.get_user(db, uid).totp_secret is None
    with pytest.raises(KeyError):
        r.set_password(db, 999, "x")
    with pytest.raises(KeyError):
        r.set_totp(db, 999, "x")


def _session(db, id_hash, uid, *, now=NOW, days=30):
    r.create_session(db, id_hash, uid, now=now, expires_at=now + timedelta(days=days),
                     user_agent="ua", ip="10.0.0.1")


def test_sessions_create_get_touch_delete(db):
    uid = r.add_user(db, "owner", "h", now=NOW)
    _session(db, "h1", uid)
    s = r.get_session(db, "h1")
    assert (s.user_id, s.username, s.disabled, s.last_seen_at, s.expires_at) == (
        uid, "owner", False, "2026-07-14T08:00:00Z", "2026-08-13T08:00:00Z")
    r.touch_session(db, "h1", now=NOW + timedelta(hours=1))
    assert r.get_session(db, "h1").last_seen_at == "2026-07-14T09:00:00Z"
    assert r.count_sessions(db, uid) == 1
    assert r.delete_session(db, "h1") is True
    assert r.delete_session(db, "h1") is False
    assert r.get_session(db, "h1") is None


def test_delete_user_removes_sessions(db):
    uid = r.add_user(db, "owner", "h", now=NOW)
    other = r.add_user(db, "other", "h", now=NOW)
    _session(db, "h1", uid)
    _session(db, "h2", uid)
    _session(db, "h3", other)
    assert r.delete_user_sessions(db, uid) == 2
    _session(db, "h4", uid)
    assert r.delete_user(db, uid) is True
    assert r.get_session(db, "h4") is None and r.get_session(db, "h3") is not None
    assert r.delete_user(db, uid) is False


def test_session_needs_existing_user(db):
    with pytest.raises(sqlite3.IntegrityError):
        _session(db, "h1", 42)


def test_delete_expired_sessions(db):
    uid = r.add_user(db, "owner", "h", now=NOW)
    _session(db, "fresh", uid)
    _session(db, "absolute", uid, now=NOW - timedelta(days=1), days=1)  # expires exactly NOW
    _session(db, "idle", uid, now=NOW - timedelta(days=8))
    n = r.delete_expired_sessions(db, now=NOW, idle_before=NOW - timedelta(days=7))
    assert n == 2
    assert r.get_session(db, "fresh") is not None


def test_attempt_counts_by_user_ip_user_and_ip(db):
    since = NOW - timedelta(minutes=15)
    r.record_attempt(db, "owner", "1.1.1.1", at=NOW, ok=False)
    r.record_attempt(db, "owner", "2.2.2.2", at=NOW, ok=False)
    r.record_attempt(db, "other", "1.1.1.1", at=NOW, ok=False)
    r.record_attempt(db, "owner", "1.1.1.1", at=NOW, ok=True)  # successes don't count
    r.record_attempt(db, "owner", "1.1.1.1", at=since - timedelta(seconds=1), ok=False)  # too old
    r.record_attempt(db, "owner", "1.1.1.1", at=since, ok=False)  # at the edge: counts
    c = r.count_failures(db, "owner", "1.1.1.1", since=since)
    assert (c.user_ip, c.user, c.ip) == (2, 3, 3)
    assert r.count_failures(db, "x", "9.9.9.9", since=since) == r.FailureCounts(0, 0, 0)


def test_prune_attempts(db):
    r.record_attempt(db, "a", "ip", at=NOW - timedelta(days=2), ok=False)
    r.record_attempt(db, "a", "ip", at=NOW, ok=False)
    assert r.prune_attempts(db, before=NOW - timedelta(days=1)) == 1
    assert r.count_failures(db, "a", "ip", since=NOW - timedelta(days=9)).user_ip == 1

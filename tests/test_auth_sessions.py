"""auth/sessions.py (M25): hashed tokens, expiry, rotation helpers, cookie flags."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from starlette.responses import Response

from sidereal.auth import sessions as s
from sidereal.db import users_repo
from tests.auth_helpers import NOW


def _user(db):
    return users_repo.add_user(db, "owner", "h", now=NOW)


def _stored_hashes(db):
    return [r[0] for r in db.execute("SELECT id_hash FROM sessions").fetchall()]


def test_token_is_random_32_bytes_and_only_its_hash_is_stored(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent="ua", ip="1.2.3.4")
    assert len(token) == 43  # token_urlsafe(32)
    assert s.create(db, uid, now=NOW, user_agent=None, ip=None) != token
    stored = _stored_hashes(db)
    assert hashlib.sha256(token.encode()).hexdigest() in stored
    dump = "\n".join(db.iterdump())
    assert token not in dump


def test_resolve_valid_session(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent="ua", ip="1.2.3.4")
    assert s.resolve(db, token, now=NOW + timedelta(days=1)) == s.SessionUser(uid, "owner")


def test_cookie_not_matching_any_hash_is_rejected(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert s.resolve(db, flipped, now=NOW) is None
    # The stored hash itself is not a valid cookie value either.
    assert s.resolve(db, _stored_hashes(db)[0], now=NOW) is None
    for bad in (None, "", "x" * 43 + "=", "../../etc", token + "x"):
        assert s.resolve(db, bad, now=NOW) is None


def test_resolve_compares_with_compare_digest(db, monkeypatch):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    monkeypatch.setattr(s.hmac, "compare_digest", lambda a, b: False)
    assert s.resolve(db, token, now=NOW) is None


def test_absolute_expiry(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    t = NOW
    while t < NOW + s.ABSOLUTE - timedelta(days=6):  # stay active, never idle
        t += timedelta(days=6)
        assert s.resolve(db, token, now=t) is not None
    assert s.resolve(db, token, now=NOW + s.ABSOLUTE) is None
    assert _stored_hashes(db) == []  # deleted on sight


def test_idle_expiry(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    assert s.resolve(db, token, now=NOW + s.IDLE - timedelta(seconds=1)) is not None
    later = NOW + s.IDLE - timedelta(seconds=1) + s.IDLE  # idle again from the last touch
    assert s.resolve(db, token, now=later) is None
    assert _stored_hashes(db) == []


def test_touch_is_throttled(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    s.resolve(db, token, now=NOW + timedelta(minutes=4))
    assert users_repo.get_session(db, s.token_hash(token)).last_seen_at == "2026-07-14T08:00:00Z"
    s.resolve(db, token, now=NOW + timedelta(minutes=5))
    assert users_repo.get_session(db, s.token_hash(token)).last_seen_at == "2026-07-14T08:05:00Z"


def test_disabled_user_session_rejected(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    db.execute("UPDATE users SET disabled = 1")
    db.commit()
    assert s.resolve(db, token, now=NOW) is None


def test_revoke(db):
    uid = _user(db)
    token = s.create(db, uid, now=NOW, user_agent=None, ip=None)
    s.revoke(db, None)
    s.revoke(db, "garbage")
    assert len(_stored_hashes(db)) == 1
    s.revoke(db, token)
    assert s.resolve(db, token, now=NOW) is None


def test_user_agent_truncated(db):
    uid = _user(db)
    s.create(db, uid, now=NOW, user_agent="u" * 500, ip=None)
    assert len(db.execute("SELECT user_agent FROM sessions").fetchone()[0]) == 200


def _cookie(secure: bool) -> str:
    r = Response()
    s.set_cookie(r, "tok", secure=secure)
    return r.headers["set-cookie"]


def test_cookie_flags():
    plain = _cookie(False)
    assert plain.startswith("sidereal_session=tok;")
    assert "HttpOnly" in plain and "SameSite=strict" in plain and "Path=/" in plain
    assert f"Max-Age={int(s.ABSOLUTE.total_seconds())}" in plain
    assert "Secure" not in plain
    assert "Secure" in _cookie(True)


def test_clear_cookie():
    r = Response()
    s.clear_cookie(r, secure=True)
    h = r.headers["set-cookie"]
    assert h.startswith('sidereal_session="";') and "Max-Age=0" in h and "Secure" in h

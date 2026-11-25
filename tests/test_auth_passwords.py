"""auth/passwords.py (M25): Argon2id hashing, policy, dummy verify."""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from sidereal.auth import passwords as p


def test_hash_is_argon2id_and_verifies():
    h = p.hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert "correct horse battery" not in h
    assert p.verify(h, "correct horse battery") is True
    assert p.verify(h, "correct horse batterY") is False
    assert p.hash_password("correct horse battery") != h  # salted


def test_verify_never_raises():
    assert p.verify("not a hash", "whatever password") is False
    assert p.verify("", "whatever password") is False
    h = p.hash_password("x" * 12)
    assert p.verify(h, "x" * (p.MAX_LENGTH + 1)) is False


def test_needs_rehash():
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("x" * 12)
    assert p.needs_rehash(weak) is True
    assert p.needs_rehash(p.hash_password("x" * 12)) is False
    assert p.needs_rehash("garbage") is False


@pytest.mark.parametrize("pw", ["", "short", "x" * 11, " " * 12, "x" * (p.MAX_LENGTH + 1)])
def test_policy_rejects(pw):
    with pytest.raises(p.WeakPassword) as e:
        p.check_policy(pw)
    assert pw.strip() == "" or pw not in str(e.value)


def test_policy_accepts():
    p.check_policy("x" * 12)
    p.check_policy("x" * p.MAX_LENGTH)


def test_dummy_verify_does_real_argon2_work(monkeypatch):
    calls = []
    real = p.verify

    def spy(h, pw):
        calls.append(real(h, pw))
        return calls[-1]

    monkeypatch.setattr(p, "verify", spy)
    p.dummy_verify("anything at all")
    assert calls == [False]
    assert p._dummy_hash().startswith("$argon2id$")

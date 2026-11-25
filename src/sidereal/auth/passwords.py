"""Argon2id password hashing (argon2-cffi defaults) and the password policy (plan §11.2)."""

from __future__ import annotations

from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 1024  # bounds hashing work per request

_hasher = PasswordHasher()  # Argon2id, library defaults


class WeakPassword(ValueError):
    """The password does not meet the policy (message safe to show; never contains it)."""


def check_policy(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"password must be at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        raise WeakPassword(f"password must be at most {MAX_LENGTH} characters")
    if password.strip() == "":
        raise WeakPassword("password must not be blank")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify(pw_hash: str, password: str) -> bool:
    """True if ``password`` matches; a corrupt hash or an over-long password is a mismatch."""
    if len(password) > MAX_LENGTH:
        return False
    try:
        return _hasher.verify(pw_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(pw_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(pw_hash)
    except InvalidHashError:
        return False


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return _hasher.hash("sidereal dummy password, never valid for any account")


def dummy_verify(password: str) -> None:
    """Spend the same Argon2 work as a real check (unknown or disabled user: no timing hint)."""
    verify(_dummy_hash(), password[:MAX_LENGTH])

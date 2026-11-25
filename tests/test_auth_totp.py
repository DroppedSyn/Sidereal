"""auth/totp.py (M25): RFC 6238 vectors, window, constant-time compare, URI."""

from __future__ import annotations

import base64

import pytest

from sidereal.auth import totp

# RFC 6238 appendix B, SHA-1 key "12345678901234567890" (8-digit values, last 6 digits here).
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(("t", "code"), [
    (59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
    (1234567890, "005924"), (2000000000, "279037"),
])
def test_rfc6238_vectors(t, code):
    assert totp.code_at(RFC_SECRET, t) == code


def test_verify_window_and_format():
    t = 1234567890
    now_code = totp.code_at(RFC_SECRET, t)
    assert totp.verify(RFC_SECRET, now_code, t)
    assert totp.verify(RFC_SECRET, f" {now_code[:3]} {now_code[3:]} ", t)
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, t - 30), t)
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, t + 30), t)
    assert not totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, t - 60), t)
    for bad in (None, "", "12345", "1234567", "abcdef", "00000a"):
        assert not totp.verify(RFC_SECRET, bad, t)


def test_verify_uses_compare_digest(monkeypatch):
    seen = []
    real = totp.hmac.compare_digest
    monkeypatch.setattr(totp.hmac, "compare_digest", lambda a, b: seen.append(1) or real(a, b))
    t = 1234567890
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, t - 30), t)  # matches the first step
    assert len(seen) == 3  # every step in the window is compared, no early exit


def test_new_secret_and_uri():
    s = totp.new_secret()
    assert len(base64.b32decode(s + "=" * (-len(s) % 8))) == 20
    assert totp.new_secret() != s
    uri = totp.provisioning_uri(s, "owner")
    assert uri == f"otpauth://totp/Sidereal:owner?secret={s}&issuer=Sidereal"

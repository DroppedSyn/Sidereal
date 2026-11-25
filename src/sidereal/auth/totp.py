"""RFC 6238 TOTP (SHA-1, 30 s, 6 digits), stdlib only: the optional second factor (plan §11.2).

Implemented here instead of adding ``pyotp``: the algorithm is a few lines of ``hmac``.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
from urllib.parse import quote

STEP_S = 30
DIGITS = 6
WINDOW = 1  # accept the previous and next step too (clock skew)


def new_secret() -> str:
    """160 random bits, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, unix_time: float) -> str:
    counter = int(unix_time // STEP_S)
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), "sha1").digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def matching_step(secret: str, code: str | None, unix_time: float) -> int | None:
    """The time step (counter) ``code`` is valid for within the window, or None. Every step is
    compared (constant time); the caller rejects a step it has already accepted (no replay,
    RFC 6238 §5.2)."""
    if code is None:
        return None
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    found = None
    for delta in range(-WINDOW, WINDOW + 1):
        t = unix_time + delta * STEP_S
        if hmac.compare_digest(code_at(secret, t).encode(), code.encode()):
            found = int(t // STEP_S)
    return found


def verify(secret: str, code: str | None, unix_time: float) -> bool:
    """Constant-time check of ``code`` against the steps around ``unix_time`` (no replay check:
    enrolment only; logins use ``matching_step``)."""
    return matching_step(secret, code, unix_time) is not None


def provisioning_uri(secret: str, username: str, issuer: str = "Sidereal") -> str:
    label = quote(f"{issuer}:{username}", safe=":")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"

"""Cardinal rule 9: never serve on a non-loopback address without auth and a user (plan §11.2)."""

from __future__ import annotations

import ipaddress

from sidereal.config import Settings
from sidereal.db.users_repo import count_active_users_at


class UnsafeBindError(Exception):
    """The configured bind address is not allowed with the current auth settings."""


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False  # a hostname: can't know what it resolves to, treat as exposed


def check_bind(host: str, settings: Settings, user_count: int) -> None:
    """Raise UnsafeBindError if serving on ``host`` would expose the app without auth."""
    if is_loopback(host):
        return
    if settings.auth.mode != "on":
        raise UnsafeBindError(
            f"refusing to bind {host}: not loopback and auth.mode is off (plan §11, rule 9)"
        )
    if user_count < 1:
        raise UnsafeBindError(
            f"refusing to bind {host}: auth is on but no user exists (sidereal user add)"
        )


def count_users(settings: Settings) -> int:
    """Active users in the configured DB, read-only; 0 if the DB or the table doesn't exist."""
    return count_active_users_at(settings.db_path)

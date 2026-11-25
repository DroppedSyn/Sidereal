"""Cardinal rule 9: never serve on a non-loopback address without auth and a user (plan §11.2).

M30 widens "non-loopback": a reverse proxy on the same host (``trusted_proxies``) or a
non-loopback ``allowed_hosts`` name exposes a loopback bind just the same."""

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


def is_loopback_name(name: str) -> bool:
    """An ``allowed_hosts`` entry that only a local client can send: loopback IPs, ``localhost``
    and ``*.localhost`` (RFC 6761). Anything else (a LAN name, an IP, ``*``) means the app is
    meant to be reached from elsewhere, e.g. through a reverse proxy on this host."""
    name = name.strip().lower().rstrip(".")
    return is_loopback(name) or name.endswith(".localhost")


def exposure(host: str, settings: Settings) -> list[str]:
    """Why serving on ``host`` with these settings reaches beyond this machine (empty: it doesn't).
    A loopback bind behind Caddy on the same host is exposed too: the proxy is the clue."""
    web = settings.web
    reasons = []
    if not is_loopback(host):
        reasons.append(f"bind {host} is not loopback")
    if web.trusted_proxies:
        reasons.append("web.trusted_proxies is set (served through a proxy)")
    names = [h for h in web.allowed_hosts if not is_loopback_name(h)]
    if names:
        reasons.append(f"web.allowed_hosts has non-loopback names ({', '.join(names)})")
    return reasons


def check_bind(host: str, settings: Settings, user_count: int) -> None:
    """Raise UnsafeBindError if serving on ``host`` would expose the app without auth: a
    non-loopback bind, ``trusted_proxies`` or a non-loopback ``allowed_hosts`` name each need
    ``auth.mode = "on"`` and at least one active user (rule 9, extended in M30)."""
    reasons = exposure(host, settings)
    if not reasons:
        return
    why = "; ".join(reasons)
    if settings.auth.mode != "on":
        raise UnsafeBindError(
            f"refusing to bind {host}: {why}, and auth.mode is off (plan §11, rule 9)"
        )
    if user_count < 1:
        raise UnsafeBindError(
            f"refusing to bind {host}: {why}, but auth is on and no user exists "
            "(sidereal user add NAME)"
        )


def count_users(settings: Settings) -> int:
    """Active users in the configured DB, read-only; 0 if the DB or the table doesn't exist."""
    return count_active_users_at(settings.db_path)

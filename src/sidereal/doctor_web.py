"""``sidereal doctor`` web exposure checks (plan §11, M30). Read-only, like the rest of doctor.

- ``web exposure``: the same rule ``serve`` enforces (``api.bind.check_bind``): a non-loopback
  bind, ``trusted_proxies`` or a non-loopback ``allowed_hosts`` name needs ``auth.mode = "on"``
  and at least one active user, else ❌.
- ``https``: the session cookie gets ``Secure`` only from ``web.https`` (kept explicit, plan
  §11.2); ⚠ when bound beyond loopback or proxied without it, and ⚠ when it is on but nothing in
  front terminates TLS (a direct non-loopback bind: browsers would drop the cookie).
- ``trusted proxies``: ⚠ for a network wider than a /24 (v4) or /64 (v6): every address in it
  may set the client IP the login rate limit counts.
- ``origins``: behind a proxy, each non-loopback ``allowed_hosts`` name needs its
  ``https://name`` in ``allowed_origins`` (the write guard compares the port), else ⚠.

The bind host is read from the installed ``sidereal-web.service`` (``--host``), because the unit
passes it explicitly and overrides ``web.host``; without the unit, ``web.host``.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from sidereal import paths
from sidereal.api.bind import exposure, is_loopback, is_loopback_name
from sidereal.api.security import _origin_of
from sidereal.config import Settings, proxy_networks
from sidereal.db.users_repo import count_active_users_at
from sidereal.doctor import FAIL, OK, WARN, Check

WEB_UNIT = "sidereal-web.service"
WIDE_PREFIX = {4: 24, 6: 64}


def unit_host(unit_file: Path) -> str | None:
    """The ``--host`` value on the unit's ``ExecStart=`` line, or None."""
    try:
        lines = unit_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        key, _, value = line.strip().partition("=")
        if key.strip() != "ExecStart":
            continue
        try:
            argv = shlex.split(value)
        except ValueError:
            return None
        for i, arg in enumerate(argv):
            if arg == "--host" and i + 1 < len(argv):
                return argv[i + 1]
            if arg.startswith("--host="):
                return arg.split("=", 1)[1]
    return None


def bind_host(settings: Settings, unit_dir: Path | None = None) -> tuple[str, str]:
    """(host, where it came from)."""
    unit = (unit_dir or paths.systemd_user_dir()) / WEB_UNIT
    host = unit_host(unit)
    if host is not None:
        return host, WEB_UNIT
    return settings.web.host, "web.host"


def check_exposure(settings: Settings, host: str, users: int) -> Check:
    reasons = exposure(host, settings)
    if not reasons:
        return Check(OK, "web exposure", f"loopback only ({host}); auth {settings.auth.mode}")
    why = "; ".join(reasons)
    if settings.auth.mode != "on":
        return Check(FAIL, "web exposure",
                     f"{why}, but auth.mode is off (set [auth] mode = \"on\"; serve refuses)")
    if users < 1:
        return Check(FAIL, "web exposure",
                     f"{why}, but no active user (sidereal user add NAME; serve refuses)")
    return Check(OK, "web exposure", f"{why}; auth on, {users} active user(s)")


def check_https(settings: Settings, host: str) -> Check:
    bound = not is_loopback(host)
    proxied = bool(settings.web.trusted_proxies)
    if settings.web.https:
        if bound and not proxied:
            return Check(WARN, "https",
                         f"web.https is on but {host} serves plain HTTP with no trusted proxy "
                         "in front: browsers won't send the Secure cookie back")
        return Check(OK, "https", "on (session cookie Secure)")
    if bound or proxied:
        how = f"bound on {host}" if bound else "behind a proxy"
        return Check(WARN, "https",
                     f"off while {how}: the session cookie has no Secure flag (put Caddy with "
                     "TLS in front and set web.https = true)")
    return Check(OK, "https", "off (loopback only)")


def check_proxies(settings: Settings) -> Check:
    nets = proxy_networks(settings.web.trusted_proxies)
    if not nets:
        return Check(OK, "trusted proxies", "none (client IP = peer address)")
    wide = [str(n) for n in nets if n.prefixlen < WIDE_PREFIX[n.version]]
    listed = ", ".join(str(n) for n in nets)
    if wide:
        return Check(WARN, "trusted proxies",
                     f"{', '.join(wide)} is wide: any address in it can choose the client IP "
                     "the login rate limit counts; list only the proxy")
    return Check(OK, "trusted proxies", listed)


def check_origins(settings: Settings) -> Check | None:
    """Behind a proxy the browser's Origin is ``https://<name>`` (port 443), not the app's port:
    each non-loopback ``allowed_hosts`` name needs an ``allowed_origins`` entry or every write,
    login included, gets 403 ``origin not allowed``."""
    if not settings.web.trusted_proxies:
        return None
    hosts = {o[1] for o in (_origin_of(x) for x in settings.web.allowed_origins) if o}
    missing = [h for h in settings.web.allowed_hosts
               if not is_loopback_name(h) and "*" not in h and h.lower() not in hosts]
    if missing:
        return Check(WARN, "origins",
                     f"no web.allowed_origins entry for {', '.join(missing)}: writes and login "
                     f"through the proxy get 403 (add \"https://{missing[0]}\")")
    return Check(OK, "origins", ", ".join(settings.web.allowed_origins) or "none needed")


def check_web_exposure(settings: Settings, *, unit_dir: Path | None = None) -> list[Check]:
    host, source = bind_host(settings, unit_dir)
    users = count_active_users_at(settings.db_path)
    checks = [
        Check(OK, "web bind", f"{host} (from {source})"),
        check_exposure(settings, host, users),
        check_https(settings, host),
        check_proxies(settings),
    ]
    origins = check_origins(settings)
    if origins is not None:
        checks.append(origins)
    return checks

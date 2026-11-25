"""deploy/*.service|timer content (M22, plan §12.1, §12.4)."""

from __future__ import annotations

import re
from datetime import time

import pytest

from sidereal import doctor_systemd, paths
from sidereal.config import Settings

DEPLOY = paths.project_root() / "deploy"
BIN = "%h/Projects/Sidereal/.venv/bin/sidereal"
HARDENING = {
    "NoNewPrivileges": "yes",
    "PrivateTmp": "yes",
    "ProtectSystem": "strict",
    "ProtectHome": "read-only",
    "ReadWritePaths": "%h/.local/share/sidereal",
}


def unit(name: str) -> dict[str, dict[str, list[str]]]:
    """``{section: {key: [values in order]}}`` (systemd keys may repeat)."""
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for raw in (DEPLOY / name).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            current = sections.setdefault(line.strip("[]"), {})
            continue
        key, _, value = line.partition("=")
        assert current is not None, f"{name}: {line!r} outside a section"
        current.setdefault(key, []).append(value)
    return sections


def one(u, section, key):
    values = u[section][key]
    assert len(values) == 1, (section, key, values)
    return values[0]


def calendar_times(expr: str) -> tuple[str, list[time]]:
    """``*-*-* 00,04:00:00 Europe/London`` → (zone, [00:00, 04:00])."""
    m = re.fullmatch(r"\*-\*-\* ([\d,]+):([\d,]+):00 (\S+)", expr)
    assert m, expr
    hours, minutes, zone = m.groups()
    return zone, [time(int(h), int(mi)) for h in hours.split(",") for mi in minutes.split(",")]


def test_run_timer_six_times_london_persistent():
    t = unit("sidereal-run.timer")
    zone, times = calendar_times(one(t, "Timer", "OnCalendar"))
    assert zone == "Europe/London"
    assert times == [time(h) for h in (0, 4, 8, 12, 16, 20)]
    assert tuple(times) == doctor_systemd.RUN_TIMES and zone == doctor_systemd.TIMER_TZ
    assert one(t, "Timer", "Persistent") == "true"
    assert one(t, "Timer", "RandomizedDelaySec") == "300"
    assert one(t, "Timer", "AccuracySec") == "1min"
    assert one(t, "Timer", "Unit") == "sidereal-run.service"
    assert one(t, "Install", "WantedBy") == "timers.target"


def test_backup_timer_0330_london_persistent():
    t = unit("sidereal-backup.timer")
    zone, times = calendar_times(one(t, "Timer", "OnCalendar"))
    assert (zone, times) == ("Europe/London", [time(3, 30)])
    assert tuple(times) == doctor_systemd.BACKUP_TIMES
    assert one(t, "Timer", "Persistent") == "true"
    assert one(t, "Timer", "Unit") == "sidereal-backup.service"
    assert one(t, "Install", "WantedBy") == "timers.target"


def test_web_service_binds_loopback_8470():
    s = unit("sidereal-web.service")
    assert one(s, "Service", "ExecStart") == f"{BIN} serve --host 127.0.0.1 --port 8470"
    assert one(s, "Service", "Restart") == "on-failure"
    assert one(s, "Service", "EnvironmentFile") == "-%h/.config/sidereal/env"
    assert one(s, "Install", "WantedBy") == "default.target"


def test_run_service_oneshot_timer_trigger():
    s = unit("sidereal-run.service")
    assert one(s, "Service", "Type") == "oneshot"
    assert one(s, "Service", "ExecStart") == f"{BIN} run --trigger timer"
    assert one(s, "Service", "Nice") == "10"
    assert one(s, "Service", "EnvironmentFile") == "-%h/.config/sidereal/env"
    assert "Install" not in s  # started by the timer (and POST /api/runs), never enabled


def test_run_timeout_covers_gate_wait_plus_run_budget():
    timeout = one(unit("sidereal-run.service"), "Service", "TimeoutStartSec")
    m = re.fullmatch(r"(\d+)h", timeout)
    assert m, timeout
    s = Settings()
    assert int(m.group(1)) * 60 > s.gate.max_wait_minutes + s.budget.max_run_minutes


def test_backup_service_oneshot():
    s = unit("sidereal-backup.service")
    assert one(s, "Service", "Type") == "oneshot"
    assert one(s, "Service", "ExecStart") == f"{BIN} backup"
    assert one(s, "Service", "RestrictAddressFamilies") == "AF_UNIX"  # no network needed
    assert "Install" not in s


@pytest.mark.parametrize("name", ["sidereal-web.service", "sidereal-run.service",
                                  "sidereal-backup.service"])
def test_services_hardened(name):
    s = unit(name)
    for key, value in HARDENING.items():
        assert one(s, "Service", key) == value, key
    if name != "sidereal-backup.service":
        assert one(s, "Service", "RestrictAddressFamilies") == "AF_INET AF_INET6 AF_UNIX"


def test_read_write_path_is_the_default_state_dir():
    home = paths.default_state_dir({"HOME": "/h"})
    assert str(home).replace("/h", "%h", 1) == HARDENING["ReadWritePaths"]


def test_doctor_knows_every_deployed_unit():
    deployed = {p.name for p in DEPLOY.iterdir() if p.suffix in (".service", ".timer")}
    assert deployed == set(doctor_systemd.UNITS)

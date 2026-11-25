"""``sidereal doctor`` systemd checks (plan §12.5), by reading files only: rule 12 keeps
``subprocess`` (``systemctl``/``loginctl``) out of everything but ``api/routes_runs.py``.

- installed: the unit files in ``~/.config/systemd/user`` (``install.sh`` copies them);
- enabled: the ``<target>.wants/<unit>`` link ``systemctl --user enable`` creates;
- web service running: a ``sidereal serve`` process in ``/proc``;
- timers: last trigger = mtime of the ``Persistent=true`` stamp file, next elapse computed from
  the schedule below (it mirrors ``deploy/*.timer``; ``tests/test_deploy_units.py`` keeps the
  two in step);
- linger: ``/var/lib/systemd/linger/<user>`` exists.
"""

from __future__ import annotations

import os
import pwd
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sidereal import paths
from sidereal.doctor import FAIL, OK, WARN, Check

WEB = "sidereal-web.service"
RUN_TIMER = "sidereal-run.timer"
BACKUP_TIMER = "sidereal-backup.timer"
UNITS = (WEB, "sidereal-run.service", "sidereal-run-manual.service", RUN_TIMER,
         "sidereal-backup.service", BACKUP_TIMER)
RUN_TIMES = (time(0), time(4), time(8), time(12), time(16), time(20))  # Europe/London
BACKUP_TIMES = (time(3, 30),)
TIMER_TZ = "Europe/London"
LINGER_DIR = Path("/var/lib/systemd/linger")
PROC = Path("/proc")


def install_hint() -> str:
    return f"run {paths.project_root() / 'install.sh'}"


def next_elapse(now: datetime, times: tuple[time, ...], tz: str = TIMER_TZ) -> datetime:
    """The first scheduled wall-clock time in ``tz`` strictly after ``now``."""
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    for days in range(2):
        day = local.date() + timedelta(days=days)
        for t in sorted(times):
            cand = datetime.combine(day, t, tzinfo=zone)
            if cand > local:
                return cand
    raise ValueError("no schedule times")  # unreachable with a non-empty ``times``


def _enabled(unit_dir: Path, target: str, unit: str) -> bool:
    link = unit_dir / f"{target}.wants" / unit
    return link.is_symlink() or link.exists()


def serve_pids(proc: Path = PROC) -> list[int]:
    """PIDs whose command line runs ``…/sidereal serve`` (not this process)."""
    found = []
    for entry in proc.glob("[0-9]*"):
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        names = [os.path.basename(a.decode(errors="replace")) for a in argv]
        if "sidereal" in names and "serve" in names[names.index("sidereal") + 1:] \
                and int(entry.name) != os.getpid():
            found.append(int(entry.name))
    return sorted(found)


def check_web(unit_dir: Path, proc: Path) -> Check:
    if not (unit_dir / WEB).is_file():
        return Check(WARN, "web service", f"{WEB} not installed ({install_hint()})")
    enabled = _enabled(unit_dir, "default.target", WEB)
    pids = serve_pids(proc)
    if pids:
        if enabled:
            return Check(OK, "web service", f"enabled, running (pid {pids[0]})")
        return Check(WARN, "web service", f"running (pid {pids[0]}) but not enabled")
    if enabled:
        return Check(FAIL, "web service",
                     f"enabled but not running (journalctl --user -u {WEB})")
    return Check(WARN, "web service", f"not enabled (systemctl --user enable --now {WEB})")


def check_timer(name: str, unit: str, times: tuple[time, ...], *, unit_dir: Path,
                stamps: Path, now: datetime) -> Check:
    if not (unit_dir / unit).is_file():
        return Check(WARN, name, f"{unit} not installed ({install_hint()})")
    if not _enabled(unit_dir, "timers.target", unit):
        return Check(WARN, name, f"not enabled (systemctl --user enable --now {unit})")
    stamp = stamps / f"stamp-{unit}"
    if stamp.exists():
        age = now.timestamp() - stamp.stat().st_mtime
        last = f"last triggered {age / 3600:.1f} h ago"
    else:
        last = "not triggered yet"
    nxt = next_elapse(now, times)
    return Check(OK, name, f"enabled, {last}, next {nxt:%a %H:%M} {nxt.tzname()}")


def check_linger(linger_dir: Path, user: str) -> Check:
    if (linger_dir / user).exists():
        return Check(OK, "linger", f"on for {user}")
    return Check(WARN, "linger", f"off: timers stop at logout (sudo loginctl enable-linger {user})")


def check_systemd(now: datetime) -> list[Check]:
    unit_dir = paths.systemd_user_dir()
    stamps = paths.systemd_timer_stamps_dir()
    user = pwd.getpwuid(os.getuid()).pw_name
    return [
        check_web(unit_dir, PROC),
        check_timer("run timer", RUN_TIMER, RUN_TIMES, unit_dir=unit_dir, stamps=stamps,
                    now=now),
        check_timer("backup timer", BACKUP_TIMER, BACKUP_TIMES, unit_dir=unit_dir,
                    stamps=stamps, now=now),
        check_linger(LINGER_DIR, user),
    ]

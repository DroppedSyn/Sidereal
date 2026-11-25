"""doctor_systemd.py (M22): systemd state from files only (rule 12: no subprocess)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, time

import pytest

from sidereal import doctor_systemd as ds
from sidereal import paths
from sidereal.doctor import FAIL, OK, WARN

NOW = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)


@pytest.fixture
def unit_dir():
    d = paths.systemd_user_dir()
    d.mkdir(parents=True)
    return d


def install(unit_dir, *names):
    for n in names:
        (unit_dir / n).write_text("[Unit]\n")


def enable(unit_dir, target, name):
    wants = unit_dir / f"{target}.wants"
    wants.mkdir(exist_ok=True)
    (wants / name).symlink_to(unit_dir / name)


@pytest.fixture
def proc(tmp_path):
    d = tmp_path / "proc"
    d.mkdir()
    return d


def fake_proc(proc, pid, *argv):
    (proc / str(pid)).mkdir()
    (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


@pytest.mark.parametrize("now,expect", [
    (datetime(2026, 11, 25, 10, 0, tzinfo=UTC), datetime(2026, 11, 25, 12, 0, tzinfo=UTC)),
    (datetime(2026, 11, 25, 12, 0, tzinfo=UTC), datetime(2026, 11, 25, 16, 0, tzinfo=UTC)),
    (datetime(2026, 11, 25, 21, 0, tzinfo=UTC), datetime(2026, 11, 26, 0, 0, tzinfo=UTC)),
    # summer time: 08:00 BST is 07:00 UTC
    (datetime(2026, 7, 1, 5, 0, tzinfo=UTC), datetime(2026, 7, 1, 7, 0, tzinfo=UTC)),
])
def test_next_elapse_in_london(now, expect):
    assert ds.next_elapse(now, ds.RUN_TIMES) == expect


def test_next_backup_elapse():
    nxt = ds.next_elapse(NOW, ds.BACKUP_TIMES)
    assert nxt == datetime(2026, 11, 26, 3, 30, tzinfo=UTC)
    assert ds.next_elapse(datetime(2026, 11, 25, 3, 0, tzinfo=UTC), (time(3, 30),)).day == 25


def test_serve_pids(proc):
    fake_proc(proc, 10, "/x/.venv/bin/python3", "/x/.venv/bin/sidereal", "serve", "--port", "1")
    fake_proc(proc, 11, "/x/.venv/bin/python3", "/x/.venv/bin/sidereal", "run")
    fake_proc(proc, 12, "vim", "serve")
    fake_proc(proc, 13, "serve", "sidereal")
    fake_proc(proc, os.getpid(), "sidereal", "serve")
    (proc / "self").mkdir()
    (proc / "99").mkdir()  # no cmdline (process gone): skipped
    assert ds.serve_pids(proc) == [10]


def test_web_not_installed(unit_dir, proc):
    c = ds.check_web(unit_dir, proc)
    assert c.level == WARN and "not installed" in c.detail


def test_web_states(unit_dir, proc):
    install(unit_dir, ds.WEB)
    assert ds.check_web(unit_dir, proc).detail.startswith("not enabled")
    enable(unit_dir, "default.target", ds.WEB)
    c = ds.check_web(unit_dir, proc)
    assert c.level == FAIL and "not running" in c.detail
    fake_proc(proc, 42, "python3", "/p/.venv/bin/sidereal", "serve")
    c = ds.check_web(unit_dir, proc)
    assert c.level == OK and c.detail == "enabled, running (pid 42)"


def test_web_running_but_not_enabled(unit_dir, proc):
    install(unit_dir, ds.WEB)
    fake_proc(proc, 42, "sidereal", "serve")
    assert ds.check_web(unit_dir, proc).level == WARN


def test_timer_states(unit_dir, tmp_path):
    stamps = tmp_path / "stamps"
    stamps.mkdir()
    kw = dict(unit_dir=unit_dir, stamps=stamps, now=NOW)
    c = ds.check_timer("run timer", ds.RUN_TIMER, ds.RUN_TIMES, **kw)
    assert c.level == WARN and "not installed" in c.detail
    install(unit_dir, ds.RUN_TIMER)
    c = ds.check_timer("run timer", ds.RUN_TIMER, ds.RUN_TIMES, **kw)
    assert c.level == WARN and "not enabled" in c.detail
    enable(unit_dir, "timers.target", ds.RUN_TIMER)
    c = ds.check_timer("run timer", ds.RUN_TIMER, ds.RUN_TIMES, **kw)
    assert c.level == OK and c.detail == "enabled, not triggered yet, next Wed 12:00 GMT"
    stamp = stamps / f"stamp-{ds.RUN_TIMER}"
    stamp.touch()
    os.utime(stamp, (NOW.timestamp() - 7200, NOW.timestamp() - 7200))
    c = ds.check_timer("run timer", ds.RUN_TIMER, ds.RUN_TIMES, **kw)
    assert c.detail == "enabled, last triggered 2.0 h ago, next Wed 12:00 GMT"


def test_linger(tmp_path):
    c = ds.check_linger(tmp_path, "al")
    assert c.level == WARN and "sudo loginctl enable-linger al" in c.detail
    (tmp_path / "al").touch()
    assert ds.check_linger(tmp_path, "al") == ds.Check(OK, "linger", "on for al")


def test_check_systemd_all_ok(unit_dir, proc, tmp_path, monkeypatch):
    import pwd

    user = pwd.getpwuid(os.getuid()).pw_name
    linger = tmp_path / "linger"
    linger.mkdir()
    (linger / user).touch()
    monkeypatch.setattr(ds, "LINGER_DIR", linger)
    monkeypatch.setattr(ds, "PROC", proc)
    install(unit_dir, *ds.UNITS)
    enable(unit_dir, "default.target", ds.WEB)
    enable(unit_dir, "timers.target", ds.RUN_TIMER)
    enable(unit_dir, "timers.target", ds.BACKUP_TIMER)
    fake_proc(proc, 7, "sidereal", "serve")
    checks = ds.check_systemd(NOW)
    assert [c.name for c in checks] == ["web service", "run timer", "backup timer", "linger"]
    assert all(c.level == OK for c in checks), checks
    assert checks[2].detail.endswith("next Thu 03:30 GMT")

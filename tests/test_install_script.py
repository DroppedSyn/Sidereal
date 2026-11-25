"""install.sh (M22, now in the repo root) against fake ``systemctl`` / ``loginctl`` on PATH:
idempotent, never sudo, unit paths pointed at this checkout, linger hint only when off."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from sidereal import doctor_systemd, paths

SCRIPT = paths.project_root() / "install.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


@pytest.fixture
def fakebin(tmp_path):
    d = tmp_path / "fakebin"
    d.mkdir()
    log = tmp_path / "calls.log"
    for name in ("systemctl", "loginctl", "sudo"):
        script = d / name
        script.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n'
                          'if [ "$1" = show-user ]; then echo "${FAKE_LINGER:-no}"; fi\n')
        script.chmod(0o755)
    return d, log


def run(fakebin, linger="no", *args):
    d, _ = fakebin
    env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "FAKE_LINGER": linger}
    argv = ["bash", str(SCRIPT), *(args or ("--no-build", "--no-doctor"))]
    return subprocess.run(argv, env=env, capture_output=True, text=True,
                          timeout=120, check=False)


def test_installs_units_and_enables_them(settings, fakebin):
    r = run(fakebin)
    assert r.returncode == 0, r.stderr
    unit_dir = paths.systemd_user_dir()
    repo = str(paths.project_root())
    for name in doctor_systemd.UNITS:
        text = (unit_dir / name).read_text()
        assert "%h/Projects/Sidereal" not in text
        if name.endswith(".service"):
            assert f"ExecStart={repo}/.venv/bin/sidereal " in text
    calls = fakebin[1].read_text().splitlines()
    assert "systemctl --user daemon-reload" in calls
    assert ("systemctl --user enable --now sidereal-web.service sidereal-run.timer "
            "sidereal-backup.timer") in calls
    assert not any(c.startswith("sudo") for c in calls)
    assert settings.db_path.exists()  # ran sidereal init (ReadWritePaths needs the state dir)
    assert "sudo loginctl enable-linger" in r.stdout


def test_idempotent(settings, fakebin):
    assert run(fakebin).returncode == 0
    unit_dir = paths.systemd_user_dir()
    first = {p.name: p.read_text() for p in unit_dir.iterdir()}
    r = run(fakebin)
    assert r.returncode == 0, r.stderr
    assert {p.name: p.read_text() for p in unit_dir.iterdir()} == first
    assert sorted(first) == sorted(doctor_systemd.UNITS)  # no temp files left behind


def test_no_linger_hint_when_on(settings, fakebin):
    r = run(fakebin, linger="yes")
    assert r.returncode == 0, r.stderr
    assert "enable-linger" not in r.stdout


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)

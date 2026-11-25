"""deploy/install.sh puts `sidereal` on PATH: a symlink ~/.local/bin/sidereal → the venv's
entry point; idempotent; a non-symlink file there is never replaced."""

from __future__ import annotations

import os
from pathlib import Path

from sidereal import paths
from tests.test_install_script import fakebin, run  # noqa: F401  (fixture re-used)

VENV_BIN = paths.project_root() / ".venv" / "bin" / "sidereal"


def link_path() -> Path:
    return Path(os.environ["HOME"]) / ".local" / "bin" / "sidereal"


def test_creates_symlink_to_venv(settings, fakebin):  # noqa: F811
    r = run(fakebin)
    assert r.returncode == 0, r.stderr
    link = link_path()
    assert link.is_symlink()
    assert os.readlink(link) == str(VENV_BIN)
    assert "Check with: sidereal doctor" in r.stdout


def test_rerun_keeps_symlink(settings, fakebin):  # noqa: F811
    assert run(fakebin).returncode == 0
    r = run(fakebin)
    assert r.returncode == 0, r.stderr
    assert os.readlink(link_path()) == str(VENV_BIN)


def test_replaces_stale_symlink(settings, fakebin):  # noqa: F811
    link = link_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to("/nonexistent/sidereal")
    assert run(fakebin).returncode == 0
    assert os.readlink(link) == str(VENV_BIN)


def test_leaves_regular_file_alone(settings, fakebin):  # noqa: F811
    link = link_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("mine\n")
    r = run(fakebin)
    assert r.returncode == 0, r.stderr
    assert not link.is_symlink()
    assert link.read_text() == "mine\n"
    assert "not a symlink" in r.stderr

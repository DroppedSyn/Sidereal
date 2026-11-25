"""install.sh options: --help, unknown options, --uninstall (removes units and the PATH link,
keeps data), and the re-install restart of the web service."""

from __future__ import annotations

import os
from pathlib import Path

from sidereal import doctor_systemd, paths
from tests.test_install_script import SCRIPT, fakebin, run  # noqa: F401  (fixture re-used)

VENV_BIN = paths.project_root() / ".venv" / "bin" / "sidereal"


def link_path() -> Path:
    return Path(os.environ["HOME"]) / ".local" / "bin" / "sidereal"


def test_script_lives_in_repo_root():
    assert SCRIPT == paths.project_root() / "install.sh"
    assert not (paths.project_root() / "deploy" / "install.sh").exists()


def test_help(fakebin):  # noqa: F811
    r = run(fakebin, "no", "--help")
    assert r.returncode == 0
    assert "./install.sh --uninstall" in r.stdout
    assert fakebin[1].exists() is False  # nothing called


def test_unknown_option(fakebin):  # noqa: F811
    r = run(fakebin, "no", "--frobnicate")
    assert r.returncode == 2
    assert "unknown option" in r.stderr


def test_reinstall_restarts_web(settings, fakebin):  # noqa: F811
    assert run(fakebin).returncode == 0
    calls = fakebin[1].read_text().splitlines()
    assert "systemctl --user try-restart sidereal-web.service" in calls


def test_uninstall_removes_units_and_link_keeps_data(settings, fakebin):  # noqa: F811
    assert run(fakebin).returncode == 0
    unit_dir = paths.systemd_user_dir()
    assert link_path().is_symlink()
    r = run(fakebin, "no", "--uninstall")
    assert r.returncode == 0, r.stderr
    for name in doctor_systemd.UNITS:
        assert not (unit_dir / name).exists()
    assert not link_path().exists()
    assert settings.db_path.exists()  # data untouched
    calls = fakebin[1].read_text().splitlines()
    assert ("systemctl --user disable --now sidereal-web.service sidereal-run.timer "
            "sidereal-backup.timer") in calls


def test_uninstall_keeps_foreign_link(settings, fakebin):  # noqa: F811
    link = link_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to("/somewhere/else/sidereal")
    assert run(fakebin, "no", "--uninstall").returncode == 0
    assert link.is_symlink()


def test_doctor_hint_names_root_script():
    assert doctor_systemd.install_hint() == f"run {paths.project_root() / 'install.sh'}"

"""deploy/sidereal-run-manual.service (M15b): POST /api/runs starts it; it equals the timer's
run unit except for ``--trigger manual`` and its description."""

from __future__ import annotations

from sidereal import doctor_systemd, paths
from sidereal.api import routes_runs

DEPLOY = paths.project_root() / "deploy"


def _body(name: str) -> list[str]:
    return [line for line in (DEPLOY / name).read_text().splitlines()
            if line and not line.startswith("#")]


def test_manual_unit_matches_run_unit_but_trigger():
    manual = _body("sidereal-run-manual.service")
    timer = _body("sidereal-run.service")
    assert "ExecStart=%h/Projects/Sidereal/.venv/bin/sidereal run --trigger manual" in manual
    swapped = [line.replace("--trigger timer", "--trigger manual")
               .replace("Description=Sidereal pipeline run",
                        "Description=Sidereal pipeline run (manual)") for line in timer]
    assert manual == swapped
    assert "[Install]" not in manual  # started on demand only


def test_route_names_the_deployed_unit():
    assert (DEPLOY / routes_runs.RUN_UNIT).is_file()
    assert routes_runs.RUN_UNIT in doctor_systemd.UNITS
    assert routes_runs.RUN_UNIT in (DEPLOY / "install.sh").read_text()

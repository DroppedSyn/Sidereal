"""``sidereal doctor`` checks (plan §12.5). Read-only: never creates the state dir, the DB or
the lock file, never writes a row. Each check is one ``Check``; ``fail`` makes doctor exit 1.

The systemd checks (web service, timers, linger) live in ``doctor_systemd`` and read files
only: subprocess is allowed only in ``api/routes_runs.py`` (rule 12).
"""

from __future__ import annotations

import shutil
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta

from sidereal import paths
from sidereal.config import Settings
from sidereal.db import Connection, runs_repo, sources_repo
from sidereal.db.connect import connect_readonly, ping
from sidereal.db.migrations import migration_files, read_version
from sidereal.llm.ollama import LLMError, OllamaClient
from sidereal.pipeline import lock
from sidereal.timeutil import parse_iso_z, utc_now

OK, WARN, FAIL = "ok", "warn", "fail"
SYMBOL = {OK: "✅", WARN: "⚠", FAIL: "❌"}
LAST_RUN_MAX_AGE = timedelta(hours=5)
DISK_WARN_BYTES = 1_000_000_000
DISK_FAIL_BYTES = 100_000_000


@dataclass(frozen=True)
class Check:
    level: str  # ok | warn | fail
    name: str
    detail: str

    def line(self) -> str:
        return f"{SYMBOL[self.level]} {self.name}: {self.detail}"


def check_config() -> list[Check]:
    """The settings loaded (an invalid file already exited 2 in the CLI); the env file holding
    secrets (§12.3) must not be group/other accessible."""
    cfg = paths.config_file()
    where = str(cfg) if cfg.exists() else f"defaults (no file at {cfg})"
    checks = [Check(OK, "config", where)]
    env_file = paths.config_dir() / "env"
    if not env_file.exists():
        checks.append(Check(OK, "env file", f"none ({env_file})"))
    elif env_file.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        mode = oct(env_file.stat().st_mode & 0o777)
        checks.append(Check(FAIL, "env file", f"{env_file} is {mode}: chmod 600 it"))
    else:
        checks.append(Check(OK, "env file", f"{env_file} (private)"))
    return checks


def check_state_dir(settings: Settings) -> list[Check]:
    state = settings.state_dir
    if not state.is_dir():
        return [Check(FAIL, "state dir", f"{state} missing (run: sidereal init)")]
    free = shutil.disk_usage(state).free
    level = FAIL if free < DISK_FAIL_BYTES else WARN if free < DISK_WARN_BYTES else OK
    return [Check(level, "state dir", f"{state} ({free / 1e9:.1f} GB free)")]


def check_lock(settings: Settings) -> list[Check]:
    path = lock.lock_path(settings.state_dir)
    if not lock.is_held(path):
        return [Check(OK, "run lock", "free")]
    pid = lock.held_by(path)
    return [Check(OK, "run lock", f"held: a run is in progress (pid {pid or '?'})")]


def _last_run(conn: Connection, now: datetime) -> Check:
    runs = [r for r in runs_repo.list_runs(conn, limit=50) if r.status != "skipped"]
    if not runs:
        return Check(WARN, "last run", "no runs yet")
    r = runs[0]
    if r.status == "running":
        return Check(OK, "last run", f"run {r.id} in progress since {r.started_at}")
    age = now - parse_iso_z(r.finished_at or r.started_at)
    hours = age.total_seconds() / 3600
    detail = f"run {r.id} {r.status}, {hours:.1f} h ago"
    if r.status == "failed":
        return Check(FAIL, "last run", f"{detail}: {r.error or 'no error text'}")
    if age >= LAST_RUN_MAX_AGE:
        return Check(WARN, "last run", f"{detail} (older than 5 h: is the timer on?)")
    return Check(OK, "last run", detail)


def _sources(conn: Connection, now: datetime) -> list[Check]:
    rows = sources_repo.list_sources(conn, enabled_only=True)
    newest = sources_repo.last_item_times(conn)
    checks = []
    bad = 0
    for row in rows:
        h = sources_repo.health(row, now=now, last_new_item_at=newest.get(row.id))
        if h == "ok":
            continue
        bad += 1
        level = FAIL if h in ("broken", "failing") else WARN
        why = f": {row.last_error}" if h in ("broken", "failing") and row.last_error else ""
        checks.append(Check(level, f"source {row.key}", f"{h}{why}"))
    checks.insert(0, Check(OK if not bad else WARN, "sources",
                           f"{len(rows) - bad} of {len(rows)} enabled sources ok"))
    return checks


def check_db(settings: Settings, now: datetime) -> list[Check]:
    """Schema current, last run, source health; all over a read-only connection."""
    db = settings.db_path
    if not ping(db):
        what = "missing" if not db.exists() else "unreadable"
        return [Check(FAIL, "database", f"{db} {what} (run: sidereal init)")]
    conn = connect_readonly(db)
    try:
        have = read_version(conn)
        want = max((v for v, _ in migration_files()), default=0)
        if have < want:
            return [Check(FAIL, "database",
                          f"schema {have}, code expects {want} (run: sidereal init)")]
        checks = [Check(OK, "database", f"{db} (schema {have})")]
        checks.append(_last_run(conn, now))
        checks.extend(_sources(conn, now))
    finally:
        conn.close()
    return checks


async def check_ollama(settings: Settings, ollama: OllamaClient) -> list[Check]:
    """Reachable (``/api/tags``) and every configured model present."""
    m = settings.models
    found: list[Check] = []
    for model in dict.fromkeys((m.triage, m.assess, m.digest)):
        try:
            present = await ollama.has_model(model)
        except LLMError as exc:
            return [Check(FAIL, "ollama",
                          f"{settings.ollama.url} unreachable ({type(exc).__name__})")]
        found.append(Check(OK, f"model {model}", "present") if present else
                     Check(FAIL, f"model {model}", f"missing (ollama pull {model})"))
    return [Check(OK, "ollama", f"{settings.ollama.url} reachable"), *found]


async def run_checks(settings: Settings, ollama: OllamaClient, *,
                     now: datetime | None = None) -> list[Check]:
    at = now or utc_now()
    from sidereal.doctor_web import check_web_exposure  # imports Check from here

    checks = check_config() + check_web_exposure(settings) + check_state_dir(settings)
    if settings.state_dir.is_dir():
        checks += check_lock(settings)
    checks += check_db(settings, at)
    checks += await check_ollama(settings, ollama)
    from sidereal.doctor_systemd import check_systemd  # imports Check from here

    checks += check_systemd(at)
    return checks

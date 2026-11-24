"""``sidereal init`` and the start-up steps shared with ``run`` / ``serve``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sidereal import paths
from sidereal.config import Settings
from sidereal.db.connect import connect
from sidereal.db.migrations import apply_migrations
from sidereal.db.seed import seed_focus_areas, seed_sources
from sidereal.defaults import load_focus_areas, load_sources


@dataclass(frozen=True)
class InitReport:
    db_path: Path
    migrations_applied: list[int]
    sources_added: int
    focus_areas_added: int


def ensure_dirs(settings: Settings) -> None:
    settings.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (settings.state_dir / "backups").mkdir(exist_ok=True, mode=0o700)


def migrate(settings: Settings) -> list[int]:
    """Create the state dir and bring the schema up to date."""
    ensure_dirs(settings)
    conn = connect(settings.db_path)
    try:
        return apply_migrations(conn)
    finally:
        conn.close()


def init(settings: Settings, defaults_dir: Path | None = None) -> InitReport:
    """Dirs, DB, migrations, then seed sources and focus areas (adds missing keys only)."""
    defaults_dir = defaults_dir or paths.defaults_dir()
    sources = load_sources(defaults_dir / "sources.toml")
    focus = load_focus_areas(defaults_dir / "focus.toml")
    applied = migrate(settings)
    conn = connect(settings.db_path)
    try:
        added_sources = seed_sources(conn, sources)
        added_focus = seed_focus_areas(conn, focus)
    finally:
        conn.close()
    return InitReport(settings.db_path, applied, added_sources, added_focus)

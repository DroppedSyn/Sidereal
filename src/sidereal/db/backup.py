"""``sidereal backup`` (plan §12.4): SQLite online backup API into ``$STATE/backups``.

The copy is written to a ``.partial`` file, checked with ``PRAGMA quick_check`` and renamed into
place, so a crash never leaves a half-written ``sidereal-*.db`` that would count toward ``keep``.
Names are ``sidereal-YYYYMMDD-HHMM.db`` in UTC (sortable; two backups in one minute replace each
other). Only files matching that pattern are ever pruned.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sidereal.db.connect import connect

BACKUP_RE = re.compile(r"^sidereal-\d{8}-\d{4}\.db$")


class BackupError(Exception):
    """The database is missing or the copy failed its integrity check."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    size: int
    removed: tuple[Path, ...]


def backup_name(at: datetime) -> str:
    """``sidereal-YYYYMMDD-HHMM.db`` for an aware ``at`` (converted to UTC)."""
    if at.tzinfo is None:
        raise ValueError("backup time must be timezone-aware")
    return f"sidereal-{at.astimezone(UTC):%Y%m%d-%H%M}.db"


def list_backups(backups_dir: Path) -> list[Path]:
    """Backup files in ``backups_dir``, oldest first (the names sort chronologically)."""
    if not backups_dir.is_dir():
        return []
    return sorted(p for p in backups_dir.iterdir() if p.is_file() and BACKUP_RE.match(p.name))


def prune_backups(backups_dir: Path, *, keep: int) -> tuple[Path, ...]:
    """Delete all but the newest ``keep`` backups; returns the deleted paths."""
    if keep < 1:
        raise ValueError("keep must be >= 1")
    old = list_backups(backups_dir)[:-keep]
    for p in old:
        p.unlink()
    return tuple(old)


def _quick_check(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA quick_check").fetchone()[0])


def make_backup(db_path: Path, backups_dir: Path, *, at: datetime, keep: int) -> BackupResult:
    """Copy ``db_path`` (online, consistent while a run writes) and prune to ``keep``."""
    if keep < 1:
        raise ValueError("keep must be >= 1")
    if not db_path.is_file():
        raise BackupError(f"{db_path} missing (run: sidereal init)")
    backups_dir.mkdir(parents=True, exist_ok=True)
    final = backups_dir / backup_name(at)
    partial = final.with_name(final.name + ".partial")
    partial.unlink(missing_ok=True)
    src = connect(db_path)
    try:
        dest = sqlite3.connect(str(partial))
        try:
            src.backup(dest)
            check = _quick_check(dest)
        finally:
            dest.close()
    finally:
        src.close()
    if check != "ok":
        partial.unlink(missing_ok=True)
        raise BackupError(f"backup failed its integrity check: {check}")
    partial.chmod(0o600)
    os.replace(partial, final)
    removed = prune_backups(backups_dir, keep=keep)
    return BackupResult(path=final, size=final.stat().st_size, removed=removed)


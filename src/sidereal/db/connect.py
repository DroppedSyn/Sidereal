"""Open SQLite connections with the project's pragmas (plan §4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def connect(path: Path | str) -> sqlite3.Connection:
    """Open (creating if needed) the database at ``path``. Row factory is ``sqlite3.Row``."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def ping(path: Path | str) -> bool:
    """True if the database exists, opens read-only and answers a query. Never creates it."""
    if not Path(path).exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        try:
            conn.execute("SELECT count(*) FROM schema_version").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return True

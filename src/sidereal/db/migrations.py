"""Numbered schema migrations (``db/sql/NNNN_name.sql``), each applied in one transaction.

⚠ Pitfall (plan §4): ``executescript`` commits as it goes, so a failing statement would leave a
half-applied migration. Each file is split into complete statements (``sqlite3.complete_statement``
keeps trigger bodies whole) and run between an explicit BEGIN and COMMIT, with ROLLBACK on error.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SQL_DIR = Path(__file__).with_name("sql")
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(Exception):
    """A migration file failed; the database is unchanged by that file."""


def split_statements(script: str) -> list[str]:
    """Split a SQL script into complete statements (comments kept with their statement)."""
    statements: list[str] = []
    buf = ""
    pieces = script.split(";")
    for i, piece in enumerate(pieces):
        buf += piece if i == len(pieces) - 1 else piece + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \t\r\n;"):
                statements.append(buf.strip())
            buf = ""
    if buf.strip(" \t\r\n;"):
        raise MigrationError(f"incomplete SQL statement at end of script: {buf.strip()[:60]!r}")
    return statements


def migration_files(sql_dir: Path = SQL_DIR) -> list[tuple[int, Path]]:
    found = []
    for path in sorted(sql_dir.glob("*.sql")):
        match = _NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return found


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version"
        " (version INTEGER NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    row = conn.execute("SELECT max(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def apply_migrations(conn: sqlite3.Connection, sql_dir: Path = SQL_DIR) -> list[int]:
    """Apply every migration newer than the current version. Returns the versions applied."""
    applied: list[int] = []
    version = current_version(conn)
    for number, path in migration_files(sql_dir):
        if number <= version:
            continue
        statements = split_statements(path.read_text(encoding="utf-8"))
        old_isolation = conn.isolation_level
        conn.isolation_level = None  # we manage the transaction ourselves
        try:
            conn.execute("BEGIN")
            for statement in statements:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (number, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK")
            raise MigrationError(f"{path.name}: {exc}") from exc
        finally:
            conn.isolation_level = old_isolation
        applied.append(number)
    return applied

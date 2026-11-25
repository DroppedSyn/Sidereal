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


def read_version(conn: sqlite3.Connection) -> int:
    """Applied schema version without creating anything (works on a read-only connection);
    0 when ``schema_version`` is missing."""
    try:
        row = conn.execute("SELECT max(version) FROM schema_version").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row[0] or 0)


def apply_migrations(conn: sqlite3.Connection, sql_dir: Path = SQL_DIR) -> list[int]:
    """Apply every migration whose number is not recorded in ``schema_version`` (in number
    order), so a lower-numbered file that lands after a higher one still applies. Returns the
    versions applied."""
    applied: list[int] = []
    current_version(conn)  # creates schema_version if missing
    done = {int(r[0]) for r in conn.execute("SELECT version FROM schema_version").fetchall()}
    for number, path in migration_files(sql_dir):
        if number in done:
            continue
        statements = split_statements(path.read_text(encoding="utf-8"))
        old_isolation = conn.isolation_level
        conn.isolation_level = None  # we manage the transaction ourselves
        try:
            # IMMEDIATE takes the write lock first, then the version is checked again: a run
            # and the web service starting together must not both apply the same file.
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM schema_version WHERE version = ?",
                            (number,)).fetchone() is not None:
                conn.execute("COMMIT")
                continue
            for statement in statements:
                conn.execute(statement)  # sql-ok: statements from packaged .sql migration files
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

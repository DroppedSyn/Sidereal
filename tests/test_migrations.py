import sqlite3
from pathlib import Path

import pytest

from sidereal.db.connect import connect, ping
from sidereal.db.migrations import (
    MigrationError,
    apply_migrations,
    current_version,
    split_statements,
)

TABLES = {"sources", "focus_areas", "runs", "stories", "items", "assessments", "day_digests",
          "settings", "schema_version"}


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {r[0] for r in rows}


def test_init_schema_applies_and_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "s.db")
    assert apply_migrations(conn) == [1, 2]
    assert apply_migrations(conn) == []
    assert current_version(conn) == 2
    assert TABLES <= tables(conn)


def test_connection_pragmas(tmp_path: Path):
    conn = connect(tmp_path / "s.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    assert conn.row_factory is sqlite3.Row


def test_failed_migration_rolls_back(tmp_path: Path):
    sql = tmp_path / "sql"
    sql.mkdir()
    (sql / "0001_one.sql").write_text("CREATE TABLE a (x INTEGER);\n")
    (sql / "0002_two.sql").write_text(
        "CREATE TABLE b (x INTEGER);\nINSERT INTO a VALUES (1);\nINSERT INTO nowhere VALUES (1);\n"
    )
    conn = connect(tmp_path / "s.db")
    with pytest.raises(MigrationError, match="0002_two.sql"):
        apply_migrations(conn, sql)
    assert current_version(conn) == 1
    assert "a" in tables(conn)
    assert "b" not in tables(conn)
    assert conn.execute("SELECT count(*) FROM a").fetchone()[0] == 0
    # Fixing the file lets it apply cleanly afterwards.
    (sql / "0002_two.sql").write_text("CREATE TABLE b (x INTEGER);\n")
    assert apply_migrations(conn, sql) == [2]


def test_split_statements_keeps_triggers_and_literals_whole():
    script = (
        "-- comment; with a semicolon\nCREATE TABLE t (v TEXT DEFAULT ';');\n"
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET v = 'x'; "
        "DELETE FROM t WHERE v = 'y'; END;\n"
    )
    parts = split_statements(script)
    assert len(parts) == 2
    assert parts[1].startswith("CREATE TRIGGER") and parts[1].endswith("END;")


def test_split_statements_rejects_unterminated_statement():
    with pytest.raises(MigrationError):
        split_statements("CREATE TABLE t (x INTEGER);\nCREATE TABLE u (")


def test_ping_never_creates_the_database(tmp_path: Path):
    path = tmp_path / "missing.db"
    assert ping(path) is False
    assert not path.exists()
    conn = connect(path)
    apply_migrations(conn)
    conn.close()
    assert ping(path) is True

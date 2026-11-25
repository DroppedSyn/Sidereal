"""db/migrations.py (M28 change): a migration is applied when its number is not yet recorded,
so a lower-numbered file that lands after a higher one (parallel milestones) still runs."""

from pathlib import Path

from sidereal.db.connect import connect
from sidereal.db.migrations import apply_migrations, current_version


def test_late_lower_numbered_file_still_applies(tmp_path: Path):
    sql = tmp_path / "sql"
    sql.mkdir()
    (sql / "0001_one.sql").write_text("CREATE TABLE a (x INTEGER);\n")
    (sql / "0003_three.sql").write_text("CREATE TABLE c (x INTEGER);\n")
    conn = connect(tmp_path / "s.db")
    assert apply_migrations(conn, sql) == [1, 3]
    (sql / "0002_two.sql").write_text("CREATE TABLE b (x INTEGER);\n")
    assert apply_migrations(conn, sql) == [2]
    assert apply_migrations(conn, sql) == []
    assert current_version(conn) == 3
    assert conn.execute("SELECT count(*) FROM b").fetchone()[0] == 0

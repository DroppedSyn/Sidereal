"""db/backup.py + ``sidereal backup`` (M22): online backup, integrity check, keep N (§12.4)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest

from sidereal import commands
from sidereal.cli import main
from sidereal.db import backup
from sidereal.db.backup import BackupError, backup_name, list_backups, make_backup
from sidereal.db.connect import connect

AT = datetime(2026, 11, 25, 3, 30, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "sidereal.db"
    conn = connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
    conn.commit()
    conn.close()
    return path


def rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        conn.close()


def test_backup_name_is_utc_minute():
    assert backup_name(AT) == "sidereal-20261125-0330.db"
    local = AT.astimezone(timezone(timedelta(hours=5)))
    assert backup_name(local) == "sidereal-20261125-0330.db"
    with pytest.raises(ValueError):
        backup_name(datetime(2026, 11, 25))


def test_backup_copies_db_privately(db, tmp_path):
    out = tmp_path / "backups"
    result = make_backup(db, out, at=AT, keep=14)
    assert result.path == out / "sidereal-20261125-0330.db"
    assert rows(result.path) == 100 and result.size == result.path.stat().st_size
    assert result.path.stat().st_mode & 0o777 == 0o600
    assert result.removed == ()
    assert [p.name for p in out.iterdir()] == [result.path.name]  # no .partial left


def test_backup_while_a_writer_holds_an_open_transaction(db, tmp_path):
    writer = connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES (999)")
    try:
        result = make_backup(db, tmp_path / "b", at=AT, keep=14)
    finally:
        writer.rollback()
        writer.close()
    assert rows(result.path) == 100  # the committed snapshot, not the open transaction


def test_keeps_newest_n_and_ignores_other_files(db, tmp_path):
    out = tmp_path / "backups"
    out.mkdir()
    (out / "notes.txt").write_text("mine")
    (out / "sidereal-manual.db").write_text("mine too")
    made = [make_backup(db, out, at=AT + timedelta(days=d), keep=3) for d in range(5)]
    names = [p.name for p in list_backups(out)]
    assert names == [m.path.name for m in made[-3:]]
    assert made[3].removed == (made[0].path,) and made[4].removed == (made[1].path,)
    assert (out / "notes.txt").exists() and (out / "sidereal-manual.db").exists()


def test_keep_one_and_same_minute_replaces(db, tmp_path):
    out = tmp_path / "b"
    make_backup(db, out, at=AT, keep=1)
    make_backup(db, out, at=AT + timedelta(seconds=20), keep=1)
    assert [p.name for p in list_backups(out)] == ["sidereal-20261125-0330.db"]
    make_backup(db, out, at=AT + timedelta(hours=1), keep=1)
    assert [p.name for p in list_backups(out)] == ["sidereal-20261125-0430.db"]


def test_keep_must_be_positive_and_missing_db(db, tmp_path):
    with pytest.raises(ValueError):
        make_backup(db, tmp_path / "b", at=AT, keep=0)
    with pytest.raises(BackupError, match="missing"):
        make_backup(tmp_path / "nope.db", tmp_path / "b", at=AT, keep=1)
    assert not (tmp_path / "nope.db").exists()


def test_failed_integrity_check_keeps_old_backups(db, tmp_path, monkeypatch):
    out = tmp_path / "b"
    first = make_backup(db, out, at=AT, keep=1)
    monkeypatch.setattr(backup, "_quick_check", lambda conn: "page 3: corrupt")
    with pytest.raises(BackupError, match="integrity check: page 3: corrupt"):
        make_backup(db, out, at=AT + timedelta(days=1), keep=1)
    assert [p.name for p in out.iterdir()] == [first.path.name]  # old kept, no .partial


def test_cli_backup(settings, capsys, monkeypatch):
    assert main(["init"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("SIDEREAL_RETENTION__BACKUP_KEEP", "2")
    for minutes in range(3):
        monkeypatch.setattr(commands, "utc_now", lambda m=minutes: AT + timedelta(minutes=m))
        assert main(["backup"]) == 0
    out = capsys.readouterr().out
    assert "backup: " in out and "sidereal-20261125-0332.db" in out
    assert "removed: 1 old backup(s)" in out
    names = [p.name for p in list_backups(settings.state_dir / "backups")]
    assert names == ["sidereal-20261125-0331.db", "sidereal-20261125-0332.db"]


def test_cli_backup_without_db_exits_1(settings, capsys):
    assert main(["backup"]) == 1
    assert "missing (run: sidereal init)" in capsys.readouterr().err
    assert not settings.db_path.exists()

"""M13c read-only DB helpers used by ``sidereal doctor``: ``connect_readonly``,
``migrations.read_version``, ``sources_repo.last_item_times``."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from sidereal.db import sources_repo
from sidereal.db.connect import connect_readonly
from sidereal.db.migrations import migration_files, read_version
from tests.pipeline_helpers import NOW, add_story, seeded_db, start


def test_connect_readonly_never_creates(tmp_path):
    path = tmp_path / "none.db"
    with pytest.raises(sqlite3.OperationalError):
        connect_readonly(path)
    assert not path.exists()


def test_connect_readonly_refuses_writes(settings):
    seeded_db(settings).close()
    conn = connect_readonly(settings.db_path)
    try:
        assert read_version(conn) == max(v for v, _ in migration_files())
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM runs")
    finally:
        conn.close()


def test_read_version_without_table_is_zero_and_creates_nothing(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    assert read_version(conn) == 0
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    conn.close()


def test_last_item_times_newest_per_source(settings):
    conn = seeded_db(settings)
    rid = start(conn)
    add_story(conn, rid, source="krebs", at=NOW - timedelta(days=2))
    add_story(conn, rid, source="krebs", at=NOW)
    add_story(conn, rid, source="schneier", at=NOW - timedelta(days=9))
    times = sources_repo.last_item_times(conn)
    by_key = {sources_repo.get_source(conn, sid).key: at for sid, at in times.items()}
    assert by_key == {"krebs": NOW, "schneier": NOW - timedelta(days=9)}
    conn.close()

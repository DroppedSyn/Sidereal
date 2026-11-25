"""Final review: the day digest leaves hidden stories out (as the Daily view and the week
digest do), and a migration already applied by another process meanwhile is not re-run."""

from __future__ import annotations

import sqlite3

import pytest

from sidereal.db import assessments_repo, feedback_repo, stories_repo
from sidereal.db.connect import connect
from sidereal.db.migrations import apply_migrations, migration_files
from sidereal.pipeline import digest_step
from tests.pipeline_helpers import NOW, add_story, seeded_db, start

DAY = "2026-11-25"


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def _placed(conn, bucket, score):
    sid = add_story(conn, start(conn), day=DAY, title=f"Story {bucket} {score}")
    stories_repo.set_score(conn, sid, score=score, bucket=bucket)
    stories_repo.set_state(conn, sid, "assessed")
    assessments_repo.save_assessment(
        conn, sid, model="m", prompt_version="assess.v1", relevance=3, urgency=1,
        actionability=1, novelty=1, tags=[], summary="s", why="w", raw={}, duration_ms=1,
        at=NOW)
    return sid


def test_day_digest_set_skips_hidden_and_frees_the_slot(conn, settings):
    hidden = _placed(conn, "top", 90.0)
    second = _placed(conn, "top", 80.0)
    feedback_repo.set_hidden(conn, hidden, True, at=NOW)
    one_top = settings.model_copy(update={"scoring": settings.scoring.model_copy(
        update={"top_cap": 1})})
    assert digest_step.digest_set(conn, DAY, one_top) == [("top", second)]


class _StaleVersions(sqlite3.Connection):
    """Reads ``schema_version`` as empty once: the state another process saw just before this
    one applied every migration."""

    stale = True

    def execute(self, sql, *args):
        if self.stale and sql == "SELECT version FROM schema_version":
            type(self).stale = False
            return super().execute("SELECT version FROM schema_version WHERE 0")
        return super().execute(sql, *args)


def test_migration_applied_meanwhile_is_not_rerun(settings):
    path = settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    first = connect(path)
    assert apply_migrations(first) == [n for n, _ in migration_files()]
    first.close()
    late = sqlite3.connect(path, factory=_StaleVersions)
    try:
        assert apply_migrations(late) == []
        versions = [r[0] for r in late.execute("SELECT version FROM schema_version")]
        assert sorted(versions) == [n for n, _ in migration_files()]
    finally:
        late.close()

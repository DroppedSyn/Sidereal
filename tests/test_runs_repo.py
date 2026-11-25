"""Tests for ``src/sidereal/db/runs_repo.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db.runs_repo import (
    finish_run,
    get_run,
    last_ok_run,
    list_runs,
    mark_skipped,
    recover_stale,
    start_run,
)
from sidereal.timeutil import iso_z

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
T1 = T0 + timedelta(minutes=7)


def test_start_and_finish_round_trip(db):
    rid = start_run(db, trigger="timer", at=T0)
    run = get_run(db, rid)
    assert run is not None
    assert run.status == "running"
    assert run.started_at == "2026-11-20T12:00:00Z"
    assert run.finished_at is None
    assert run.stats == {}
    assert run.error is None
    assert run.trigger == "timer"

    finish_run(db, rid, status="ok",
               stats={"sources": {"ok": 20, "failed": 1}, "gate_wait_s": 0},
               at=T0 + timedelta(minutes=7))
    run = get_run(db, rid)
    assert run.status == "ok"
    assert run.finished_at == "2026-11-20T12:07:00Z"
    assert run.stats == {"sources": {"ok": 20, "failed": 1}, "gate_wait_s": 0}


def test_finish_with_error(db):
    rid = start_run(db, trigger="manual", at=T0)
    finish_run(db, rid, status="failed", stats={}, at=T1, error="boom")
    run = get_run(db, rid)
    assert run.error == "boom"


def test_invalid_status_raises(db):
    rid = start_run(db, trigger="timer", at=T0)
    with pytest.raises(ValueError):
        finish_run(db, rid, status="bogus", stats={}, at=T1)
    with pytest.raises(ValueError):
        finish_run(db, rid, status="running", stats={}, at=T1)
    run = get_run(db, rid)
    assert run.status == "running"


def test_invalid_trigger_raises(db):
    with pytest.raises(ValueError):
        start_run(db, trigger="cron", at=T0)


def test_finish_unknown_run_raises(db):
    with pytest.raises(KeyError):
        finish_run(db, 999, status="ok", stats={}, at=T0)


def test_mark_skipped(db):
    rid = mark_skipped(db, trigger="timer", at=T0, reason="run already in progress")
    run = get_run(db, rid)
    assert run is not None
    assert run.status == "skipped"
    assert run.started_at == run.finished_at == iso_z(T0)
    assert run.error == "run already in progress"
    assert run.stats == {}


def test_recover_stale_marks_only_running(db):
    A = start_run(db, trigger="timer", at=T0)
    finish_run(db, A, status="ok", stats={}, at=T0 + timedelta(minutes=5))
    B = start_run(db, trigger="timer", at=T0 + timedelta(minutes=10))
    C = start_run(db, trigger="timer", at=T0 + timedelta(minutes=15))
    finish_run(db, C, status="partial", stats={}, at=T0 + timedelta(minutes=20))
    D = start_run(db, trigger="timer", at=T0 + timedelta(minutes=25))

    count = recover_stale(db, at=T1)
    assert count == 2

    b = get_run(db, B)
    assert b.status == "failed"
    assert b.error == "interrupted"
    assert b.finished_at == iso_z(T1)

    d = get_run(db, D)
    assert d.status == "failed"
    assert d.error == "interrupted"
    assert d.finished_at == iso_z(T1)

    a = get_run(db, A)
    assert a.status == "ok"
    c = get_run(db, C)
    assert c.status == "partial"

    assert recover_stale(db, at=T1 + timedelta(minutes=1)) == 0


def test_list_runs_newest_first_and_paging(db):
    r1 = start_run(db, trigger="timer", at=T0)
    r2 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=1))
    r3 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=2))
    r4 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=3))
    r5 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=4))

    all_runs = list_runs(db)
    assert [r.id for r in all_runs] == [r5, r4, r3, r2, r1]

    limited = list_runs(db, limit=2)
    assert [r.id for r in limited] == [r5, r4]

    paged = list_runs(db, limit=2, before_id=r4)
    assert [r.id for r in paged] == [r3, r2]

    empty = list_runs(db, before_id=r1)
    assert empty == []


def test_get_run_missing(db):
    assert get_run(db, 999) is None


def test_last_ok_run(db):
    # empty DB
    assert last_ok_run(db) is None

    # one failed, one skipped
    f1 = start_run(db, trigger="timer", at=T0)
    finish_run(db, f1, status="failed", stats={}, at=T0 + timedelta(minutes=1))
    mark_skipped(db, trigger="timer", at=T0 + timedelta(minutes=2),
                      reason="lock held")
    assert last_ok_run(db) is None

    # add an ok run
    o1 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=3))
    finish_run(db, o1, status="ok", stats={}, at=T0 + timedelta(minutes=4))
    assert last_ok_run(db).id == o1

    # add a newer partial run
    p1 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=5))
    finish_run(db, p1, status="partial", stats={}, at=T0 + timedelta(minutes=6))
    assert last_ok_run(db).id == p1

    # add a newer failed run
    f2 = start_run(db, trigger="timer", at=T0 + timedelta(minutes=7))
    finish_run(db, f2, status="failed", stats={}, at=T0 + timedelta(minutes=8))
    assert last_ok_run(db).id == p1


def test_writes_commit(db):
    rid = start_run(db, trigger="timer", at=T0)
    assert db.in_transaction is False
    finish_run(db, rid, status="ok", stats={}, at=T1)
    assert db.in_transaction is False
    mark_skipped(db, trigger="manual", at=T1, reason="lock held")
    assert db.in_transaction is False
    start_run(db, trigger="catchup", at=T1)
    recover_stale(db, at=T1)
    assert db.in_transaction is False

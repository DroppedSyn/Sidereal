"""Tests for ``src/sidereal/db/assessments_repo.py``."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db.assessments_repo import get_assessment, save_assessment
from sidereal.db.runs_repo import start_run
from sidereal.db.stories_repo import create_story

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
RUBRIC = ("relevance", "urgency", "actionability", "novelty")


def _run(db):
    return start_run(db, trigger="timer", at=T0)


def _story(db, run_id, *, title="T", first_seen_at=T0, day="2026-11-20", cve_ids=()):
    return create_story(db, title=title, day=day, first_seen_at=first_seen_at,
                        first_run_id=run_id, cve_ids=cve_ids)


def _save(db, story_id, *, model="m1", numbers=(3, 2, 1, 0), tags=("entra", "cve"),
          raw=None, at=T0):
    relevance, urgency, actionability, novelty = numbers
    save_assessment(db, story_id, model=model, prompt_version="p-" + model,
                    relevance=relevance, urgency=urgency,
                    actionability=actionability, novelty=novelty,
                    tags=tags, summary="sum-" + model, why="why-" + model,
                    raw=raw if raw is not None else {"model": model},
                    duration_ms=len(model) * 100, at=at)


def test_save_and_get_round_trip(db):
    st = _story(db, _run(db))
    raw = {"relevance": 3, "nested": {"a": [1, 2]}}
    _save(db, st, tags=["entra", "cve"], raw=raw)
    a = get_assessment(db, st)
    assert a.story_id == st
    assert (a.model, a.prompt_version, a.summary, a.why) == ("m1", "p-m1", "sum-m1", "why-m1")
    assert (a.relevance, a.urgency, a.actionability, a.novelty) == (3, 2, 1, 0)
    assert a.tags == ["entra", "cve"]
    assert a.raw == raw
    assert a.duration_ms == 200
    assert a.created_at == "2026-11-20T12:00:00Z"


def test_save_upsert_replaces(db):
    st = _story(db, _run(db))
    _save(db, st)
    _save(db, st, model="m22", numbers=(0, 1, 2, 3), tags=["x"], at=T0 + timedelta(hours=1))
    a = get_assessment(db, st)
    assert (a.model, a.prompt_version, a.summary, a.why) == ("m22", "p-m22", "sum-m22", "why-m22")
    assert (a.relevance, a.urgency, a.actionability, a.novelty) == (0, 1, 2, 3)
    assert a.tags == ["x"]
    assert a.raw == {"model": "m22"}
    assert a.duration_ms == 300
    assert a.created_at == "2026-11-20T13:00:00Z"
    assert db.execute("SELECT count(*) FROM assessments").fetchone()[0] == 1


@pytest.mark.parametrize("field", range(4), ids=RUBRIC)
@pytest.mark.parametrize("bad", [4, -1])
def test_rubric_out_of_range(db, field, bad):
    st = _story(db, _run(db))
    numbers = [0, 3, 0, 3]
    numbers[field] = bad
    with pytest.raises(ValueError):
        _save(db, st, numbers=tuple(numbers))
    assert get_assessment(db, st) is None


def test_get_missing_returns_none(db):
    st = _story(db, _run(db))
    assert get_assessment(db, st) is None
    assert get_assessment(db, 9999) is None


def test_unknown_story_is_integrity_error(db):
    with pytest.raises(sqlite3.IntegrityError):
        _save(db, 9999)
    assert db.in_transaction is False


def test_writes_commit(db):
    st = _story(db, _run(db))
    _save(db, st)
    assert db.in_transaction is False
    _save(db, st, model="m2")
    assert db.in_transaction is False

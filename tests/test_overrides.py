"""overrides.py (M27): validation of settings-UI overrides and how runs/views pick them up."""

from __future__ import annotations

import logging

import pytest

from sidereal.config import Settings
from sidereal.db import settings_repo
from sidereal.overrides import (
    SECTIONS,
    OverrideError,
    apply_overrides,
    effective_settings,
    validate_overrides,
)

BASE = Settings()


def test_valid_overrides_cleaned():
    out = validate_overrides(BASE, {"scoring": {"top_threshold": 80, "top_cap": 5,
                                                "w_novelty": None},
                                    "budget": {"max_assess_per_run": 10}})
    assert out == {"scoring": {"top_threshold": 80.0, "top_cap": 5},
                   "budget": {"max_assess_per_run": 10}, "triage": {}}


@pytest.mark.parametrize("data, message", [
    ({"web": {"port": 1}}, "not editable: web"),
    ({"notify": {}}, "not editable: notify"),
    ({"scoring": {"nope": 1}}, "scoring.nope"),
    ({"scoring": {"top_threshold": 100.5}}, "scoring.top_threshold"),
    ({"scoring": {"side_threshold": -1}}, "scoring.side_threshold"),
    ({"scoring": {"w_relevance": 1.2}}, "scoring.w_relevance"),
    ({"scoring": {"kev_bonus": 51}}, "scoring.kev_bonus"),
    ({"scoring": {"top_cap": 0}}, "scoring.top_cap"),
    ({"scoring": {"top_cap": 101}}, "scoring.top_cap"),
    ({"scoring": {"top_cap": 2.5}}, "scoring.top_cap"),
    ({"scoring": {"top_cap": "5"}}, "scoring.top_cap"),
    ({"scoring": {"top_cap": True}}, "scoring.top_cap"),
    ({"scoring": {"recency_floor": 1.5}}, "scoring.recency_floor"),
    ({"scoring": {"w_novelty": float("nan")}}, "scoring.w_novelty"),
    ({"scoring": {"kev_bonus": float("inf")}}, "scoring.kev_bonus"),
    ({"budget": {"max_run_minutes": 86}}, "budget.max_run_minutes"),
    ({"budget": {"max_run_minutes": 4}}, "budget.max_run_minutes"),
    ({"budget": {"triage_batch_size": 0}}, "budget.triage_batch_size"),
    ({"budget": {"max_assess_per_run": -1}}, "budget.max_assess_per_run"),
    ({"triage": {"keep_min": 4}}, "triage.keep_min"),
    ({"scoring": {"relevant_threshold": 72}}, "top > relevant > side"),
    ({"scoring": {"side_threshold": 48}}, "top > relevant > side"),
    ({"scoring": {"top_threshold": 40}}, "top > relevant > side"),
    ({"scoring": {"corroboration_max": 3}}, "corroboration_max"),
])
def test_invalid_overrides(data, message):
    with pytest.raises(OverrideError, match=message):
        validate_overrides(BASE, data)


def test_consistency_uses_file_values():
    """A threshold is checked against the file's other thresholds, not the defaults."""
    file_settings = BASE.model_copy(update={"scoring": BASE.scoring.model_copy(
        update={"relevant_threshold": 30.0, "side_threshold": 10.0})})
    validate_overrides(file_settings, {"scoring": {"top_threshold": 40}})
    with pytest.raises(OverrideError):
        validate_overrides(BASE, {"scoring": {"top_threshold": 40}})


def test_every_editable_key_exists_in_settings():
    for name, model in SECTIONS.items():
        assert set(model.model_fields) <= set(type(getattr(BASE, name)).model_fields), name


def test_apply_overrides_wins_and_leaves_input():
    out = apply_overrides(BASE, {"scoring": {"top_cap": 3}, "budget": {"max_run_minutes": 30}})
    assert out.scoring.top_cap == 3 and out.budget.max_run_minutes == 30
    assert out.scoring.relevant_cap == BASE.scoring.relevant_cap
    assert BASE.scoring.top_cap == 8


def test_apply_skips_bad_stored_section(caplog):
    caplog.set_level(logging.WARNING)
    out = apply_overrides(BASE, {"scoring": {"top_cap": 999}, "budget": {"max_run_minutes": 30}})
    assert out.scoring.top_cap == 8 and out.budget.max_run_minutes == 30
    assert "ignoring stored scoring overrides" in caplog.text


def test_apply_skips_all_on_inconsistent_merge(caplog):
    caplog.set_level(logging.WARNING)
    out = apply_overrides(BASE, {"scoring": {"relevant_threshold": 90}})
    assert out == BASE
    assert "top > relevant > side" in caplog.text


def test_unknown_stored_section_ignored():
    assert apply_overrides(BASE, {"web": {"port": 1}}) == BASE


def test_effective_settings_reads_db(db):
    assert effective_settings(BASE, db) == BASE
    settings_repo.set_override(db, "scoring", {"top_cap": 4})
    settings_repo.set_override(db, "triage", {"keep_min": 3})
    eff = effective_settings(BASE, db)
    assert eff.scoring.top_cap == 4 and eff.triage.keep_min == 3


async def test_run_once_uses_stored_overrides(settings):
    """A run reads the settings-UI overrides: max_assess_per_run 0 → nothing assessed."""
    from sidereal.pipeline.runner import run_once
    from tests.pipeline_helpers import NOW, FeedServer, ollama_for, seeded_db, smart_ollama

    conn = seeded_db(settings)
    try:
        settings_repo.set_override(conn, "budget", {"max_assess_per_run": 0})
        row = await run_once(settings, conn, fetcher=FeedServer(conn).fetcher(),
                             ollama=ollama_for(smart_ollama(), settings), now=NOW)
        assert row.stats["assess"]["ok"] == 0 and row.stats["assess"]["deferred"] > 0
        assert row.stats["stories"]["new"] > 0
    finally:
        conn.close()

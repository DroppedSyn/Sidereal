"""Repository for the ``assessments`` table."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sidereal.timeutil import iso_z


@dataclass(frozen=True)
class AssessmentRow:
    story_id: int
    model: str
    prompt_version: str
    relevance: int
    urgency: int
    actionability: int
    novelty: int
    tags: list[str]
    summary: str
    why: str
    raw: dict[str, Any]
    duration_ms: int
    created_at: str


def _row(row: sqlite3.Row | None) -> AssessmentRow | None:
    if row is None:
        return None
    return AssessmentRow(
        story_id=row["story_id"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        relevance=row["relevance"],
        urgency=row["urgency"],
        actionability=row["actionability"],
        novelty=row["novelty"],
        tags=json.loads(row["tags_json"]),
        summary=row["summary"],
        why=row["why"],
        raw=json.loads(row["raw_json"]),
        duration_ms=row["duration_ms"],
        created_at=row["created_at"],
    )


def save_assessment(conn: sqlite3.Connection, story_id: int, *,
                    model: str, prompt_version: str,
                    relevance: int, urgency: int,
                    actionability: int, novelty: int,
                    tags: Sequence[str], summary: str,
                    why: str, raw: Mapping[str, Any],
                    duration_ms: int, at: datetime) -> None:
    """Upsert an assessment. Any rubric number outside 0..3 → ``ValueError``."""
    for val in (relevance, urgency, actionability, novelty):
        if val not in (0, 1, 2, 3):
            raise ValueError(f"rubric value must be 0..3, got {val!r}")

    tags_json = json.dumps(list(tags))
    raw_json = json.dumps(dict(raw), sort_keys=True)
    at_str = iso_z(at)

    with conn:
        conn.execute(
            "INSERT INTO assessments"
            " (story_id, model, prompt_version, relevance, urgency,"
            " actionability, novelty, tags_json, summary, why,"
            " raw_json, duration_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(story_id) DO UPDATE SET"
            " model = excluded.model,"
            " prompt_version = excluded.prompt_version,"
            " relevance = excluded.relevance,"
            " urgency = excluded.urgency,"
            " actionability = excluded.actionability,"
            " novelty = excluded.novelty,"
            " tags_json = excluded.tags_json,"
            " summary = excluded.summary,"
            " why = excluded.why,"
            " raw_json = excluded.raw_json,"
            " duration_ms = excluded.duration_ms,"
            " created_at = excluded.created_at",
            (story_id, model, prompt_version, relevance, urgency,
             actionability, novelty, tags_json, summary, why,
             raw_json, duration_ms, at_str),
        )


def get_assessment(conn: sqlite3.Connection, story_id: int) -> AssessmentRow | None:
    """Return the assessment for ``story_id``, or ``None``."""
    return _row(conn.execute(
        "SELECT * FROM assessments WHERE story_id = ?", (story_id,)
    ).fetchone())

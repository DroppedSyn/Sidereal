"""Read-only repository for the ``focus_areas`` table (seeded by ``init``, plan §5)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FocusRow:
    key: str
    name: str
    tier: str  # "primary" | "secondary" | "side"
    description: str
    keywords: tuple[str, ...]
    enabled: bool


def _row(row: sqlite3.Row) -> FocusRow:
    return FocusRow(
        key=row["key"],
        name=row["name"],
        tier=row["tier"],
        description=row["description"],
        keywords=tuple(json.loads(row["keywords_json"])),
        enabled=bool(row["enabled"]),
    )


def list_focus_areas(conn: sqlite3.Connection, *, enabled_only: bool = True) -> list[FocusRow]:
    """Focus areas by ``id`` (seed order); only enabled ones unless ``enabled_only=False``."""
    if enabled_only:
        rows = conn.execute(
            "SELECT * FROM focus_areas WHERE enabled = 1 ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM focus_areas ORDER BY id").fetchall()
    return [_row(r) for r in rows]

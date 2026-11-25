"""Settings-UI writes (M27): ``settings`` overrides, focus areas and sources.

The ``settings`` table holds one row per overridden config section (``key`` = section name,
``value_json`` = ``{field: value}``); ``sidereal.overrides`` validates and applies them. Focus
areas and sources are edited in place; values arrive validated by the API layer. Every write
commits itself (``with conn:``). Unknown ids/keys on writes → ``KeyError``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sidereal.timeutil import iso_z


class KeyTaken(Exception):
    """A focus area or source with this key already exists."""


def get_overrides(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """``{section: {field: value}}`` for every stored section whose JSON is an object."""
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute("SELECT key, value_json FROM settings ORDER BY key").fetchall():
        try:
            value = json.loads(row["value_json"])
        except ValueError:
            continue
        if isinstance(value, dict):
            out[row["key"]] = value
    return out


def set_override(conn: sqlite3.Connection, section: str, values: dict[str, Any]) -> None:
    """Store ``values`` for ``section``; an empty dict deletes the row (back to the file)."""
    with conn:
        if values:
            conn.execute(
                "INSERT INTO settings (key, value_json) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (section, json.dumps(values, sort_keys=True)),
            )
        else:
            conn.execute("DELETE FROM settings WHERE key = ?", (section,))


# --- focus areas -------------------------------------------------------------------------


def add_focus_area(conn: sqlite3.Connection, *, key: str, name: str, tier: str,
                   description: str, keywords: Sequence[str], enabled: bool) -> None:
    """Insert a focus area; a taken key raises ``KeyTaken``."""
    with conn:
        cur = conn.execute(
            "INSERT INTO focus_areas (key, name, tier, description, keywords_json, enabled)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO NOTHING",
            (key, name, tier, description, json.dumps(list(keywords)), int(enabled)),
        )
    if cur.rowcount == 0:
        raise KeyTaken(key)


def update_focus_area(conn: sqlite3.Connection, key: str, *, name: str, tier: str,
                      description: str, keywords: Sequence[str], enabled: bool) -> None:
    with conn:
        cur = conn.execute(
            "UPDATE focus_areas SET name = ?, tier = ?, description = ?, keywords_json = ?,"
            " enabled = ? WHERE key = ?",
            (name, tier, description, json.dumps(list(keywords)), int(enabled), key),
        )
    if cur.rowcount == 0:
        raise KeyError(key)


def delete_focus_area(conn: sqlite3.Connection, key: str) -> None:
    with conn:
        cur = conn.execute("DELETE FROM focus_areas WHERE key = ?", (key,))
    if cur.rowcount == 0:
        raise KeyError(key)


# --- sources -----------------------------------------------------------------------------


def add_source(conn: sqlite3.Connection, *, key: str, name: str, kind: str, url: str,
               enabled: bool, weight: float, max_items: int, options: dict[str, Any],
               at: datetime) -> int:
    """Insert a source and return its id; a taken key raises ``KeyTaken``."""
    with conn:
        cur = conn.execute(
            "INSERT INTO sources (key, name, kind, url, enabled, weight, max_items,"
            " options_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(key) DO NOTHING",
            (key, name, kind, url, int(enabled), weight, max_items,
             json.dumps(options, sort_keys=True), iso_z(at)),
        )
    if cur.rowcount == 0:
        raise KeyTaken(key)
    return int(cur.lastrowid or 0)


def update_source(conn: sqlite3.Connection, source_id: int, *, name: str, url: str,
                  enabled: bool, weight: float, max_items: int,
                  options: dict[str, Any]) -> None:
    """Edit a source (key and kind stay). A changed URL clears the conditional-GET validators,
    which belong to the old URL."""
    with conn:
        cur = conn.execute(
            "UPDATE sources SET name = ?, enabled = ?, weight = ?, max_items = ?,"
            " options_json = ?,"
            " etag = CASE WHEN url = ? THEN etag ELSE NULL END,"
            " last_modified = CASE WHEN url = ? THEN last_modified ELSE NULL END,"
            " url = ? WHERE id = ?",
            (name, int(enabled), weight, max_items, json.dumps(options, sort_keys=True),
             url, url, url, source_id),
        )
    if cur.rowcount == 0:
        raise KeyError(source_id)


def source_item_count(conn: sqlite3.Connection, source_id: int) -> int:
    return int(conn.execute(
        "SELECT count(*) FROM items WHERE source_id = ?", (source_id,)).fetchone()[0])


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    """Delete a source without items (the caller checks ``source_item_count`` first; items
    reference it, so SQLite refuses otherwise)."""
    with conn:
        cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    if cur.rowcount == 0:
        raise KeyError(source_id)

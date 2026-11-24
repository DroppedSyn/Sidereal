"""Seed rows for ``sources`` and ``focus_areas``. Insert-only: existing keys are never touched."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime

from sidereal.defaults import FocusSeed, SourceSeed


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_sources(conn: sqlite3.Connection, seeds: Iterable[SourceSeed]) -> int:
    """Insert sources whose key is missing. Returns how many rows were added."""
    added = 0
    with conn:
        for s in seeds:
            cur = conn.execute(
                "INSERT INTO sources (key, name, kind, url, enabled, weight, max_items,"
                " options_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(key) DO NOTHING",
                (s.key, s.name, s.kind, s.url, int(s.enabled), s.weight, s.max_items,
                 json.dumps(s.options, sort_keys=True), _now()),
            )
            added += cur.rowcount
    return added


def seed_focus_areas(conn: sqlite3.Connection, seeds: Iterable[FocusSeed]) -> int:
    """Insert focus areas whose key is missing. Returns how many rows were added."""
    added = 0
    with conn:
        for f in seeds:
            cur = conn.execute(
                "INSERT INTO focus_areas (key, name, tier, description, keywords_json, enabled)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO NOTHING",
                (f.key, f.name, f.tier, f.description, json.dumps(f.keywords), int(f.enabled)),
            )
            added += cur.rowcount
    return added

"""db/focus_repo.py (M13b): read the seeded focus areas."""

from __future__ import annotations

from sidereal.db import focus_repo
from tests.pipeline_helpers import seeded_db


def test_lists_seeded_areas_in_order(settings):
    conn = seeded_db(settings)
    rows = focus_repo.list_focus_areas(conn)
    assert [r.key for r in rows][:3] == ["azure-networking", "network-architecture",
                                         "entra-identity"]
    assert rows[0].tier == "primary" and "vnet" in rows[0].keywords
    assert isinstance(rows[0].keywords, tuple) and rows[0].description and rows[0].enabled


def test_enabled_only(settings):
    conn = seeded_db(settings)
    with conn:
        conn.execute("UPDATE focus_areas SET enabled = 0 WHERE key = 'industry'")
    assert "industry" not in [r.key for r in focus_repo.list_focus_areas(conn)]
    every = focus_repo.list_focus_areas(conn, enabled_only=False)
    assert [r.enabled for r in every if r.key == "industry"] == [False]

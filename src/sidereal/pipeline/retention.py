"""Data lifecycle (plan §12.4), run at the end of every pipeline run: clear article text older
than ``content_days`` and delete dropped / filtered / triaged-out stories (with their items and
assessments) first seen more than ``drop_days`` ago. Summaries and excerpts are kept forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sidereal.config import RetentionSettings
from sidereal.db import Connection, items_repo, stories_repo


def apply_retention(conn: Connection, cfg: RetentionSettings, *, now: datetime) -> dict[str, int]:
    """Prune; returns ``{"content_pruned": n, "stories_deleted": m}`` for the run stats."""
    pruned = items_repo.prune_content(conn, older_than=now - timedelta(days=cfg.content_days))
    deleted = stories_repo.delete_dropped_before(conn, before=now - timedelta(days=cfg.drop_days))
    return {"content_pruned": pruned, "stories_deleted": deleted}

"""Small pieces shared by the pipeline steps: the run deadline, a story with its items and
sources, and a log-safe error string."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sidereal.db import Connection, items_repo
from sidereal.db.items_repo import ItemRow
from sidereal.db.sources_repo import SourceRow
from sidereal.db.stories_repo import StoryRow
from sidereal.timeutil import parse_iso_z

ERROR_MAX_CHARS = 200


class Deadline:
    """``Deadline(seconds)()`` is True once ``seconds`` have passed since construction (plan
    §9.2). ``None`` seconds never expire. ``clock`` is injectable for tests."""

    def __init__(self, seconds: float | None, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._end = None if seconds is None else clock() + seconds
        self.hit = False  # set once a step has seen it expired

    def __call__(self) -> bool:
        if self._end is not None and self._clock() >= self._end:
            self.hit = True
        return self.hit


def short_error(exc: BaseException) -> str:
    """``"<ExcType>: <message>"`` cut to 200 chars (fetch/LLM messages never carry bodies)."""
    text = f"{type(exc).__name__}: {exc}".strip()
    return text if len(text) <= ERROR_MAX_CHARS else text[: ERROR_MAX_CHARS - 1] + "…"


@dataclass(frozen=True)
class StoryBundle:
    story: StoryRow
    items: list[ItemRow]  # item-id order
    lead: ItemRow | None  # lead_item_id, else the first item
    sources: list[SourceRow]  # distinct, in item order

    @property
    def source_keys(self) -> tuple[str, ...]:
        return tuple(s.key for s in self.sources)

    @property
    def source_weights(self) -> tuple[float, ...]:
        return tuple(s.weight for s in self.sources)

    @property
    def published(self) -> datetime | None:
        """Earliest item ``published_at``, or None when no item is dated."""
        dates = [parse_iso_z(i.published_at) for i in self.items if i.published_at]
        return min(dates) if dates else None

    @property
    def first_seen(self) -> datetime:
        return parse_iso_z(self.story.first_seen_at)


def bundle(conn: Connection, story: StoryRow,
           sources_by_id: Mapping[int, SourceRow]) -> StoryBundle:
    items = items_repo.items_for_story(conn, story.id)
    lead = next((i for i in items if i.id == story.lead_item_id), items[0] if items else None)
    seen: dict[int, SourceRow] = {}
    for it in items:
        if it.source_id not in seen and it.source_id in sources_by_id:
            seen[it.source_id] = sources_by_id[it.source_id]
    return StoryBundle(story, items, lead, list(seen.values()))

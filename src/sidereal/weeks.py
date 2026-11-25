"""ISO weeks (M29): keys ``YYYY-Www``, their local days and English labels. Pure.

A week is Monday..Sunday of *local* days (``schedule.tz``): stories carry the local day of
first sight (rule 6), so a week's stories are those whose ``day`` falls in its seven dates,
and "which week is it now" is the ISO week of ``day_key(now, tz)``, never of the UTC date.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sidereal.timeutil import day_key

_WEEK = re.compile(r"(\d{4})-W(\d{2})", re.ASCII)  # no fullwidth digits


def week_key(day: date | str) -> str:
    """The ISO week of a date (or ``YYYY-MM-DD``): ``2027-01-02`` → ``2026-W53``."""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def week_start(week: str) -> date:
    """Monday of *week*; anything that is not a real ISO week → ValueError."""
    m = _WEEK.fullmatch(week) if isinstance(week, str) else None
    if m is None:
        raise ValueError(f"week must be YYYY-Www, got {week!r}")
    try:
        return date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        raise ValueError(f"no such ISO week: {week!r}") from None


def is_week(week: str) -> bool:
    try:
        week_start(week)
    except ValueError:
        return False
    return True


def week_days(week: str) -> list[str]:
    """The seven local days ``YYYY-MM-DD`` of *week*, Monday first."""
    monday = week_start(week)
    return [(monday + timedelta(days=k)).isoformat() for k in range(7)]


def _dmy(d: date) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def week_label(week: str) -> str:
    """``2026-W48`` → ``Week 48 · 23.11.2026 – 29.11.2026``."""
    monday = week_start(week)
    return f"Week {int(week[-2:])} · {_dmy(monday)} – {_dmy(monday + timedelta(days=6))}"


def previous_week(week: str) -> str:
    return week_key(week_start(week) - timedelta(days=7))


def local_today(now: datetime, tz: str) -> date:
    return date.fromisoformat(day_key(now, tz))


def current_week(now: datetime, tz: str) -> str:
    """The ISO week of the local date of *now* in *tz*."""
    return week_key(local_today(now, tz))

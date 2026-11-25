"""Date/time helpers for Sidereal."""

from __future__ import annotations

import time
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from feedparser.datetimes import _parse_date

_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def utc_now() -> datetime:
    """datetime.now(UTC)."""
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Aware datetime → same instant with tzinfo UTC. Naive → ValueError."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC)


def from_struct_time(st: time.struct_time | None) -> datetime | None:
    """feedparser struct_time (UTC) → datetime. None or error → None."""
    if st is None:
        return None
    try:
        return datetime(
            st.tm_year, st.tm_mon, st.tm_mday,
            st.tm_hour, st.tm_min, st.tm_sec,
            tzinfo=UTC,
        )
    except (TypeError, ValueError):
        return None


def parse_date_text(text: str | None) -> datetime | None:
    """Parse a date string with feedparser; None/""/unparseable → None."""
    if not text:
        return None
    try:
        st = _parse_date(text)
        return from_struct_time(st)
    except Exception:
        return None


def drop_future(dt: datetime | None, now: datetime) -> datetime | None:
    """None if dt is None or dt > now + 1 day; else dt unchanged."""
    if dt is None:
        return None
    if dt > now + timedelta(days=1):
        return None
    return dt


def entry_published(entry: Mapping[str, Any], now: datetime) -> datetime | None:
    """First usable of published_parsed, updated_parsed, created_parsed (checked with
    `key in entry`: feedparser's .get() aliases updated → published with a DeprecationWarning).
    A value that is None, unbuildable or more than 1 day in the future counts as missing, so
    the next key is tried. None if none usable."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        if key in entry and entry[key] is not None:
            dt = from_struct_time(entry[key])
            if dt is not None:
                result = drop_future(dt, now)
                if result is not None:
                    return result
    return None


def iso_z(dt: datetime) -> str:
    """to_utc(dt), microseconds dropped, formatted 'YYYY-MM-DDTHH:MM:SSZ'."""
    return to_utc(dt).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_z(text: str) -> datetime:
    """datetime.fromisoformat(text) → to_utc. No offset or garbage → ValueError."""
    dt = datetime.fromisoformat(text)
    return to_utc(dt)


def day_key(dt: datetime, tz: str | ZoneInfo) -> str:
    """to_utc(dt) converted to tz → date.isoformat() 'YYYY-MM-DD'."""
    zone = tz if isinstance(tz, ZoneInfo) else ZoneInfo(tz)
    return to_utc(dt).astimezone(zone).date().isoformat()


def day_label(day: str) -> str:
    """'YYYY-MM-DD' → '<Weekday> - DD.MM.YYYY'. Anything invalid → ValueError."""
    if len(day) != 10:
        raise ValueError(f"bad day format: {day!r}")
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise ValueError(f"bad day format: {day!r}") from None
    weekday = _DAYS[d.weekday()]
    return f"{weekday} - {d.day:02d}.{d.month:02d}.{d.year}"

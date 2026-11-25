"""weeks.py (M29): ISO week keys, days, labels and the current local week."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from sidereal.weeks import (
    current_week,
    is_week,
    previous_week,
    week_days,
    week_key,
    week_label,
    week_start,
)


@pytest.mark.parametrize(("day", "week"), [
    ("2026-11-23", "2026-W48"),  # Monday
    ("2026-11-29", "2026-W48"),  # Sunday
    ("2026-11-30", "2026-W49"),
    ("2026-12-28", "2026-W53"),  # 2026 has 53 ISO weeks (1 Jan 2026 is a Thursday)
    ("2027-01-01", "2026-W53"),
    ("2027-01-03", "2026-W53"),
    ("2027-01-04", "2027-W01"),
    ("2025-12-29", "2026-W01"),  # ISO year starts in the previous calendar year
    ("2024-12-30", "2025-W01"),
    ("2021-01-03", "2020-W53"),
])
def test_week_key_year_boundaries(day, week):
    assert week_key(day) == week
    assert week_key(date.fromisoformat(day)) == week
    assert day in week_days(week)


def test_week_days_of_53rd_week_span_the_new_year():
    assert week_days("2026-W53") == ["2026-12-28", "2026-12-29", "2026-12-30", "2026-12-31",
                                     "2027-01-01", "2027-01-02", "2027-01-03"]
    assert week_days("2027-W01")[0] == "2027-01-04"


@pytest.mark.parametrize("bad", ["2025-W53", "2026-W54", "2026-W00", "2026-48", "2026-W4",
                                 "2026-w48", " 2026-W48", "2026-W48\n", "", "2026-W4８"])
def test_bad_weeks_are_refused(bad):
    assert not is_week(bad)
    with pytest.raises(ValueError):
        week_start(bad)


def test_labels():
    assert week_label("2026-W48") == "Week 48 · 23.11.2026 – 29.11.2026"
    assert week_label("2026-W53") == "Week 53 · 28.12.2026 – 03.01.2027"
    assert week_label("2027-W01") == "Week 1 · 04.01.2027 – 10.01.2027"


def test_previous_week_across_years():
    assert previous_week("2027-W01") == "2026-W53"
    assert previous_week("2026-W01") == "2025-W52"
    assert previous_week("2026-W48") == "2026-W47"


def test_current_week_uses_the_local_date_not_utc():
    # Sunday 29.03.2026 23:30 UTC is Monday 00:30 in London (BST started that morning).
    now = datetime(2026, 3, 29, 23, 30, tzinfo=UTC)
    assert current_week(now, "Europe/London") == "2026-W14"
    assert current_week(now, "UTC") == "2026-W13"
    # Sunday 25.10.2026 23:30 UTC is still Sunday 23:30 in London (GMT again after DST).
    assert current_week(datetime(2026, 10, 25, 23, 30, tzinfo=UTC), "Europe/London") == "2026-W43"
    # West of UTC: Monday 04.01.2027 03:00 UTC is still Sunday evening in New York.
    assert current_week(datetime(2027, 1, 4, 3, 0, tzinfo=UTC), "America/New_York") == "2026-W53"

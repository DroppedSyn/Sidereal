import time
import warnings
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser
import pytest

from sidereal.timeutil import (
    day_key,
    day_label,
    drop_future,
    entry_published,
    from_struct_time,
    iso_z,
    parse_date_text,
    parse_iso_z,
    to_utc,
    utc_now,
)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _rss(pub: str | None) -> bytes:
    date = f"<pubDate>{pub}</pubDate>" if pub else ""
    return (
        '<rss version="2.0"><channel><title>t</title><item><title>a</title>'
        f"{date}</item></channel></rss>"
    ).encode()


def test_utc_now_is_aware_utc():
    n = utc_now()
    assert n.tzinfo is UTC
    assert n.utcoffset() == timedelta(0)


def test_to_utc_converts_offset():
    r = to_utc(
        datetime(2026, 11, 20, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    assert r == datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    assert r.tzinfo is UTC


def test_to_utc_rejects_naive():
    with pytest.raises(ValueError):
        to_utc(datetime(2026, 11, 20, 12, 0))


def test_from_struct_time():
    assert (
        from_struct_time(
            time.struct_time((2026, 11, 20, 12, 0, 0, 4, 324, 0))
        )
        == datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    )
    assert from_struct_time(None) is None


def test_cisa_two_digit_year():
    e = feedparser.parse(
        _rss("Fri, 20 Nov 26 12:00:00 +0000")
    ).entries[0]
    assert entry_published(e, NOW) == datetime(
        2026, 11, 20, 12, 0, tzinfo=UTC
    )
    assert parse_date_text(
        "Fri, 20 Nov 26 12:00:00 +0000"
    ) == datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_parse_date_text_formats():
    assert (
        parse_date_text("2026-11-20T12:00:00Z")
        == datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    )
    assert (
        parse_date_text("Fri, 20 Nov 2026 14:00:00 +0200")
        == datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    )
    assert (
        parse_date_text("Tue, 24 Nov 2026 10:00:00 EST")
        == datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
    )


def test_parse_date_text_bad_is_none():
    for x in ("garbage", "", None):
        assert parse_date_text(x) is None


def test_entry_without_date_is_none():
    assert (
        entry_published(feedparser.parse(_rss(None)).entries[0], NOW) is None
    )


def test_entry_bad_date_is_none_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert (
            entry_published(
                feedparser.parse(_rss("nonsense")).entries[0], NOW
            )
            is None
        )


def test_entry_falls_back_to_updated_then_created():
    assert entry_published(
        {
            "updated_parsed": time.struct_time(
                (2026, 11, 20, 10, 0, 0, 4, 324, 0)
            )
        },
        NOW,
    ) == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert entry_published(
        {
            "published_parsed": None,
            "created_parsed": time.struct_time(
                (2026, 11, 19, 10, 0, 0, 3, 323, 0)
            ),
        },
        NOW,
    ) == datetime(2026, 11, 19, 10, 0, tzinfo=UTC)


def test_entry_future_published_falls_back_to_updated():
    entry = {
        "published_parsed": time.struct_time((2026, 12, 20, 10, 0, 0, 6, 354, 0)),
        "updated_parsed": time.struct_time((2026, 11, 20, 10, 0, 0, 4, 324, 0)),
    }
    assert entry_published(entry, NOW) == datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def test_drop_future():
    assert drop_future(NOW + timedelta(days=1, seconds=1), NOW) is None
    assert (
        drop_future(NOW + timedelta(days=1), NOW)
        == NOW + timedelta(days=1)
    )
    assert (
        drop_future(NOW - timedelta(days=3), NOW)
        == NOW - timedelta(days=3)
    )
    assert drop_future(None, NOW) is None


def test_entry_future_date_is_none():
    assert (
        entry_published(
            feedparser.parse(
                _rss("Fri, 27 Nov 2026 12:00:00 +0000")
            ).entries[0],
            NOW,
        )
        is None
    )


def test_iso_z():
    assert (
        iso_z(
            datetime(
                2026, 11, 20, 12, 0, 5, 123456, tzinfo=UTC
            )
        )
        == "2026-11-20T12:00:05Z"
    )
    assert (
        iso_z(
            datetime(
                2026, 11, 20, 14, 0, tzinfo=timezone(timedelta(hours=2))
            )
        )
        == "2026-11-20T12:00:00Z"
    )
    with pytest.raises(ValueError):
        iso_z(datetime(2026, 11, 20, 12, 0))


def test_parse_iso_z():
    r = parse_iso_z("2026-11-20T12:00:05Z")
    assert r == datetime(2026, 11, 20, 12, 0, 5, tzinfo=UTC)
    assert r.tzinfo is UTC
    assert (
        parse_iso_z("2026-11-20T14:00:05+02:00")
        == datetime(2026, 11, 20, 12, 0, 5, tzinfo=UTC)
    )
    dt = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)
    assert parse_iso_z(iso_z(dt)) == dt


def test_parse_iso_z_rejects_naive_and_garbage():
    for x in ("2026-11-20T12:00:05", "nope", ""):
        with pytest.raises(ValueError):
            parse_iso_z(x)


def test_day_key_bst_boundary():
    assert (
        day_key(
            datetime(2026, 10, 24, 23, 30, tzinfo=UTC), "Europe/London"
        )
        == "2026-10-25"
    )
    assert (
        day_key(
            datetime(2026, 10, 24, 22, 30, tzinfo=UTC), "Europe/London"
        )
        == "2026-10-24"
    )


def test_day_key_gmt():
    assert (
        day_key(
            datetime(2026, 3, 29, 0, 30, tzinfo=UTC), "Europe/London"
        )
        == "2026-03-29"
    )
    assert (
        day_key(
            datetime(2026, 3, 28, 23, 30, tzinfo=UTC), "Europe/London"
        )
        == "2026-03-28"
    )
    assert (
        day_key(
            datetime(2026, 1, 15, 23, 30, tzinfo=UTC), "Europe/London"
        )
        == "2026-01-15"
    )


def test_day_key_zoneinfo_and_utc():
    assert (
        day_key(
            datetime(2026, 7, 14, 23, 30, tzinfo=UTC),
            ZoneInfo("Europe/London"),
        )
        == "2026-07-15"
    )
    assert (
        day_key(datetime(2026, 7, 14, 23, 30, tzinfo=UTC), "UTC")
        == "2026-07-14"
    )


def test_day_key_rejects_naive():
    with pytest.raises(ValueError):
        day_key(datetime(2026, 7, 14, 23, 30), "Europe/London")


def test_day_label():
    assert day_label("2026-07-12") == "Sunday - 12.07.2026"
    assert day_label("2026-07-14") == "Tuesday - 14.07.2026"
    assert day_label("2026-01-05") == "Monday - 05.01.2026"


def test_day_label_rejects_bad():
    for x in ("2026-13-01", "12.07.2026", "20260712", ""):
        with pytest.raises(ValueError):
            day_label(x)

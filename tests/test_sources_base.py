from __future__ import annotations

import dataclasses
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

import sidereal.sources
from sidereal.sources.base import (
    REGISTRY,
    FetchResult,
    RawItem,
    apply_age_cap,
    newest_first,
    option_regex,
    register,
)
from sidereal.sources.msrc import MsrcAdapter
from sidereal.sources.rss import RssAdapter
from tests.adapter_helpers import FakeSource

T = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def item(title: str, published: datetime | None) -> RawItem:
    return RawItem(
        source_key="s",
        guid=title,
        url="https://example.com/" + title,
        title=title,
        published=published,
        author=None,
        excerpt_html="",
        extra={},
    )


def four() -> list[RawItem]:
    return [
        item("a", T - timedelta(hours=2)),
        item("b", None),
        item("c", T),
        item("d", T - timedelta(hours=1)),
    ]


def test_newest_first_sorts_desc_none_last():
    assert [i.title for i in newest_first(four(), 10)] == ["c", "d", "a", "b"]


def test_newest_first_limit():
    assert [i.title for i in newest_first(four(), 2)] == ["c", "d"]


def test_newest_first_ties_keep_feed_order():
    items = [item("x", T), item("y", T), item("z", T)]
    assert [i.title for i in newest_first(items, 10)] == ["x", "y", "z"]


def test_age_cap_none_keeps_all():
    assert [i.title for i in apply_age_cap(four(), T, None)] == ["a", "b", "c", "d"]


def test_age_cap_boundary_kept():
    items = [
        item("p", T - timedelta(hours=24)),
        item("q", T - timedelta(hours=24, seconds=1)),
        item("r", None),
    ]
    assert [i.title for i in apply_age_cap(items, T, 24)] == ["p", "r"]


def test_raw_item_is_frozen():
    it = item("a", T)
    with pytest.raises(dataclasses.FrozenInstanceError):
        it.title = "x"  # type: ignore[misc]


def test_register_rejects_duplicate_kind():
    class Dummy:
        kind = "dummy-test"

        async def fetch(self, source, fetcher, now, *, max_age_hours=None):
            return FetchResult(items=[])

    class Other(Dummy):
        kind = "dummy-test"

    try:
        assert register(Dummy) is Dummy
        assert REGISTRY["dummy-test"] is Dummy
        with pytest.raises(ValueError, match="dummy-test"):
            register(Other)
        assert REGISTRY["dummy-test"] is Dummy
        assert register(Dummy) is Dummy
    finally:
        REGISTRY.pop("dummy-test", None)


def test_registry_has_rss_and_msrc():
    assert sidereal.sources.REGISTRY is REGISTRY
    assert REGISTRY["rss"] is RssAdapter
    assert REGISTRY["msrc"] is MsrcAdapter


def test_option_regex():
    src = FakeSource(key="k", options={"a": "(?i)x", "empty": "", "bad": "(", "num": 5})
    assert option_regex(src, "a").search("X")
    assert option_regex(src, "missing") is None
    assert option_regex(src, "empty") is None
    assert option_regex(src, "missing", "d").pattern == "d"
    assert option_regex(src, "empty", "d").pattern == "d"
    with pytest.raises(ValueError, match=r"k: invalid options\.bad"):
        option_regex(src, "bad")
    with pytest.raises(ValueError, match=r"k: invalid options\.num"):
        option_regex(src, "num")


def test_package_import_registers_all_kinds():
    code = (
        "import sidereal.sources.base as b; import sidereal.sources; "
        "print(sorted(k for k in b.REGISTRY))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "['cisa_kev', 'hn_algolia', 'msrc', 'rss']"

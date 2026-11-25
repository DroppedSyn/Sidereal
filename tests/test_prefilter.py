from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sidereal.pipeline.prefilter import (
    Candidate,
    Decision,
    FocusArea,
    Mutes,
    age_band,
    match_keywords,
    order_for_triage,
    prefilter,
)

NOW = datetime(2026, 11, 25, 12, 0, 0, tzinfo=UTC)

FOCUS = (
    FocusArea(
        key="az",
        tier="primary",
        keywords=("vnet", "conditional access", "pim", "workload identit", "cve-"),
    ),
    FocusArea(
        key="netsec",
        tier="secondary",
        keywords=("fortinet", "exploit", "vpn"),
    ),
    FocusArea(key="ind", tier="side", keywords=("outage",)),
)

_EMPTY_MUTES = Mutes()


def make_candidate(**overrides):
    fields = dict(
        story_id=1,
        title="Something unrelated",
        source_keys=("blog",),
        max_source_weight=1.0,
        published=NOW - timedelta(hours=1),
        first_seen=NOW - timedelta(hours=1),
        kev_vendor=None,
    )
    fields.update(overrides)
    return Candidate(**fields)


def decide(c, mutes=None, max_age_hours=96):
    if mutes is None:
        mutes = _EMPTY_MUTES
    return prefilter(c, FOCUS, mutes, now=NOW, max_age_hours=max_age_hours)


# ── match_keywords ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title, expected",
    [
        ("PIM roles", {"az": 1}),
        ("Pimple", {}),
        ("New VNets", {"az": 1}),
        ("Conditional Access gaps", {"az": 1}),
        ("Workload identities", {"az": 1}),
        ("CVE-2026-1234 fixed", {"az": 1}),
        ("Fortinet exploited", {"netsec": 2}),
        ("VPN outage", {"netsec": 1, "ind": 1}),
        ("Assessment", {}),
    ],
)
def test_match_keywords(title, expected):
    result = match_keywords(title, FOCUS)
    assert result == expected


# ── prefilter: each reason ────────────────────────────────────────


def test_triage():
    c = make_candidate(title="Something unrelated")
    d = decide(c)
    assert d.reason == "triage"
    assert d.keep is True
    assert d.always is False
    assert d.hint_score == 0
    assert d.focus_hits == ()


def test_primary_keyword():
    c = make_candidate(title="VNet outage")
    d = decide(c)
    assert d.reason == "primary_keyword"
    assert d.keep is True
    assert d.always is True


def test_trusted_source():
    c = make_candidate(max_source_weight=1.3)
    d = decide(c)
    assert d.reason == "trusted_source"
    assert d.keep is True
    assert d.always is True


def test_kev_microsoft():
    c = make_candidate(kev_vendor="Microsoft")
    d = decide(c)
    assert d.reason == "kev_microsoft"
    assert d.keep is True
    assert d.always is True


def test_muted_source():
    mutes = Mutes(sources=frozenset({"blog"}))
    c = make_candidate(source_keys=("blog",))
    d = decide(c, mutes=mutes)
    assert d.reason == "muted_source"
    assert d.keep is False
    assert d.always is False


def test_muted_keyword():
    mutes = Mutes(keywords=("webinar",))
    c = make_candidate(title="Free webinar")
    d = decide(c, mutes=mutes)
    assert d.reason == "muted_keyword"
    assert d.keep is False
    assert d.always is False


def test_too_old():
    c = make_candidate(published=NOW - timedelta(hours=100))
    d = decide(c)
    assert d.reason == "too_old"
    assert d.keep is False
    assert d.always is False


# ── prefilter: edge cases ─────────────────────────────────────────


def test_kev_vendor_fortinet_triage():
    c = make_candidate(
        kev_vendor="Fortinet",
        title="Unrelated thing",
    )
    d = decide(c)
    assert d.reason == "triage"


def test_kev_vendor_whitespace_microsoft():
    c = make_candidate(kev_vendor=" microsoft ")
    d = decide(c)
    assert d.reason == "kev_microsoft"


def test_weight_129_triage():
    c = make_candidate(max_source_weight=1.29)
    d = decide(c)
    assert d.reason == "triage"


def test_weight_13_trusted():
    c = make_candidate(max_source_weight=1.3)
    d = decide(c)
    assert d.reason == "trusted_source"


# ── prefilter: precedence ─────────────────────────────────────────


def test_precedence_muted_source_over_trusted():
    mutes = Mutes(sources=frozenset({"blog"}))
    c = make_candidate(
        source_keys=("blog",),
        max_source_weight=1.5,
    )
    d = decide(c, mutes=mutes)
    assert d.reason == "muted_source"


def test_precedence_too_old_over_kev():
    c = make_candidate(
        published=NOW - timedelta(hours=100),
        kev_vendor="Microsoft",
    )
    d = decide(c)
    assert d.reason == "too_old"


def test_precedence_muted_keyword_over_primary():
    mutes = Mutes(keywords=("vnet",))
    c = make_candidate(title="VNet outage")
    d = prefilter(c, FOCUS, mutes, now=NOW, max_age_hours=96)
    assert d.reason == "muted_keyword"


# ── prefilter: partial mute ───────────────────────────────────────


def test_partial_mute_triage():
    mutes = Mutes(sources=frozenset({"a"}))
    c = make_candidate(source_keys=("a", "b"))
    d = decide(c, mutes=mutes)
    assert d.reason == "triage"


def test_both_muted():
    mutes = Mutes(sources=frozenset({"a", "b"}))
    c = make_candidate(source_keys=("a", "b"))
    d = decide(c, mutes=mutes)
    assert d.reason == "muted_source"


# ── prefilter: age boundary ───────────────────────────────────────


def test_age_boundary_exact_kept():
    c = make_candidate(published=NOW - timedelta(hours=96))
    d = decide(c)
    assert d.reason == "triage"
    assert d.keep is True


def test_age_boundary_one_second_too_old():
    c = make_candidate(published=NOW - timedelta(hours=96, seconds=1))
    d = decide(c)
    assert d.reason == "too_old"


def test_undated_too_old():
    c = make_candidate(
        published=None,
        first_seen=NOW - timedelta(hours=100),
    )
    d = decide(c)
    assert d.reason == "too_old"


def test_undated_first_seen_recent():
    c = make_candidate(
        published=None,
        first_seen=NOW - timedelta(hours=1),
    )
    d = decide(c)
    assert d.keep is True


# ── prefilter: hint scores ────────────────────────────────────────


def test_hint_score_triage():
    c = make_candidate(title="Fortinet VPN exploit")
    d = decide(c)
    assert d.reason == "triage"
    assert d.hint_score == 6
    assert d.focus_hits == ("netsec",)


def test_hint_score_primary():
    c = make_candidate(title="VNet outage")
    d = decide(c)
    assert d.reason == "primary_keyword"
    assert d.hint_score == 4
    assert d.focus_hits == ("az", "ind")


def test_hint_score_multi():
    c = make_candidate(title="VNet PIM outage")
    d = decide(c)
    assert d.hint_score == 7


# ── prefilter: dropped decisions carry hint ───────────────────────


def test_dropped_decision_has_hint():
    mutes = Mutes(keywords=("fortinet",))
    c = make_candidate(title="Fortinet thing")
    d = prefilter(c, FOCUS, mutes, now=NOW, max_age_hours=96)
    assert d.reason == "muted_keyword"
    assert d.keep is False
    assert d.hint_score == 2


# ── age_band ──────────────────────────────────────────────────────


def test_age_band_11_9():
    c = make_candidate(published=NOW - timedelta(hours=11.9))
    assert age_band(c, now=NOW) == 2


def test_age_band_12():
    c = make_candidate(published=NOW - timedelta(hours=12))
    assert age_band(c, now=NOW) == 1


def test_age_band_47_9():
    c = make_candidate(published=NOW - timedelta(hours=47.9))
    assert age_band(c, now=NOW) == 1


def test_age_band_48():
    c = make_candidate(published=NOW - timedelta(hours=48))
    assert age_band(c, now=NOW) == 0


# ── order_for_triage ──────────────────────────────────────────────


def test_order_for_triage():
    c1 = make_candidate(
        story_id=1,
        published=NOW - timedelta(hours=1),
        first_seen=NOW - timedelta(hours=1),
    )
    c2 = make_candidate(
        story_id=2,
        published=NOW - timedelta(hours=60),
        first_seen=NOW - timedelta(hours=60),
    )
    c3 = make_candidate(
        story_id=3,
        published=NOW - timedelta(hours=20),
        first_seen=NOW - timedelta(hours=20),
    )
    c4 = make_candidate(
        story_id=4,
        published=NOW - timedelta(hours=60),
        first_seen=NOW - timedelta(hours=60),
    )

    d1 = Decision(True, False, "triage", 6, ())
    d2 = Decision(True, False, "triage", 1, ())
    d3 = Decision(True, False, "triage", 2, ())
    d4 = Decision(True, False, "triage", 4, ())

    pairs = [
        (c1, d1),
        (c2, d2),
        (c3, d3),
        (c4, d4),
    ]
    ordered = order_for_triage(pairs, now=NOW)
    ids = [p[0].story_id for p in ordered]
    assert ids == [4, 2, 3, 1]


def test_order_for_triage_ties():
    c1 = make_candidate(
        story_id=1,
        first_seen=NOW - timedelta(hours=1),
    )
    c2 = make_candidate(
        story_id=2,
        first_seen=NOW - timedelta(hours=1),
    )
    d1 = Decision(True, False, "triage", 3, ())
    d2 = Decision(True, False, "triage", 3, ())

    pairs = [(c2, d2), (c1, d1)]
    ordered = order_for_triage(pairs, now=NOW)
    ids = [p[0].story_id for p in ordered]
    assert ids == [1, 2]


def test_order_for_triage_first_seen_before_story_id():
    older = make_candidate(
        story_id=9, first_seen=NOW - timedelta(hours=2), published=NOW - timedelta(hours=1)
    )
    newer = make_candidate(
        story_id=1, first_seen=NOW - timedelta(hours=1), published=NOW - timedelta(hours=1)
    )
    d = Decision(True, False, "triage", 3, ())
    pairs = [(newer, d), (older, d)]
    ordered = order_for_triage(pairs, now=NOW)
    assert [p[0].story_id for p in ordered] == [9, 1]
    assert [p[0].story_id for p in pairs] == [1, 9]  # new list, input untouched


# ── review additions ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "keyword, title, hit",
    [
        ("sse", "Assessment of SSE", True),
        ("sse", "Assessment", False),
        ("apt", "Aptitude test", False),
        ("apt", "APTs target banks", True),
        ("vnet", "VNetwork", False),
        ("exploit", "Fortinet exploited", True),
        ("exploit", "Unexploitable", False),
        ("conditional access", "conditional-access", False),
    ],
)
def test_keyword_boundaries(keyword, title, hit):
    focus = (FocusArea(key="k", tier="side", keywords=(keyword,)),)
    assert match_keywords(title, focus) == ({"k": 1} if hit else {})


def test_match_keywords_counts_distinct_keywords_once():
    focus = (FocusArea(key="k", tier="side", keywords=("vpn", "vpn", "outage")),)
    assert match_keywords("VPN VPN VPNs outage", focus) == {"k": 2}


def test_precedence_muted_source_over_muted_keyword():
    d = decide(
        make_candidate(title="Free webinar"),
        mutes=Mutes(sources=frozenset({"blog"}), keywords=("webinar",)),
    )
    assert d.reason == "muted_source"


def test_precedence_muted_keyword_over_too_old():
    d = decide(
        make_candidate(title="Free webinar", published=NOW - timedelta(hours=200)),
        mutes=Mutes(keywords=("webinar",)),
    )
    assert d.reason == "muted_keyword"


def test_precedence_kev_over_trusted():
    d = decide(make_candidate(kev_vendor="Microsoft", max_source_weight=1.5))
    assert (d.reason, d.keep, d.always) == ("kev_microsoft", True, True)


def test_precedence_trusted_over_primary():
    d = decide(make_candidate(title="VNet news", max_source_weight=1.3))
    assert (d.reason, d.keep, d.always) == ("trusted_source", True, True)


def test_kev_vendor_case_insensitive():
    assert decide(make_candidate(kev_vendor="MICROSOFT")).reason == "kev_microsoft"


def test_kev_vendor_substring_is_not_microsoft():
    assert decide(make_candidate(kev_vendor="Microsoft Corp")).reason == "triage"


def test_secondary_hit_alone_is_triage():
    d = decide(make_candidate(title="Fortinet patch"))
    assert (d.reason, d.keep, d.always, d.hint_score) == ("triage", True, False, 2)


def test_no_source_keys_is_not_muted():
    d = decide(make_candidate(source_keys=()), mutes=Mutes(sources=frozenset({"blog"})))
    assert d.reason == "triage"


def test_published_preferred_over_first_seen():
    c = make_candidate(published=NOW - timedelta(hours=1), first_seen=NOW - timedelta(hours=200))
    assert decide(c).reason == "triage"
    assert age_band(c, now=NOW) == 2


def test_dropped_muted_source_and_too_old_carry_hint():
    d = decide(make_candidate(title="Fortinet"), mutes=Mutes(sources=frozenset({"blog"})))
    assert (d.reason, d.keep, d.always, d.hint_score, d.focus_hits) == (
        "muted_source",
        False,
        False,
        2,
        ("netsec",),
    )
    d = decide(make_candidate(title="VNet outage", published=NOW - timedelta(hours=200)))
    assert (d.reason, d.keep, d.hint_score, d.focus_hits) == ("too_old", False, 4, ("az", "ind"))


def test_max_age_hours_is_passed_through():
    c = make_candidate(published=NOW - timedelta(hours=30))
    assert decide(c, max_age_hours=24).reason == "too_old"
    assert decide(c, max_age_hours=48).reason == "triage"


def test_age_band_future_is_newest():
    assert age_band(make_candidate(published=NOW + timedelta(hours=5)), now=NOW) == 2

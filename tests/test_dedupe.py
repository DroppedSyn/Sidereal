"""Tests for sidereal.pipeline.dedupe (plan §6.7)."""

from datetime import UTC, date, datetime, timedelta, timezone

from sidereal.pipeline.dedupe import (
    Assignment,
    KnownStory,
    NewItem,
    assign_stories,
    jaccard,
    normalize_title,
    rollup_title,
    title_tokens,
)

PT = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)
ENTRA_A = "Microsoft patches exploited Entra ID flaw CVE-2026-21001"
ENTRA_B = "Microsoft patches actively exploited Entra ID flaw (CVE-2026-21001)"
LONG_T = "Azure Front Door outage hits Europe West"
MSRC_TITLES = [
    "Windows Kernel elevation of privilege vulnerability",
    "Exchange Server remote code execution flaw",
    "SharePoint spoofing issue fixed today",
    "Hyper-V denial service bug patched",
    "Office macro bypass gets security fix",
    "Edge Chromium memory corruption repaired",
    "Teams client information disclosure closed",
]


def item(key, title, **kw):
    return NewItem(
        key=key,
        source_key=kw.pop("source_key", "src"),
        guid=kw.pop("guid", f"g{key}"),
        canonical_url=kw.pop("canonical_url", f"https://example.com/{key}"),
        title=title,
        **kw,
    )


def story(sid, *titles, cves=()):
    return KnownStory(sid, tuple(normalize_title(t) for t in titles), tuple(cves))


def msrc(key, *, published=PT, cve=None):
    return item(
        key,
        MSRC_TITLES[key],
        is_msrc=True,
        published=published,
        cve_ids=(cve or f"CVE-2026-{20001 + key}",),
    )


def toks(title):
    return title_tokens(normalize_title(title))


# ── normalize_title / jaccard ──────────────────────────────────────────────


def test_normalize_title_examples():
    assert (
        normalize_title("Microsoft's “Patch Tuesday”: 3 Zero-Days!")
        == "microsoft patch tuesday 3 zero day"
    )
    assert normalize_title("The Access Process Changes") == "access process change"
    assert normalize_title("Ｆｕｌｌ-width CVEs fixed") == "full width cve fixed"
    assert normalize_title("News: Azure is down") == "new azure down"


def test_normalize_title_curly_apostrophe_and_short_s():
    assert normalize_title("Microsoft’s bus has gas") == "microsoft bus gas"


def test_jaccard_values():
    assert jaccard(frozenset("abc"), frozenset("abd")) == 0.5
    assert jaccard(frozenset(), frozenset()) == 0.0


def test_rollup_title_format():
    assert (
        rollup_title(date(2026, 11, 10), 57) == "Microsoft security updates: 2026-11-10 (57 CVEs)"
    )


# ── plan §6.7 pitfall tests ────────────────────────────────────────────────


def test_similar_feature_titles_not_merged():
    a = "Azure Firewall now supports TLS inspection for outbound traffic"
    b = "Azure Firewall now supports IDPS signature rules for outbound traffic"
    assert jaccard(toks(a), toks(b)) == 6 / 11
    assert assign_stories([item(0, b)], [story(1, a)]) == [Assignment(0, "new", new_group=0)]


def test_same_story_two_outlets_merged():
    assert jaccard(toks(ENTRA_A), toks(ENTRA_B)) == 0.9
    res = assign_stories([item(0, ENTRA_B, source_key="bleeping")], [story(5, ENTRA_A)])
    assert res == [Assignment(0, "existing", story_id=5)]


def test_patch_tuesday_rollup_does_not_absorb_unrelated_cve_story():
    known = [
        story(
            9,
            "Microsoft security updates: 2026-11-10 (6 CVEs)",
            cves=tuple(f"CVE-2026-{n}" for n in range(1001, 1007)),
        )
    ]
    exch = "Exchange Server zero-day exploited in the wild"
    res = assign_stories([item(0, exch, cve_ids=("CVE-2026-1003",))], known)
    assert res == [Assignment(0, "new", new_group=0)]

    batch = [msrc(k, cve=f"CVE-2026-{1001 + k}") for k in range(5)]
    batch.append(item(5, exch, cve_ids=("CVE-2026-1003",)))
    res = assign_stories(batch, [])
    day = date(2026, 11, 10)
    assert res[:5] == [Assignment(k, "new", new_group=0, rollup_date=day) for k in range(5)]
    assert res[5] == Assignment(5, "new", new_group=1)


# ── duplicates ─────────────────────────────────────────────────────────────


def test_duplicate_by_url():
    res = assign_stories([item(0, LONG_T)], [], known_urls={"https://example.com/0"})
    assert res == [Assignment(0, "duplicate")]


def test_duplicate_by_guid():
    it = item(0, LONG_T, canonical_url="https://example.com/other")
    assert assign_stories([it], [], known_guids={("src", "g0")}) == [Assignment(0, "duplicate")]


def test_guid_from_other_source_not_duplicate():
    it = item(0, LONG_T, source_key="other")
    res = assign_stories([it], [], known_guids={("src", "g0")})
    assert res == [Assignment(0, "new", new_group=0)]


def test_duplicate_within_batch():
    items = [
        item(0, LONG_T),
        item(1, "Printer spooler crash fixed overnight", canonical_url="https://example.com/0"),
        item(2, "Kubernetes ingress controller bug found", guid="g0"),
        item(3, "Teams meeting recordings vanish again", guid=None),
        item(4, "Defender quarantine false positive wave", guid=None),
    ]
    assert assign_stories(items, []) == [
        Assignment(0, "new", new_group=0),
        Assignment(1, "duplicate"),
        Assignment(2, "duplicate"),
        Assignment(3, "new", new_group=1),
        Assignment(4, "new", new_group=2),
    ]


def test_none_guid_never_matches_known():
    it = item(0, LONG_T, guid=None)
    res = assign_stories([it], [], known_guids={("src", None)})
    assert res == [Assignment(0, "new", new_group=0)]


# ── CVE rule ───────────────────────────────────────────────────────────────


def test_cve_join():
    known = [story(10, "Something about printers", cves=("CVE-2026-21001",))]
    res = assign_stories([item(0, LONG_T, cve_ids=("CVE-2026-21001",))], known)
    assert res == [Assignment(0, "existing", story_id=10)]


def test_cve_beats_title():
    known = [
        story(11, LONG_T),
        story(10, "Something about printers", cves=("CVE-2026-21001",)),
        story(9, LONG_T),
    ]
    res = assign_stories([item(0, LONG_T, cve_ids=("CVE-2026-21001",))], known)
    assert res == [Assignment(0, "existing", story_id=10)]


def test_cve_rule_skipped_for_story_with_4_cves():
    known = [story(10, "Printers", cves=tuple(f"CVE-2026-{n}" for n in range(1001, 1005)))]
    res = assign_stories([item(0, LONG_T, cve_ids=("CVE-2026-1001",))], known)
    assert res == [Assignment(0, "new", new_group=0)]


def test_cve_rule_applies_with_3_cves():
    known = [story(10, "Printers", cves=tuple(f"CVE-2026-{n}" for n in range(1001, 1004)))]
    res = assign_stories([item(0, LONG_T, cve_ids=("CVE-2026-1001",))], known)
    assert res == [Assignment(0, "existing", story_id=10)]


def test_cve_match_lowest_story_id():
    known = [story(8, "Printers", cves=("CVE-1",)), story(4, "Scanners", cves=("CVE-1",))]
    res = assign_stories([item(0, LONG_T, cve_ids=("CVE-1",))], known)
    assert res == [Assignment(0, "existing", story_id=4)]


# ── title rule ─────────────────────────────────────────────────────────────


def test_short_titles_never_title_merged():
    res = assign_stories([item(0, "Azure outage today")], [story(1, "Azure outage today")])
    assert res == [Assignment(0, "new", new_group=0)]


def test_short_story_title_norm_ignored():
    # item has 4 tokens; the story's only title has 3 (a subset → Jaccard 0.75)
    res = assign_stories([item(0, "Azure outage today Europe")], [story(1, "Azure outage today")])
    assert res == [Assignment(0, "new", new_group=0)]


def test_short_item_title_never_title_merged():
    # item has 3 tokens; the story's title has 4 (a superset → Jaccard 0.75)
    res = assign_stories([item(0, "Azure outage today")], [story(1, "Azure outage today Europe")])
    assert res == [Assignment(0, "new", new_group=0)]


def test_four_tokens_enough():
    res = assign_stories(
        [item(0, "Azure outage today Europe")], [story(1, "Azure outage today Europe")]
    )
    assert res == [Assignment(0, "existing", story_id=1)]


def test_threshold_exactly_0_6_merges():
    res = assign_stories(
        [item(0, "alpha bravo charlie echo")], [story(1, "alpha bravo charlie delta")]
    )
    assert res == [Assignment(0, "existing", story_id=1)]


def test_threshold_just_below_not_merged():
    a = "alpha bravo charlie delta echo foxtrot golf hotel india"
    b = "alpha bravo charlie delta echo foxtrot golf kilo lima mike"
    assert jaccard(toks(a), toks(b)) == 7 / 12
    assert assign_stories([item(0, b)], [story(1, a)]) == [Assignment(0, "new", new_group=0)]


def test_stop_words_removed_before_jaccard():
    # without stop-word removal: 5/9 ≈ 0.556; with it: 5/5
    res = assign_stories(
        [item(0, "Azure outage is hitting the Europe region")],
        [story(1, "Azure outage of a Europe region hitting")],
    )
    assert res == [Assignment(0, "existing", story_id=1)]


def test_best_title_score_wins():
    known = [
        story(1, "alpha bravo charlie delta"),  # 0.6 vs the item
        story(2, "zulu", "alpha bravo charlie echo"),  # 1.0 via its second title
    ]
    res = assign_stories([item(0, "alpha bravo charlie echo")], known)
    assert res == [Assignment(0, "existing", story_id=2)]


def test_tie_break_lowest_story_id():
    res = assign_stories([item(0, LONG_T)], [story(7, LONG_T), story(3, LONG_T)])
    assert res == [Assignment(0, "existing", story_id=3)]


# ── within-batch grouping ──────────────────────────────────────────────────


def test_within_batch_grouping():
    items = [
        item(0, ENTRA_A, source_key="outlet-a"),
        item(1, LONG_T),
        item(2, ENTRA_B, source_key="outlet-b"),
    ]
    assert assign_stories(items, []) == [
        Assignment(0, "new", new_group=0),
        Assignment(1, "new", new_group=1),
        Assignment(2, "new", new_group=0),
    ]


def test_group_grows_with_joined_titles_and_cves():
    items = [
        item(0, LONG_T),
        item(1, "Printer driver flaw lets attackers escalate", cve_ids=("CVE-9",)),
        # title vs item 1: 6/8 → group 1, brings CVE-8
        item(2, "Printer driver flaw lets attackers escalate quickly now", cve_ids=("CVE-8",)),
        # title vs item 1: 5/9 (no), vs item 2: 7/9 → group 1 only via item 2's title
        item(3, "Driver flaw lets attackers escalate quickly now remotely"),
        # CVE-8 came from item 2, not from the group's first item
        item(4, "Totally different headline words", cve_ids=("CVE-8",)),
    ]
    assert [a.new_group for a in assign_stories(items, [])] == [0, 1, 1, 1, 1]


def test_batch_group_cve_rule_respects_limit():
    items = [
        item(0, "First headline words here", cve_ids=("CVE-1", "CVE-2", "CVE-3", "CVE-4")),
        item(1, "Second headline different entirely", cve_ids=("CVE-1",)),
    ]
    assert [a.new_group for a in assign_stories(items, [])] == [0, 1]


def test_known_story_beats_batch_group():
    items = [item(0, LONG_T), item(1, LONG_T + " today")]
    res = assign_stories(items, [story(4, LONG_T + " today")])
    assert res == [Assignment(0, "existing", story_id=4), Assignment(1, "existing", story_id=4)]


# ── MSRC roll-up ───────────────────────────────────────────────────────────


def test_msrc_rollup_five_items():
    items = [msrc(k) for k in range(4)]
    items.append(
        msrc(4, published=datetime(2026, 11, 11, 1, 0, tzinfo=timezone(timedelta(hours=5))))
    )
    day = date(2026, 11, 10)
    assert assign_stories(items, []) == [
        Assignment(k, "new", new_group=0, rollup_date=day) for k in range(5)
    ]


def test_msrc_four_items_no_rollup():
    items = [msrc(k) for k in range(4)]
    res = assign_stories(items, [])
    assert res == [Assignment(k, "new", new_group=k) for k in range(4)]


def test_msrc_duplicates_do_not_count_toward_rollup():
    items = [msrc(k) for k in range(5)]
    res = assign_stories(items, [], known_urls={"https://example.com/4"})
    assert res[4] == Assignment(4, "duplicate")
    assert [a.rollup_date for a in res[:4]] == [None] * 4


def test_msrc_other_day_or_undated_not_in_rollup():
    items = [msrc(k) for k in range(5)]
    items.append(msrc(5, published=PT + timedelta(days=1)))
    items.append(msrc(6, published=None))
    res = assign_stories(items, [])
    assert res[5] == Assignment(5, "new", new_group=1)
    assert res[6] == Assignment(6, "new", new_group=2)


def test_rollup_skips_known_story_rules():
    known = [story(3, "Printers", cves=("CVE-2026-20001",))]
    res = assign_stories([msrc(k) for k in range(5)], known)
    assert res[0] == Assignment(0, "new", new_group=0, rollup_date=date(2026, 11, 10))


def test_rollup_group_closed_to_other_items():
    items = [msrc(k) for k in range(5)]
    same_title = items[0].title
    items.append(item(5, same_title, cve_ids=items[1].cve_ids))
    res = assign_stories(items, [])
    assert res[5] == Assignment(5, "new", new_group=1)


def test_rollup_group_number_in_input_order():
    items = [item(0, LONG_T), *[msrc(k) for k in range(1, 6)], item(6, ENTRA_A)]
    day = date(2026, 11, 10)
    assert assign_stories(items, []) == [
        Assignment(0, "new", new_group=0),
        *[Assignment(k, "new", new_group=1, rollup_date=day) for k in range(1, 6)],
        Assignment(6, "new", new_group=2),
    ]


# ── determinism ────────────────────────────────────────────────────────────


def test_deterministic():
    known = [
        story(5, ENTRA_A),
        story(2, ENTRA_A),
        story(9, "Printers", cves=("CVE-7",)),
        story(1, "Scanners", cves=("CVE-7",)),
    ]
    items = [item(0, ENTRA_B), item(1, LONG_T, cve_ids=("CVE-7",)), item(2, LONG_T)]
    res = assign_stories(items, known)
    assert res == [
        Assignment(0, "existing", story_id=2),
        Assignment(1, "existing", story_id=1),
        Assignment(2, "new", new_group=0),
    ]
    assert assign_stories(items, known) == res
    assert assign_stories(items, list(reversed(known))) == res

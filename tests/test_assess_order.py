"""Assess queue order (post-M14): triage relevance first, then the §7.2 age-band order."""

from __future__ import annotations

from datetime import timedelta

import pytest

from sidereal.db import stories_repo
from sidereal.pipeline import assess_step
from sidereal.pipeline.common import Deadline
from sidereal.pipeline.prefilter import Candidate, Decision
from tests.pipeline_helpers import (
    NOW,
    FeedServer,
    ollama_for,
    seeded_db,
    smart_ollama,
    start,
    state_of,
)
from tests.pipeline_helpers import add_story as _add

PLAIN = "Local bakery wins regional bread award again"  # no focus keyword: goes to triage


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def add(conn, **kw):
    return _add(conn, start(conn), **kw)


async def run(conn, settings, fake, max_assess):
    return await assess_step.run_assess(
        conn, ollama_for(fake, settings), FeedServer(conn).fetcher(), settings, now=NOW,
        deadline=Deadline(None), max_assess=max_assess)


def pair(sid, *, hours, always=False, hint=0):
    c = Candidate(story_id=sid, title="t", source_keys=("x",), max_source_weight=1.0,
                  published=NOW - timedelta(hours=hours), first_seen=NOW)
    return c, Decision(keep=True, always=always, reason="trusted_source" if always else "triage",
                       hint_score=hint, focus_hits={})


async def test_relevance_3_beats_older_relevance_2_under_the_cap(settings, conn):
    old2 = add(conn, title=PLAIN, published=NOW - timedelta(hours=60))
    new3 = add(conn, title=PLAIN + " fresh", published=NOW - timedelta(hours=1))
    fake = smart_ollama(triage_relevance=lambda i: 3 if i == new3 else 2)
    res = await run(conn, settings, fake, max_assess=1)
    assert state_of(conn, new3) == "assessed"
    assert state_of(conn, old2) == "new"
    assert stories_repo.get_story(conn, old2).triage_relevance == 2
    assert res.stats["assess"]["deferred"] == 1


async def test_pretriaged_relevance_counts_too(settings, conn):
    old2 = add(conn, title=PLAIN, published=NOW - timedelta(hours=60))
    new3 = add(conn, title=PLAIN + " fresh", published=NOW - timedelta(hours=1))
    stories_repo.set_triage(conn, old2, 2)
    stories_repo.set_triage(conn, new3, 3)
    await run(conn, settings, smart_ollama(), max_assess=1)
    assert (state_of(conn, new3), state_of(conn, old2)) == ("assessed", "new")


async def test_always_keep_counts_as_relevance_3(settings, conn):
    plain3 = add(conn, title=PLAIN, published=NOW - timedelta(hours=60))
    trusted = add(conn, source="tc-entra", title=PLAIN + " trusted",
                  published=NOW - timedelta(hours=1))
    plain2 = add(conn, title=PLAIN + " two", published=NOW - timedelta(hours=60))
    fake = smart_ollama(triage_relevance=lambda i: 3 if i == plain3 else 2)
    await run(conn, settings, fake, max_assess=2)
    # relevance 3 for both: the older age band goes first; the older relevance 2 waits
    assert state_of(conn, plain3) == state_of(conn, trusted) == "assessed"
    assert state_of(conn, plain2) == "new"


def test_assess_order_relevance_then_band_then_hint():
    pairs = [pair(1, hours=60), pair(2, hours=1), pair(3, hours=1, always=True),
             pair(4, hours=30), pair(5, hours=1, hint=5), pair(6, hours=60, hint=2)]
    rel = {1: 2, 2: 3, 4: 3, 5: 3, 6: 2}
    assert assess_step.assess_order(pairs, rel, now=NOW) == [4, 5, 2, 3, 6, 1]


def test_assess_order_leaves_input_untouched():
    pairs = [pair(1, hours=1), pair(2, hours=60)]
    before = list(pairs)
    assess_step.assess_order(pairs, {1: 3, 2: 2}, now=NOW)
    assert pairs == before

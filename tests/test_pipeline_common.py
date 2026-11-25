"""pipeline/common.py (M13b): Deadline, short_error, story bundles."""

from __future__ import annotations

from datetime import timedelta

from sidereal.db import items_repo, sources_repo, stories_repo
from sidereal.pipeline.common import Deadline, bundle, short_error
from tests.pipeline_helpers import NOW, FakeClock, add_story, seeded_db, start


def test_deadline_expires_at_the_boundary_and_stays_hit():
    clock = FakeClock()
    d = Deadline(10, clock=clock)
    clock.t += 9.9
    assert d() is False and d.hit is False
    clock.t += 0.1
    assert d() is True and d.hit is True
    clock.t -= 100
    assert d() is True


def test_deadline_none_never_expires():
    clock = FakeClock()
    d = Deadline(None, clock=clock)
    clock.t += 1e9
    assert d() is False


def test_short_error_type_and_cut():
    assert short_error(ValueError("bad")) == "ValueError: bad"
    long = short_error(RuntimeError("x" * 500))
    assert len(long) == 200 and long.endswith("…") and long.startswith("RuntimeError: x")


def test_bundle_lead_sources_and_dates(settings):
    conn = seeded_db(settings)
    run = start(conn)
    sid = add_story(conn, run, source="krebs", extra_sources=("tc-entra", "krebs"),
                    published=NOW - timedelta(hours=3))
    sources = {s.id: s for s in sources_repo.list_sources(conn)}
    b = bundle(conn, stories_repo.get_story(conn, sid), sources)
    assert b.source_keys == ("krebs", "tc-entra") and b.source_weights == (0.9, 1.4)
    assert b.lead.id == b.items[0].id and len(b.items) == 3
    assert b.published == NOW - timedelta(hours=3) and b.first_seen == NOW
    undated = add_story(conn, run, title="Another one entirely")
    assert bundle(conn, stories_repo.get_story(conn, undated), sources).published is None
    empty = stories_repo.create_story(conn, title="t", day="2026-11-25", first_seen_at=NOW,
                                      first_run_id=run)
    eb = bundle(conn, stories_repo.get_story(conn, empty), sources)
    assert eb.lead is None and eb.sources == [] and items_repo.items_for_story(conn, empty) == []

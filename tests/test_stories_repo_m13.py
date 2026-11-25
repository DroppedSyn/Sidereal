"""stories_repo additions for the runner (M13b): ``merge_flags``, ``scored_stories``."""

from __future__ import annotations

import pytest

from sidereal.db import stories_repo
from tests.pipeline_helpers import add_story, seeded_db, start


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def test_merge_flags_overwrites_given_keys_only(conn):
    sid = add_story(conn, start(conn), flags={"kev": True, "cvss": 7.5})
    stories_repo.merge_flags(conn, sid, {"cvss": 9.8, "exploited": True})
    assert stories_repo.get_story(conn, sid).flags == {"kev": True, "cvss": 9.8,
                                                       "exploited": True}
    conn.rollback()  # committed by the repo itself
    assert stories_repo.get_story(conn, sid).flags["exploited"] is True


def test_merge_flags_unknown_story(conn):
    with pytest.raises(KeyError):
        stories_repo.merge_flags(conn, 999, {"kev": True})


def test_scored_stories_by_state_and_day(conn):
    run = start(conn)
    a = add_story(conn, run, day="2026-11-24")
    b = add_story(conn, run, day="2026-11-25")
    c = add_story(conn, run, day="2026-11-25")
    add_story(conn, run, day="2026-11-25")  # new
    stories_repo.set_state(conn, a, "assessed")
    stories_repo.set_state(conn, b, "assess_failed")
    stories_repo.set_state(conn, c, "triaged_out")
    assert [s.id for s in stories_repo.scored_stories(conn)] == [a, b]
    assert [s.id for s in stories_repo.scored_stories(conn, day="2026-11-25")] == [b]
    assert stories_repo.scored_stories(conn, day="2026-01-01") == []

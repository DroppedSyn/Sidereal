"""Tests for ``db/feedback_repo.py`` (M24a-1)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from sidereal.db import stories_repo
from sidereal.db.connect import connect
from sidereal.db.feedback_repo import (
    NO_FEEDBACK,
    StoryFeedback,
    VotedStory,
    add_mute,
    get_feedback,
    list_mutes,
    mark_day_read,
    muted_values,
    remove_mute,
    set_hidden,
    set_read,
    set_vote,
    story_feedback,
    voted_stories,
)
from tests.factories import make_run, make_story

T0 = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)


@pytest.fixture
def run(db: sqlite3.Connection) -> int:
    return make_run(db, at=T0)


def story(db: sqlite3.Connection, run: int, **kw) -> int:
    kw.setdefault("first_seen", T0)
    return make_story(db, run_id=run, tz="UTC", **kw)


def count(db: sqlite3.Connection, sid: int | None = None) -> int:
    if sid is None:
        return db.execute("SELECT count(*) FROM feedback").fetchone()[0]
    return db.execute("SELECT count(*) FROM feedback WHERE story_id = ?", (sid,)).fetchone()[0]


def stored_at(db: sqlite3.Connection, sid: int, kind: str) -> str:
    return db.execute("SELECT at FROM feedback WHERE story_id = ? AND kind = ?",
                      (sid, kind)).fetchone()[0]


def test_migration_creates_tables(db):
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"feedback", "mutes"} <= names


@pytest.mark.parametrize("sql, params", [
    ("INSERT INTO feedback (story_id, kind, at) VALUES (?, 'like', 'x')", "story"),
    ("INSERT INTO feedback (story_id, kind, at) VALUES (?, 'read', 'x')", "missing"),
    ("INSERT INTO mutes (kind, value, created_at) VALUES ('tag', 'x', 'x')", None),
])
def test_schema_constraints(db, run, sql, params):
    sid = story(db, run)
    args = () if params is None else ((sid if params == "story" else 999),)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK|FOREIGN KEY"):
        db.execute(sql, args)
    db.rollback()


def test_no_feedback_default(db, run):
    sid = story(db, run)
    assert get_feedback(db, sid) == NO_FEEDBACK


def test_vote_up_then_down_replaces(db, run):
    sid = story(db, run)
    set_vote(db, sid, "up", at=T0)
    set_vote(db, sid, "down", at=T1)
    assert get_feedback(db, sid).vote == "down"
    assert count(db, sid) == 1


def test_vote_none_clears(db, run):
    sid = story(db, run)
    set_vote(db, sid, "up", at=T0)
    set_vote(db, sid, None, at=T1)
    assert get_feedback(db, sid).vote is None
    assert count(db, sid) == 0


def test_same_vote_refreshes_at(db, run):
    sid = story(db, run)
    set_vote(db, sid, "up", at=T0)
    set_vote(db, sid, "up", at=T1)
    assert stored_at(db, sid, "up") == "2026-07-14T09:00:00Z"
    assert count(db, sid) == 1


def test_vote_keeps_read_and_hidden(db, run):
    sid = story(db, run)
    set_read(db, sid, True, at=T0)
    set_hidden(db, sid, True, at=T0)
    set_vote(db, sid, "up", at=T0)
    set_vote(db, sid, "down", at=T1)
    assert get_feedback(db, sid) == StoryFeedback("down", True, True)
    set_vote(db, sid, None, at=T1)
    assert get_feedback(db, sid) == StoryFeedback(None, True, True)


@pytest.mark.parametrize("vote", ["meh", "read", "UP"])
def test_invalid_vote(db, run, vote):
    sid = story(db, run)
    with pytest.raises(ValueError, match="invalid vote"):
        set_vote(db, sid, vote, at=T0)
    assert count(db, sid) == 0


@pytest.mark.parametrize("write", [
    lambda db: set_vote(db, 999, "up", at=T0),
    lambda db: set_read(db, 999, True, at=T0),
    lambda db: set_hidden(db, 999, True, at=T0),
])
def test_unknown_story_raises_keyerror(db, write):
    with pytest.raises(KeyError, match="999"):
        write(db)
    assert count(db) == 0


def test_read_keeps_first_time(db, run):
    sid = story(db, run)
    set_read(db, sid, True, at=T0)
    set_read(db, sid, True, at=T1)
    assert stored_at(db, sid, "read") == "2026-07-14T08:00:00Z"


def test_hidden_keeps_first_time(db, run):
    sid = story(db, run)
    set_hidden(db, sid, True, at=T0)
    set_hidden(db, sid, True, at=T1)
    assert stored_at(db, sid, "hide") == "2026-07-14T08:00:00Z"


def test_unread(db, run):
    sid = story(db, run)
    set_read(db, sid, True, at=T0)
    set_hidden(db, sid, True, at=T0)
    set_read(db, sid, False, at=T1)
    assert get_feedback(db, sid) == StoryFeedback(None, False, True)


def test_hidden_toggle(db, run):
    sid = story(db, run)
    set_read(db, sid, True, at=T0)
    set_hidden(db, sid, True, at=T0)
    assert get_feedback(db, sid).hidden is True
    set_hidden(db, sid, False, at=T1)
    assert get_feedback(db, sid) == StoryFeedback(None, True, False)


def test_mark_day_read_counts_new_only(db, run):
    top = story(db, run, bucket="top")
    rel = story(db, run, bucket="relevant")
    side = story(db, run, bucket="side")
    drop = story(db, run, bucket="drop")
    filtered = story(db, run, bucket=None, state="filtered")
    other = story(db, run, bucket="side", first_seen=T0 + timedelta(days=1))
    set_read(db, rel, True, at=T0)
    assert mark_day_read(db, "2026-07-14", at=T1) == 2
    fb = story_feedback(db, [top, rel, side, drop, filtered, other])
    assert [fb[s].read for s in (top, rel, side)] == [True, True, True]
    assert [fb[s].read for s in (drop, filtered, other)] == [False, False, False]
    assert stored_at(db, rel, "read") == "2026-07-14T08:00:00Z"
    assert stored_at(db, top, "read") == "2026-07-14T09:00:00Z"


def test_mark_day_read_unknown_day(db, run):
    story(db, run, bucket="top")
    assert mark_day_read(db, "2026-01-01", at=T1) == 0
    assert count(db) == 0


def test_story_feedback_bulk(db, run):
    a, b, c = (story(db, run) for _ in range(3))
    set_vote(db, a, "up", at=T0)
    set_read(db, b, True, at=T0)
    set_hidden(db, b, True, at=T0)
    assert story_feedback(db, [a, b, c, 999]) == {
        a: StoryFeedback("up", False, False), b: StoryFeedback(None, True, True),
        c: NO_FEEDBACK, 999: NO_FEEDBACK,
    }
    statements: list[str] = []
    db.set_trace_callback(statements.append)
    assert story_feedback(db, []) == {}
    db.set_trace_callback(None)
    assert statements == []


def test_voted_stories_context(db, run):
    a = story(db, run, sources=("bleepingcomputer", "msrc-blog", "bleepingcomputer2"),
              focus="entra", tags=("entra", "mfa"))
    b = story(db, run, state="filtered", bucket=None)
    c = story(db, run)
    # a second item from the same source must not repeat its key
    d = story(db, run, sources=("hn", "hn"), focus="industry", tags=("z", "a"))
    set_vote(db, a, "up", at=T0)
    set_vote(db, b, "down", at=T0)
    set_read(db, c, True, at=T0)
    set_vote(db, d, "down", at=T0)
    assert voted_stories(db) == [
        VotedStory(a, "up", ("bleepingcomputer", "bleepingcomputer2", "msrc-blog"),
                   "entra", ("entra", "mfa")),
        VotedStory(b, "down", ("bleepingcomputer",), None, ()),
        VotedStory(d, "down", ("hn",), "industry", ("z", "a")),
    ]


def test_voted_stories_order_by_id(db, run):
    a, b = story(db, run), story(db, run)
    set_vote(db, b, "up", at=T0)
    set_vote(db, a, "down", at=T1)
    assert [v.story_id for v in voted_stories(db)] == [a, b]


def test_voted_stories_non_string_focus(db, run):
    sid = story(db, run)
    set_vote(db, sid, "up", at=T0)
    db.execute("UPDATE assessments SET raw_json = ? WHERE story_id = ?",
               (json.dumps({"focus": 3}), sid))
    db.commit()
    assert voted_stories(db)[0].focus is None


def test_feedback_deleted_with_story(db, run):
    sid = story(db, run, bucket="drop")
    set_vote(db, sid, "up", at=T0)
    set_read(db, sid, True, at=T0)
    assert stories_repo.delete_dropped_before(db, before=T1) == 1
    assert count(db) == 0


def test_add_mute_normalises(db):
    m = add_mute(db, "keyword", "  Bitcoin   Price ", at=T0)
    assert m.value == "bitcoin price"
    assert m.kind == "keyword"
    assert m.created_at == "2026-07-14T08:00:00Z"
    assert add_mute(db, "source", " HackerNews ", at=T0).value == "HackerNews"


def test_add_mute_idempotent(db):
    first = add_mute(db, "keyword", "bitcoin", at=T0)
    second = add_mute(db, "keyword", "BITCOIN", at=T1)
    assert second.id == first.id
    assert second.created_at == "2026-07-14T08:00:00Z"
    assert len(list_mutes(db)) == 1


def test_same_value_different_kinds(db):
    add_mute(db, "keyword", "hn", at=T0)
    add_mute(db, "source", "hn", at=T0)
    assert len(list_mutes(db)) == 2


@pytest.mark.parametrize("kind, value, message", [
    ("tag", "x", "invalid mute kind"),
    ("keyword", "   ", "must not be empty"),
    ("source", "x" * 201, "longer than 200"),
])
def test_add_mute_invalid(db, kind, value, message):
    with pytest.raises(ValueError, match=message):
        add_mute(db, kind, value, at=T0)
    assert list_mutes(db) == []


def test_add_mute_max_len_ok(db):
    assert add_mute(db, "source", "x" * 200, at=T0).value == "x" * 200


def test_list_mutes_order(db):
    for kind, value in (("keyword", "zeta"), ("source", "b"), ("keyword", "alpha"),
                        ("source", "a")):
        add_mute(db, kind, value, at=T0)
    assert [(m.kind, m.value) for m in list_mutes(db)] == [
        ("keyword", "alpha"), ("keyword", "zeta"), ("source", "a"), ("source", "b")]


def test_remove_mute(db):
    keep = add_mute(db, "keyword", "keep", at=T0)
    m = add_mute(db, "keyword", "gone", at=T0)
    assert remove_mute(db, m.id) is True
    assert list_mutes(db) == [keep]
    assert remove_mute(db, m.id) is False


def test_muted_values(db):
    assert muted_values(db) == (frozenset(), ())
    for kind, value in (("source", "hn"), ("keyword", "zeta"), ("source", "bc"),
                        ("keyword", "alpha")):
        add_mute(db, kind, value, at=T0)
    assert muted_values(db) == (frozenset({"hn", "bc"}), ("alpha", "zeta"))


def test_writes_commit(db, run, settings):
    sid = story(db, run, bucket="top")
    other = connect(settings.db_path)
    try:
        set_vote(db, sid, "up", at=T0)
        assert db.in_transaction is False
        assert other.execute("SELECT kind FROM feedback WHERE story_id = ?",
                             (sid,)).fetchone()[0] == "up"
        set_read(db, sid, True, at=T0)
        assert db.in_transaction is False
        set_read(db, sid, False, at=T0)
        assert db.in_transaction is False
        set_hidden(db, sid, True, at=T0)
        assert db.in_transaction is False
        assert mark_day_read(db, "2026-07-14", at=T0) == 1
        assert db.in_transaction is False
        m = add_mute(db, "keyword", "x", at=T0)
        assert db.in_transaction is False
        assert remove_mute(db, m.id) is True
        assert db.in_transaction is False
        assert other.execute("SELECT count(*) FROM feedback").fetchone()[0] == 3
    finally:
        other.close()

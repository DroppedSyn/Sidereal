"""M24 in the read side: hidden stories leave the Gazette and Daily views (and the day-list
counts); Story responses carry vote/read/hidden."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.deps import get_now
from sidereal.api.present import build_sections
from sidereal.bootstrap import migrate
from sidereal.config import ScoringSettings
from sidereal.db import feedback_repo, views_repo
from sidereal.db.connect import connect
from sidereal.db.feedback_repo import StoryFeedback
from tests.factories import make_run, make_story

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
DAY = "2026-07-14"


@pytest.fixture
def conn(settings):
    migrate(settings)
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def client(settings, tmp_path, conn):
    dist = tmp_path / "dist"
    dist.mkdir()
    app = create_app(settings, dist_dir=dist)
    app.dependency_overrides[get_now] = lambda: NOW
    return TestClient(app, base_url="http://testserver:8470")


def story(conn, bucket="top", title="Story"):
    run = make_run(conn, at=NOW - timedelta(hours=2))
    return make_story(conn, run_id=run, first_seen=NOW - timedelta(hours=1), tz="UTC",
                      bucket=bucket, title=title)


def ids(sections):
    return {s["id"] for name in ("top", "relevant", "side", "drop") for s in sections[name]}


def test_repo_views_skip_hidden(conn):
    keep, gone = story(conn), story(conn)
    feedback_repo.set_hidden(conn, gone, True, at=NOW)
    assert [v.id for v in views_repo.gazette_views(conn, since=NOW - timedelta(days=1))] == [keep]
    assert [v.id for v in views_repo.day_views(conn, DAY)] == [keep]
    feedback_repo.set_hidden(conn, gone, False, at=NOW)
    assert [v.id for v in views_repo.day_views(conn, DAY)] == [keep, gone]


def test_day_summary_counts_skip_hidden(conn):
    story(conn, "top")
    hidden = story(conn, "relevant")
    feedback_repo.set_hidden(conn, hidden, True, at=NOW)
    [row] = views_repo.day_summaries(conn)
    assert (row.day, row.top, row.relevant) == (DAY, 1, 0)


def test_read_and_other_feedback_do_not_hide(conn):
    sid = story(conn)
    feedback_repo.set_read(conn, sid, True, at=NOW)
    feedback_repo.set_vote(conn, sid, "down", at=NOW)
    assert [v.id for v in views_repo.day_views(conn, DAY)] == [sid]


def test_gazette_and_day_leave_hidden_out(client, conn):
    keep = story(conn, "top")
    gone = story(conn, "top")
    dropped = story(conn, "drop")
    feedback_repo.set_hidden(conn, gone, True, at=NOW)
    feedback_repo.set_hidden(conn, dropped, True, at=NOW)
    g = client.get("/api/gazette", params={"include_drop": True}).json()
    assert ids(g["sections"]) == {keep}
    assert g["counts"] == {"top": 1, "relevant": 0, "side": 0, "drop": 0}
    d = client.get(f"/api/days/{DAY}", params={"include_drop": True}).json()
    assert ids(d["sections"]) == {keep}
    assert client.get("/api/days").json()[0]["counts"]["top"] == 1


def test_story_responses_carry_feedback(client, conn):
    up = story(conn, "top")
    other = story(conn, "relevant")
    feedback_repo.set_vote(conn, up, "up", at=NOW)
    feedback_repo.set_read(conn, up, True, at=NOW)
    g = client.get("/api/gazette").json()["sections"]
    [top] = g["top"]
    assert (top["id"], top["vote"], top["read"], top["hidden"]) == (up, "up", True, False)
    [rel] = g["relevant"]
    assert (rel["id"], rel["vote"], rel["read"], rel["hidden"]) == (other, None, False, False)
    [day_top] = client.get(f"/api/days/{DAY}").json()["sections"]["top"]
    assert (day_top["vote"], day_top["read"]) == ("up", True)


def test_hidden_story_detail_still_available(client, conn):
    sid = story(conn)
    feedback_repo.set_hidden(conn, sid, True, at=NOW)
    feedback_repo.set_vote(conn, sid, "down", at=NOW)
    r = client.get(f"/api/stories/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert (body["hidden"], body["vote"], body["read"]) == (True, "down", False)


def test_build_sections_drops_hidden_feedback(conn):
    a, b = story(conn), story(conn)
    views = views_repo.day_views(conn, DAY)
    fb = {b: StoryFeedback(vote=None, read=False, hidden=True)}
    sections, counts = build_sections(views, ScoringSettings(), now=None, include_drop=True,
                                      feedback=fb)
    assert [s.id for s in sections.top] == [a] and counts.top == 1

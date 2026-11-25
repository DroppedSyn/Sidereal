"""GET /api/stories/{id} (plan §10.1): items, assessment, links and content rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.bootstrap import migrate
from sidereal.db.connect import connect
from sidereal.db.items_repo import items_for_story, set_content
from sidereal.db.stories_repo import set_state
from tests.factories import make_run, make_story, seed_demo

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


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
    return TestClient(create_app(settings, dist_dir=dist), base_url="http://testserver:8470")


@pytest.fixture
def run(conn):
    return make_run(conn, at=NOW - 2 * HOUR)


def _get(client, sid):
    r = client.get(f"/api/stories/{sid}")
    assert r.status_code == 200, r.text
    return r.json()


def test_detail_shape(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR, title="Entra flaw", bucket="top",
                     score=80.0, sources=("msrc-update-guide", "bleepingcomputer"),
                     urls=("https://msrc.example/a", "https://bc.example/b"),
                     flags={"kev": True, "exploited": True}, tags=("entra",),
                     focus="entra-identity", cve_ids=("CVE-2026-1",))
    body = _get(client, sid)
    items = body.pop("items")
    assert body == {
        "id": sid, "title": "Entra flaw", "day": "2026-07-14",
        "first_seen_at": "2026-07-14T07:00:00Z", "published_at": "2026-07-14T06:00:00Z",
        "bucket": "top", "score": 80.0, "summary": "AI summary.", "why": "Why it matters.",
        "tags": ["entra"], "focus": "entra-identity", "flags": {"kev": True, "exploited": True},
        "sources": [
            {"key": "msrc-update-guide", "name": "MSRC Security Update Guide",
             "url": "https://msrc.example/a"},
            {"key": "bleepingcomputer", "name": "BleepingComputer",
             "url": "https://bc.example/b"}],
        "lead_url": "https://msrc.example/a", "excerpt": "Original excerpt.", "read": False,
        "vote": None, "hidden": False,
        "cve_ids": ["CVE-2026-1"],
        "assessment": {"model": "demo-model", "prompt_version": "assess.v1",
                       "created_at": "2026-07-14T07:00:00Z",
                       "rubric": {"relevance": 2, "urgency": 2, "actionability": 2,
                                  "novelty": 2, "exploited_in_wild": True}}}
    assert [i["source_key"] for i in items] == ["msrc-update-guide", "bleepingcomputer"]
    assert items[0] == {
        "id": items[0]["id"], "source_key": "msrc-update-guide",
        "source_name": "MSRC Security Update Guide", "title": "Entra flaw",
        "url": "https://msrc.example/a", "author": None,
        "published_at": "2026-07-14T06:00:00Z", "first_seen_at": "2026-07-14T07:00:00Z",
        "excerpt": "Original excerpt."}
    assert items[0]["id"] < items[1]["id"]


def test_unknown_story_404(client):
    assert client.get("/api/stories/999").status_code == 404


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_bad_id_422(client, bad):
    assert client.get(f"/api/stories/{bad}").status_code == 422


@pytest.mark.parametrize("state", ["new", "filtered", "triaged_out"])
def test_hidden_story_404(client, conn, run, state):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR, state=state, bucket=None,
                     score=None)
    assert client.get(f"/api/stories/{sid}").status_code == 404


def test_never_returns_content_text(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR)
    for item in items_for_story(conn, sid):
        set_content(conn, item.id, text="SECRET ARTICLE BODY", status="ok")
    r = client.get(f"/api/stories/{sid}")
    assert r.status_code == 200
    assert "SECRET ARTICLE BODY" not in r.text
    assert "content" not in r.text


@pytest.mark.parametrize("url", ["javascript:alert(1)", "JaVaScRiPt:alert(1)",
                                 "data:text/html,x", " javascript:x", "ftp://x.example/a"])
def test_non_http_links_dropped(client, conn, run, url):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR,
                     sources=("bleepingcomputer", "hn"), urls=(url, "https://hn.example/ok"))
    body = _get(client, sid)
    assert body["lead_url"] is None
    assert body["sources"][0]["url"] is None
    assert body["items"][0]["url"] is None
    assert body["items"][1]["url"] == "https://hn.example/ok"
    assert url.strip() not in client.get(f"/api/stories/{sid}").text


def test_assess_failed_is_side_without_score_or_assessment(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR, state="assess_failed",
                     bucket=None, score=None)
    body = _get(client, sid)
    assert (body["bucket"], body["score"], body["assessment"]) == ("side", None, None)
    assert len(body["items"]) == 1


def test_assess_failed_hides_a_stale_assessment(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR, bucket="top", score=90.0)
    set_state(conn, sid, "assess_failed")
    body = _get(client, sid)
    assert (body["bucket"], body["score"], body["assessment"]) == ("side", None, None)


def test_drop_story_is_readable(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR, bucket="drop", score=5.0)
    assert _get(client, sid)["bucket"] == "drop"


def test_no_database_is_503(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    client = TestClient(create_app(settings, dist_dir=dist), base_url="http://testserver:8470")
    assert client.get("/api/stories/1").status_code == 503
    assert not settings.db_path.exists()


def test_demo_round_trip(client, conn):
    seed_demo(conn)
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM stories WHERE bucket IS NOT NULL OR state = 'assess_failed'")]
    assert ids
    for sid in ids:
        body = _get(client, sid)
        assert body["items"]
        assert all(i["url"].startswith("https://") for i in body["items"])

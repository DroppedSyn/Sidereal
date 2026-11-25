"""GET /api/gazette (plan §10.1): window, sections, order, caps, link and content rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.deps import get_now
from sidereal.bootstrap import migrate
from sidereal.config import ScoringSettings
from sidereal.db.connect import connect
from sidereal.db.items_repo import items_for_story, set_content
from tests.factories import DEMO_NOW, make_run, make_story, seed_demo

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)  # 09:00 in London (BST)
HOUR = timedelta(hours=1)
EMPTY = {"top": [], "relevant": [], "side": [], "drop": []}


def _client(settings, dist, now=NOW):
    app = create_app(settings, dist_dir=dist)
    app.dependency_overrides[get_now] = lambda: now
    return TestClient(app, base_url="http://testserver:8470")


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    return d


@pytest.fixture
def conn(settings):
    migrate(settings)
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def client(settings, dist, conn):
    return _client(settings, dist)


@pytest.fixture
def run(conn):
    return make_run(conn, at=NOW - 30 * HOUR)


def _gazette(client, query=""):
    r = client.get("/api/gazette" + query)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(stories):
    return [s["id"] for s in stories]


def test_empty_gazette(client):
    assert _gazette(client) == {
        "generated_at": "2026-07-14T08:00:00Z", "window_start": "2026-07-13T08:00:00Z",
        "sections": EMPTY, "counts": {"top": 0, "relevant": 0, "side": 0, "drop": 0}}


def test_no_database_is_503(settings, dist):
    r = _client(settings, dist).get("/api/gazette")
    assert r.status_code == 503
    assert not settings.db_path.exists()


def test_story_shape(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR, title="Entra flaw", bucket="top",
                     score=80.0, sources=("msrc-update-guide", "bleepingcomputer"),
                     urls=("https://msrc.example/a", "https://bc.example/b"), flags={"kev": True},
                     tags=("entra",), focus="entra-identity")
    assert _gazette(client)["sections"]["top"] == [{
        "id": sid, "title": "Entra flaw", "day": "2026-07-14",
        "first_seen_at": "2026-07-14T07:00:00Z", "published_at": "2026-07-14T06:00:00Z",
        "bucket": "top", "score": 80.0, "summary": "AI summary.", "why": "Why it matters.",
        "tags": ["entra"], "focus": "entra-identity", "flags": {"kev": True},
        "sources": [
            {"key": "msrc-update-guide", "name": "MSRC Security Update Guide",
             "url": "https://msrc.example/a"},
            {"key": "bleepingcomputer", "name": "BleepingComputer",
             "url": "https://bc.example/b"}],
        "lead_url": "https://msrc.example/a", "excerpt": "Original excerpt.", "read": False}]


def test_window_crosses_midnight(client, conn, run):
    a = make_story(conn, run_id=run, first_seen=datetime(2026, 7, 13, 22, 30, tzinfo=UTC))
    b = make_story(conn, run_id=run, first_seen=datetime(2026, 7, 13, 23, 30, tzinfo=UTC))
    c = make_story(conn, run_id=run, first_seen=NOW - 24 * HOUR)
    d = make_story(conn, run_id=run, first_seen=NOW - 24 * HOUR - timedelta(seconds=1))
    relevant = _gazette(client)["sections"]["relevant"]
    assert sorted(_ids(relevant)) == sorted([a, b, c])
    assert d not in _ids(relevant)
    assert {s["day"] for s in relevant} == {"2026-07-13", "2026-07-14"}


def test_hours_param(client, conn, run):
    make_story(conn, run_id=run, first_seen=NOW - 3 * HOUR)
    y = make_story(conn, run_id=run, first_seen=NOW - HOUR)
    body = _gazette(client, "?hours=2")
    assert _ids(body["sections"]["relevant"]) == [y]
    assert body["window_start"] == "2026-07-14T06:00:00Z"


@pytest.mark.parametrize("hours", ["0", "169", "abc"])
def test_bad_hours_rejected(client, hours):
    assert client.get(f"/api/gazette?hours={hours}").status_code == 422


def test_sections_and_counts(client, conn, run):
    at = NOW - HOUR
    t = make_story(conn, run_id=run, first_seen=at, bucket="top", score=80.0)
    rl = make_story(conn, run_id=run, first_seen=at, bucket="relevant", score=60.0)
    s = make_story(conn, run_id=run, first_seen=at, bucket="side", score=30.0)
    f = make_story(conn, run_id=run, first_seen=at, state="assess_failed", bucket="side",
                   score=None)
    d = make_story(conn, run_id=run, first_seen=at, bucket="drop", score=10.0)
    x = make_story(conn, run_id=run, first_seen=at, state="filtered", bucket=None)
    body = _gazette(client)
    sec = body["sections"]
    assert (_ids(sec["top"]), _ids(sec["relevant"]), _ids(sec["side"]), sec["drop"]) == (
        [t], [rl], [s, f], [])
    assert body["counts"] == {"top": 1, "relevant": 1, "side": 2, "drop": 1}
    failed = sec["side"][1]
    assert (failed["score"], failed["summary"], failed["why"]) == (None, None, None)
    assert x not in [st["id"] for lst in sec.values() for st in lst]
    assert _ids(_gazette(client, "?include_drop=true")["sections"]["drop"]) == [d]


def test_order_is_score_times_recency(client, conn, run):
    a = make_story(conn, run_id=run, first_seen=NOW - 20 * HOUR, bucket="top", score=80.0)
    b = make_story(conn, run_id=run, first_seen=NOW - HOUR, bucket="top", score=70.0)
    assert _ids(_gazette(client)["sections"]["top"]) == [b, a]


def test_top_cap_from_settings(settings, dist, conn, run):
    hi = make_story(conn, run_id=run, first_seen=NOW - HOUR, bucket="top", score=90.0)
    lo = make_story(conn, run_id=run, first_seen=NOW - HOUR, bucket="top", score=80.0)
    capped = settings.model_copy(update={"scoring": ScoringSettings(top_cap=1)})
    body = _gazette(_client(capped, dist))
    assert _ids(body["sections"]["top"]) == [hi]
    assert _ids(body["sections"]["relevant"]) == [lo]
    assert body["sections"]["relevant"][0]["bucket"] == "relevant"
    assert body["counts"]["top"] == 1
    assert body["counts"]["relevant"] == 1


def test_non_http_links_are_null(client, conn, run):
    make_story(conn, run_id=run, first_seen=NOW - HOUR, urls=("javascript:alert(1)",))
    r = client.get("/api/gazette")
    story = r.json()["sections"]["relevant"][0]
    assert story["lead_url"] is None
    assert story["sources"][0]["url"] is None
    assert "javascript:" not in r.text


def test_no_article_text(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=NOW - HOUR)
    set_content(conn, items_for_story(conn, sid)[0].id, text="FULL ARTICLE BODY", status="ok")
    r = client.get("/api/gazette")
    assert "FULL ARTICLE BODY" not in r.text
    assert r.json()["sections"]["relevant"][0]["excerpt"] == "Original excerpt."


def test_no_store_header(client):
    assert client.get("/api/gazette").headers["cache-control"] == "no-store"


def test_openapi_lists_gazette(client):
    assert "/api/gazette" in client.get("/api/openapi.json").json()["paths"]


def test_demo_seed(settings, dist, conn):
    seed_demo(conn)
    body = _gazette(_client(settings, dist, now=DEMO_NOW))
    assert body["counts"] == {"top": 2, "relevant": 4, "side": 4, "drop": 2}
    assert body["window_start"] == "2026-07-13T14:30:00Z"

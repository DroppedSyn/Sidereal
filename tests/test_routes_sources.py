"""GET /api/sources (plan §10.1, §10.2): health, last ok/error, items in the last 7 days."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.deps import get_now
from sidereal.bootstrap import migrate
from sidereal.db.connect import connect
from sidereal.db.sources_repo import get_by_key, record_broken, record_fetch_error, record_fetch_ok
from tests.factories import KNOWN_SOURCES, ensure_source, make_run, make_story, seed_demo

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
DAY = timedelta(days=1)


@pytest.fixture
def conn(settings):
    migrate(settings)
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def client(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    app = create_app(settings, dist_dir=dist)
    app.dependency_overrides[get_now] = lambda: NOW
    return TestClient(app, base_url="http://testserver:8470")


def _by_key(client):
    r = client.get("/api/sources")
    assert r.status_code == 200, r.text
    return {s["key"]: s for s in r.json()}


def test_lists_every_source_in_id_order(client, conn):
    assert client.get("/api/sources").json() == []
    seed_demo(conn, now=NOW)
    body = client.get("/api/sources").json()
    assert {s["key"] for s in body} == set(KNOWN_SOURCES)
    assert [s["id"] for s in body] == sorted(s["id"] for s in body)


def test_shape_and_counts(client, conn):
    run = make_run(conn, at=NOW - 10 * DAY)
    make_story(conn, run_id=run, first_seen=NOW - DAY, sources=("hn",))
    make_story(conn, run_id=run, first_seen=NOW - 2 * DAY, sources=("hn",))
    make_story(conn, run_id=run, first_seen=NOW - 8 * DAY, sources=("hn",))
    hn = get_by_key(conn, "hn")
    record_fetch_ok(conn, hn.id, at=NOW - DAY, etag=None, last_modified=None, entry_count=3)
    s = _by_key(client)["hn"]
    assert s == {
        "id": hn.id, "key": "hn", "name": "Hacker News", "kind": "rss",
        "url": "https://hn.example/feed", "enabled": True, "weight": 0.7, "health": "ok",
        "last_fetch_at": "2026-07-13T08:00:00Z", "last_ok_at": "2026-07-13T08:00:00Z",
        "last_error": None, "consecutive_failures": 0,
        "last_item_at": "2026-07-13T08:00:00Z", "items_7d": 2}


def test_health_states(client, conn):
    run = make_run(conn, at=NOW - 30 * DAY)
    make_story(conn, run_id=run, first_seen=NOW - 8 * DAY, sources=("stale-src",))
    make_story(conn, run_id=run, first_seen=NOW - DAY, sources=("fresh-src", "broken-src",
                                                                 "failing-src"))
    b, f = get_by_key(conn, "broken-src").id, get_by_key(conn, "failing-src").id
    record_broken(conn, b, at=NOW, error="HTML instead of a feed")
    for _ in range(3):
        record_fetch_error(conn, f, at=NOW, error="FetchError: timeout")
    out = _by_key(client)
    assert out["stale-src"]["health"] == "stale"
    assert out["fresh-src"]["health"] == "ok"
    assert out["broken-src"]["health"] == "broken"
    assert out["broken-src"]["last_error"] == "broken: HTML instead of a feed"
    assert (out["failing-src"]["health"], out["failing-src"]["consecutive_failures"]) == (
        "failing", 3)


def test_disabled_and_non_http_url(client, conn):
    sid = ensure_source(conn, "odd")
    conn.execute("UPDATE sources SET enabled = 0, url = 'javascript:alert(1)' WHERE id = ?",
                 (sid,))
    conn.commit()
    s = _by_key(client)["odd"]
    assert (s["enabled"], s["url"]) == (False, None)
    assert "javascript:" not in client.get("/api/sources").text


def test_no_database_is_503(client, settings):
    assert client.get("/api/sources").status_code == 503
    assert not settings.db_path.exists()

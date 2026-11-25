"""api/routes_feedback.py (M24): vote, read, hide, mark a day read, mutes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.deps import get_now
from sidereal.bootstrap import migrate
from sidereal.db.connect import connect
from tests.factories import ensure_source, make_run, make_story

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
WRITE = {"X-Sidereal": "1", "Origin": "http://testserver:8470"}
ORIGIN_ONLY = {"Origin": "http://testserver:8470"}
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


@pytest.fixture
def story(conn):
    return new_story(conn)


def new_story(conn, bucket="top"):
    run = make_run(conn, at=NOW - timedelta(hours=2))
    return make_story(conn, run_id=run, first_seen=NOW - timedelta(hours=1), tz="UTC",
                      bucket=bucket)


def fb(client, sid):
    r = client.get(f"/api/stories/{sid}/feedback")
    assert r.status_code == 200, r.text
    return r.json()


def test_get_feedback_default(client, story):
    assert fb(client, story) == {"story_id": story, "vote": None, "read": False,
                                 "hidden": False}


def test_get_feedback_unknown_404(client):
    r = client.get("/api/stories/999/feedback")
    assert r.status_code == 404 and r.json()["detail"] == "story not found"


def test_story_id_must_be_positive(client):
    assert client.get("/api/stories/0/feedback").status_code == 422
    assert client.put("/api/stories/0/vote", json={"vote": "up"},
                      headers=WRITE).status_code == 422


def test_vote_up_then_clear(client, story):
    r = client.put(f"/api/stories/{story}/vote", json={"vote": "up"}, headers=WRITE)
    assert r.status_code == 200 and r.json()["vote"] == "up"
    r = client.put(f"/api/stories/{story}/vote", json={"vote": "down"}, headers=WRITE)
    assert r.json()["vote"] == "down"
    r = client.put(f"/api/stories/{story}/vote", json={"vote": None}, headers=WRITE)
    assert r.status_code == 200 and r.json()["vote"] is None
    assert fb(client, story)["vote"] is None


@pytest.mark.parametrize("body", [{"vote": "meh"}, {}, {"vote": "up", "x": 1}])
def test_vote_invalid_422(client, story, body):
    r = client.put(f"/api/stories/{story}/vote", json=body, headers=WRITE)
    assert r.status_code == 422
    assert fb(client, story)["vote"] is None


@pytest.mark.parametrize("route,body", [("vote", {"vote": "up"}), ("read", {"read": True}),
                                        ("hidden", {"hidden": True})])
def test_unknown_story_404(client, route, body):
    r = client.put(f"/api/stories/999/{route}", json=body, headers=WRITE)
    assert r.status_code == 404 and r.json()["detail"] == "story not found"


def test_read_and_hidden(client, story):
    r = client.put(f"/api/stories/{story}/read", json={"read": True}, headers=WRITE)
    assert r.status_code == 200 and r.json()["read"] is True
    r = client.put(f"/api/stories/{story}/hidden", json={"hidden": True}, headers=WRITE)
    assert r.json()["hidden"] is True and r.json()["read"] is True
    r = client.put(f"/api/stories/{story}/read", json={"read": False}, headers=WRITE)
    assert r.json() == {"story_id": story, "vote": None, "read": False, "hidden": True}
    r = client.put(f"/api/stories/{story}/hidden", json={"hidden": False}, headers=WRITE)
    assert r.json()["hidden"] is False


@pytest.mark.parametrize("body", [{"read": "yes"}, {}, {"read": True, "hidden": True}])
def test_read_invalid_422(client, story, body):
    assert client.put(f"/api/stories/{story}/read", json=body,
                      headers=WRITE).status_code == 422


WRITES = [
    ("put", "/api/stories/{sid}/vote", {"vote": "up"}),
    ("put", "/api/stories/{sid}/read", {"read": True}),
    ("put", "/api/stories/{sid}/hidden", {"hidden": True}),
    ("post", f"/api/days/{DAY}/read", None),
]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_write_guard(client, story, method, path, body):
    url = path.format(sid=story)
    r = client.request(method.upper(), url, json=body, headers=ORIGIN_ONLY)
    assert r.status_code == 403
    r = client.request(method.upper(), url, json=body,
                       headers={"X-Sidereal": "1", "Origin": "http://evil.example"})
    assert r.status_code == 403
    assert fb(client, story) == {"story_id": story, "vote": None, "read": False,
                                 "hidden": False}


def test_mark_day_read(client, conn):
    a, b = new_story(conn), new_story(conn)
    dropped = new_story(conn, bucket="drop")
    r = client.post(f"/api/days/{DAY}/read", headers=WRITE)
    assert r.status_code == 200 and r.json() == {"day": DAY, "marked": 2}
    assert client.post(f"/api/days/{DAY}/read", headers=WRITE).json()["marked"] == 0
    assert fb(client, a)["read"] is True and fb(client, b)["read"] is True
    assert fb(client, dropped)["read"] is False


@pytest.mark.parametrize("day", ["2026-13-01", "yesterday"])
def test_mark_day_read_bad_day_422(client, day):
    assert client.post(f"/api/days/{day}/read", headers=WRITE).status_code == 422


def test_mutes_crud(client, conn):
    ensure_source(conn, "hackernews")
    r = client.post("/api/mutes", json={"kind": "source", "value": "hackernews"}, headers=WRITE)
    assert r.status_code == 201
    src = r.json()
    assert (src["kind"], src["value"], src["created_at"]) == (
        "source", "hackernews", "2026-07-14T08:00:00Z")
    r = client.post("/api/mutes", json={"kind": "keyword", "value": "  Bitcoin "},
                    headers=WRITE)
    assert r.status_code == 201 and r.json()["value"] == "bitcoin"
    listed = client.get("/api/mutes").json()
    assert [(m["kind"], m["value"]) for m in listed] == [("keyword", "bitcoin"),
                                                         ("source", "hackernews")]
    assert client.delete(f"/api/mutes/{src['id']}", headers=WRITE).status_code == 204
    assert [m["value"] for m in client.get("/api/mutes").json()] == ["bitcoin"]
    r = client.delete(f"/api/mutes/{src['id']}", headers=WRITE)
    assert r.status_code == 404 and r.json()["detail"] == "mute not found"


def test_mute_unknown_source_422(client):
    r = client.post("/api/mutes", json={"kind": "source", "value": "nope"}, headers=WRITE)
    assert r.status_code == 422 and r.json()["detail"] == "unknown source"
    assert client.get("/api/mutes").json() == []


@pytest.mark.parametrize("body", [
    {"kind": "tag", "value": "x"},
    {"kind": "keyword", "value": ""},
    {"kind": "keyword", "value": "   "},
    {"kind": "keyword", "value": "x" * 201},
    {"kind": "keyword"},
    {"kind": "keyword", "value": "x", "extra": 1},
])
def test_mute_invalid_422(client, body):
    assert client.post("/api/mutes", json=body, headers=WRITE).status_code == 422
    assert client.get("/api/mutes").json() == []


def test_mute_duplicate_returns_same_id(client):
    a = client.post("/api/mutes", json={"kind": "keyword", "value": "crypto"}, headers=WRITE)
    b = client.post("/api/mutes", json={"kind": "keyword", "value": "CRYPTO"}, headers=WRITE)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]


def test_mute_writes_guarded(client):
    r = client.post("/api/mutes", json={"kind": "keyword", "value": "x"}, headers=ORIGIN_ONLY)
    assert r.status_code == 403
    assert client.get("/api/mutes").json() == []
    r = client.post("/api/mutes", json={"kind": "keyword", "value": "x"}, headers=WRITE)
    assert client.delete(f"/api/mutes/{r.json()['id']}", headers=ORIGIN_ONLY).status_code == 403
    assert len(client.get("/api/mutes").json()) == 1


def test_openapi_lists_feedback_routes(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    for p in ("/api/stories/{story_id}/feedback", "/api/stories/{story_id}/vote",
              "/api/stories/{story_id}/read", "/api/stories/{story_id}/hidden",
              "/api/days/{day}/read", "/api/mutes", "/api/mutes/{mute_id}"):
        assert p in paths, p


def test_auth_on_requires_session(settings, tmp_path, conn, story):
    on = settings.model_copy(update={"auth": settings.auth.model_copy(update={"mode": "on"})})
    dist = tmp_path / "dist2"
    dist.mkdir()
    c = TestClient(create_app(on, dist_dir=dist), base_url="http://testserver:8470")
    assert c.get(f"/api/stories/{story}/feedback").status_code == 401
    assert c.put(f"/api/stories/{story}/vote", json={"vote": "up"},
                 headers=WRITE).status_code == 401
    assert c.get("/api/mutes").status_code == 401

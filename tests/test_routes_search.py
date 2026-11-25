"""api/routes_search.py (M26): GET /api/search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.bootstrap import migrate
from sidereal.db import search_repo
from sidereal.db.connect import connect
from sidereal.db.feedback_repo import set_hidden, set_read
from tests.auth_helpers import add_user, auth_settings, fast_hasher, login, make_client
from tests.factories import make_run, make_story

__all__ = ["fast_hasher"]  # fixture re-export

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


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


def story(conn, title, **kw) -> int:
    run = make_run(conn, at=NOW - timedelta(hours=2))
    return make_story(conn, run_id=run, first_seen=NOW - timedelta(hours=1), tz="UTC",
                      title=title, **kw)


def get(client, **params):
    r = client.get("/api/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_result_shape(client, conn):
    sid = story(conn, "Exploited Entra flaw", excerpt="details about entra")
    set_read(conn, sid, True, at=NOW)
    body = get(client, q="entra")
    assert body["query"] == "entra" and body["next_before"] is None
    [res] = body["results"]
    assert res["story"]["id"] == sid and res["story"]["read"] is True
    assert res["story"]["title"] == "Exploited Entra flaw"
    assert isinstance(res["rank"], float)
    assert "\x02" in res["snippet"] and "\x03" in res["snippet"]


@pytest.mark.parametrize("q", ['"', '""', "*", "OR", "a OR", "NEAR(", "NEAR(a b, 2)",
                               "col:", "title:entra", "", "   ", "x" * 1000, "(", "^",
                               "'; DROP TABLE stories; --"])
def test_injection_like_queries_are_200(client, conn, q):
    story(conn, "Entra flaw")
    body = get(client, q=q)
    assert isinstance(body["results"], list)


def test_too_long_query_is_422(client):
    assert client.get("/api/search", params={"q": "x" * 1001}).status_code == 422


def test_missing_query_is_422(client):
    assert client.get("/api/search").status_code == 422


def test_syntax_error_is_400(client, conn, monkeypatch):
    story(conn, "Entra flaw")
    monkeypatch.setattr(search_repo, "fts_query", lambda text: 'NEAR("a"')
    r = client.get("/api/search", params={"q": "a"})
    assert r.status_code == 400
    assert r.json() == {"detail": "invalid search query"}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"before": 0},
                                    {"limit": "x"}])
def test_bad_paging_is_422(client, params):
    assert client.get("/api/search", params={"q": "a", **params}).status_code == 422


def test_paging(client, conn):
    made = [story(conn, f"Entra flaw {i}") for i in range(5)]
    first = get(client, q="entra", limit=2)
    assert [r["story"]["id"] for r in first["results"]] == [made[4], made[3]]
    assert first["next_before"] == made[3]
    second = get(client, q="entra", limit=2, before=first["next_before"])
    assert [r["story"]["id"] for r in second["results"]] == [made[2], made[1]]
    third = get(client, q="entra", limit=2, before=second["next_before"])
    assert [r["story"]["id"] for r in third["results"]] == [made[0]]
    assert third["next_before"] is None


def test_exact_page_has_no_next(client, conn):
    story(conn, "Entra one")
    story(conn, "Entra two")
    assert get(client, q="entra", limit=2)["next_before"] is None


def test_hidden_story_left_out(client, conn):
    a = story(conn, "Entra flaw one")
    b = story(conn, "Entra flaw two")
    set_hidden(conn, a, True, at=NOW)
    assert [r["story"]["id"] for r in get(client, q="entra")["results"]] == [b]


def test_no_database_is_503(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    c = TestClient(create_app(settings, dist_dir=dist), base_url="http://testserver:8470")
    assert c.get("/api/search", params={"q": "a"}).status_code == 503


def test_auth_on_requires_session(settings, tmp_path, conn):
    story(conn, "Entra flaw")
    on = settings.model_copy(update={"auth": settings.auth.model_copy(update={"mode": "on"})})
    dist = tmp_path / "dist2"
    dist.mkdir()
    c = TestClient(create_app(on, dist_dir=dist), base_url="http://testserver:8470")
    r = c.get("/api/search", params={"q": "entra"})
    assert r.status_code == 401
    assert "Entra" not in r.text


def test_auth_on_with_session(config_file, monkeypatch, tmp_path, fast_hasher):
    s = auth_settings(config_file, monkeypatch)
    c = connect(s.db_path)
    add_user(c)
    sid = story(c, "Entra flaw")
    c.close()
    client = make_client(s, tmp_path)
    assert client.get("/api/search", params={"q": "entra"}).status_code == 401
    assert login(client).status_code == 200
    body = get(client, q="entra")
    assert [r["story"]["id"] for r in body["results"]] == [sid]


def test_openapi_lists_route(client):
    assert "/api/search" in client.get("/api/openapi.json").json()["paths"]

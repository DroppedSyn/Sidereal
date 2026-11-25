"""api/routes_settings_sources.py (M27): source CRUD and "Test feed"."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from sidereal.api import routes_settings_sources
from sidereal.api.app import create_app
from sidereal.api.deps import get_now
from sidereal.bootstrap import init
from sidereal.db import sources_repo
from sidereal.db.connect import connect
from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from tests.adapter_helpers import feed_bytes, make_fetcher
from tests.factories import make_run, make_story

ORIGIN = "http://testserver:8470"
WRITE = {"X-Sidereal": "1", "Origin": ORIGIN}
NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
NEW = {"key": "my-feed", "name": "My feed", "kind": "rss", "url": "https://feeds.example.com/a",
       "weight": 1.3, "max_items": 25,
       "options": {"article_hosts": ["Example.com"], "include_regex": "(?i)azure"}}


@pytest.fixture
def client(settings, tmp_path):
    init(settings)
    dist = tmp_path / "dist"
    dist.mkdir()
    app = create_app(settings, dist_dir=dist)
    app.dependency_overrides[get_now] = lambda: NOW
    return TestClient(app, base_url=ORIGIN)


def row(settings, key):
    conn = connect(settings.db_path)
    try:
        return sources_repo.get_by_key(conn, key)
    finally:
        conn.close()


def test_list_has_options(client):
    rows = client.get("/api/settings/sources").json()
    hn = next(r for r in rows if r["kind"] == "hn_algolia")
    assert hn["options"]["queries"] and "min_points" in hn["options"]
    assert {"id", "key", "name", "kind", "url", "enabled", "weight", "max_items"} <= set(hn)


def test_add_source_round_trip(client, settings):
    r = client.post("/api/settings/sources", headers=WRITE, json=NEW)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["options"] == {"article_hosts": ["example.com"], "include_regex": "(?i)azure"}
    stored = row(settings, "my-feed")
    assert (stored.kind, stored.url, stored.weight, stored.max_items, stored.enabled) == (
        "rss", NEW["url"], 1.3, 25, True)
    assert stored.created_at == "2026-07-14T08:00:00Z"
    assert stored.options == body["options"]
    assert client.post("/api/settings/sources", headers=WRITE, json=NEW).status_code == 409


def test_edit_source(client, settings):
    sid = client.post("/api/settings/sources", headers=WRITE, json=NEW).json()["id"]
    edit = {"name": "Renamed", "url": "https://other.example.com/rss", "enabled": False,
            "weight": 0.5, "max_items": 10, "options": {}}
    r = client.put(f"/api/settings/sources/{sid}", headers=WRITE, json=edit)
    assert r.status_code == 200, r.text
    stored = row(settings, "my-feed")
    assert (stored.name, stored.url, stored.enabled, stored.weight, stored.max_items,
            stored.options, stored.kind) == ("Renamed", edit["url"], False, 0.5, 10, {}, "rss")
    assert client.put("/api/settings/sources/9999", headers=WRITE,
                      json=edit).status_code == 404


def test_edit_cannot_change_key_or_kind(client):
    sid = client.post("/api/settings/sources", headers=WRITE, json=NEW).json()["id"]
    edit = {k: v for k, v in NEW.items() if k not in ("key", "kind")}
    for extra in ({"key": "other"}, {"kind": "msrc"}):
        r = client.put(f"/api/settings/sources/{sid}", headers=WRITE, json=edit | extra)
        assert r.status_code == 422


def test_edit_checks_options_for_the_stored_kind(client, settings):
    key = next(s["key"] for s in client.get("/api/settings/sources").json()
               if s["kind"] == "hn_algolia")
    hn = row(settings, key)
    edit = {"name": hn.name, "url": hn.url, "enabled": True, "weight": 1.0, "max_items": 20,
            "options": {"queries": []}}
    r = client.put(f"/api/settings/sources/{hn.id}", headers=WRITE, json=edit)
    assert r.status_code == 422 and "queries" in r.json()["detail"]
    edit["options"] = {"include_regex": "x"}
    r = client.put(f"/api/settings/sources/{hn.id}", headers=WRITE, json=edit)
    assert r.status_code == 422 and "not used by hn_algolia" in r.json()["detail"]


@pytest.mark.parametrize("change", [
    {"url": "http://127.0.0.1/feed"},
    {"url": "http://10.1.2.3/feed"},
    {"url": "http://[::1]/feed"},
    {"url": "http://169.254.169.254/"},
    {"url": "http://localhost:8470/api"},
    {"url": "https://nas.local/feed"},
    {"url": "ftp://example.com/feed"},
    {"url": "https://user:pw@example.com/feed"},
    {"url": "https://example.com:8443/feed"},
    {"weight": 0.4}, {"weight": 1.6}, {"weight": "1.0"}, {"weight": True},
    {"max_items": 0}, {"max_items": 501}, {"max_items": 2.5},
    {"key": "Bad"}, {"key": ""}, {"kind": "atom"}, {"name": "  "}, {"name": "a\nb"},
    {"enabled": 1}, {"options": {"include_regex": "(unclosed"}},
    {"options": {"exclude_regex": "*"}}, {"options": {"product_regex": "x"}},
    {"options": {"article_hosts": ["127.0.0.1"]}}, {"options": {"max_bytes": -5}},
    {"options": ["not", "a", "dict"]}, {"surprise": True},
])
def test_add_source_422(client, settings, change):
    r = client.post("/api/settings/sources", headers=WRITE, json=NEW | change)
    assert r.status_code == 422, (change, r.text)
    assert row(settings, "my-feed") is None


def test_private_ip_source_is_rejected(client, settings):
    """Plan §16 M27: adding a source with a private-IP URL is rejected."""
    r = client.post("/api/settings/sources", headers=WRITE,
                    json=NEW | {"url": "http://192.168.1.10/rss.xml"})
    assert r.status_code == 422
    assert "private" in str(r.json()["detail"])
    assert row(settings, "my-feed") is None


def test_delete_source(client, settings):
    sid = client.post("/api/settings/sources", headers=WRITE, json=NEW).json()["id"]
    assert client.delete(f"/api/settings/sources/{sid}", headers=WRITE).status_code == 204
    assert row(settings, "my-feed") is None
    assert client.delete(f"/api/settings/sources/{sid}", headers=WRITE).status_code == 404
    assert client.delete("/api/settings/sources/0", headers=WRITE).status_code == 422


def test_source_with_items_cannot_be_deleted(client, settings):
    conn = connect(settings.db_path)
    try:
        run = make_run(conn, at=NOW)
        make_story(conn, run_id=run, first_seen=NOW, tz="UTC", sources=("bleepingcomputer",))
    finally:
        conn.close()
    sid = row(settings, "bleepingcomputer").id
    r = client.delete(f"/api/settings/sources/{sid}", headers=WRITE)
    assert r.status_code == 409 and "disable" in r.json()["detail"]
    assert row(settings, "bleepingcomputer") is not None


def test_source_writes_need_the_guard(client, settings):
    assert client.post("/api/settings/sources", json=NEW,
                       headers={"Origin": ORIGIN}).status_code == 403
    sid = row(settings, "bleepingcomputer").id
    assert client.delete(f"/api/settings/sources/{sid}",
                         headers={"X-Sidereal": "1"}).status_code == 403
    assert client.post("/api/settings/sources/test", json=NEW,
                       headers={"Origin": "http://evil.example"}).status_code == 403


# --- Test feed ---------------------------------------------------------------------------

TEST = {"kind": "rss", "url": "https://feeds.example.com/feed", "max_items": 5, "options": {}}


def use_fetcher(monkeypatch, fetcher):
    monkeypatch.setattr(routes_settings_sources, "make_fetcher", lambda: fetcher)


def test_feed_test_ok(client, monkeypatch):
    fetcher, seen = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    use_fetcher(monkeypatch, fetcher)
    r = client.post("/api/settings/sources/test", headers=WRITE, json=TEST)
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True and body["error"] is None
    assert body["entries"] >= body["items"] == 5 and len(body["titles"]) == 5
    assert str(seen[0].url) == TEST["url"]
    assert "If-None-Match" not in seen[0].headers


def test_feed_test_applies_filters(client, monkeypatch):
    fetcher, _ = make_fetcher(feed_bytes("bleepingcomputer.xml"))
    use_fetcher(monkeypatch, fetcher)
    r = client.post("/api/settings/sources/test", headers=WRITE,
                    json=TEST | {"options": {"include_regex": "^NO MATCH EVER$"}})
    assert r.json()["ok"] is True and r.json()["items"] == 0 and r.json()["entries"] > 0


@pytest.mark.parametrize("status, content_type, body, error", [
    (404, "text/html", b"gone", "HTTP 404"),
    (200, "text/html", b"<!doctype html><html><body>login</body></html>", "not a feed"),
])
def test_feed_test_failures(client, monkeypatch, status, content_type, body, error):
    fetcher, _ = make_fetcher(body, status=status, content_type=content_type)
    use_fetcher(monkeypatch, fetcher)
    r = client.post("/api/settings/sources/test", headers=WRITE, json=TEST)
    assert r.status_code == 200 and r.json()["ok"] is False and error in r.json()["error"]


def test_feed_test_dns_to_private_is_refused(client, monkeypatch):
    """The static check passes a public-looking name; the guard's DNS check refuses it."""
    async def private(host: str, port: int) -> Sequence[str]:
        return ["10.0.0.7"]

    requests: list[httpx.Request] = []
    client_http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: requests.append(req) or httpx.Response(200)))
    use_fetcher(monkeypatch, Fetcher(client=client_http, guard=UrlGuard(resolver=private)))
    r = client.post("/api/settings/sources/test", headers=WRITE, json=TEST)
    assert r.json()["ok"] is False and "URL refused" in r.json()["error"]
    assert requests == []


@pytest.mark.parametrize("change", [
    {"url": "http://127.0.0.1/"}, {"url": "gopher://x.example.com/"}, {"kind": "nope"},
    {"options": {"include_regex": "("}}, {"max_items": 0},
])
def test_feed_test_422(client, monkeypatch, change):
    def boom():
        raise AssertionError("no fetch for an invalid request")

    monkeypatch.setattr(routes_settings_sources, "make_fetcher", boom)
    r = client.post("/api/settings/sources/test", headers=WRITE, json=TEST | change)
    assert r.status_code == 422

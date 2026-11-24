"""create_app: health, host allowlist, write guard, headers, static UI, bind refusal."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sidereal import __version__
from sidereal.api.app import create_app
from sidereal.api.bind import UnsafeBindError, check_bind, is_loopback
from sidereal.api.security import CSP
from sidereal.bootstrap import migrate
from sidereal.config import load_settings

ORIGIN = "http://testserver:8470"
GOOD = {"X-Sidereal": "1", "Origin": ORIGIN}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>Sidereal</title>")
    (d / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside dist")
    return d


@pytest.fixture
def client(settings, dist) -> TestClient:
    migrate(settings)
    app = create_app(settings, dist_dir=dist)

    @app.post("/api/_echo")  # a write endpoint to exercise the guard
    def echo() -> dict:
        return {"ok": True}

    return TestClient(app, base_url="http://testserver:8470")


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__, "db": "ok"}


def test_health_degraded_without_db(settings, dist):
    r = TestClient(create_app(settings, dist_dir=dist)).get("/api/health")
    assert r.json()["db"] == "error"
    assert not settings.db_path.exists()


def test_unknown_host_rejected(client):
    r = client.get("/api/health", headers={"Host": "evil.example"})
    assert r.status_code == 400


def test_default_allowed_hosts_exclude_testserver(isolated_env, dist):
    app = create_app(load_settings(), dist_dir=dist)  # no test config: defaults only
    assert TestClient(app).get("/api/health").status_code == 400
    ok = TestClient(app, base_url="http://127.0.0.1:8470").get("/api/health")
    assert ok.status_code == 200


def test_post_without_custom_header_rejected(client):
    r = client.post("/api/_echo", headers={"Origin": ORIGIN})
    assert r.status_code == 403
    wrong = {"Origin": ORIGIN, "X-Sidereal": "0"}
    assert client.post("/api/_echo", headers=wrong).status_code == 403


def test_cross_origin_post_rejected(client):
    for origin in ("http://evil.example", "http://testserver:9999", "null", "file://x"):
        r = client.post("/api/_echo", headers={"X-Sidereal": "1", "Origin": origin})
        assert r.status_code == 403, origin
    assert client.post("/api/_echo", headers={"X-Sidereal": "1"}).status_code == 403


def test_same_origin_post_allowed(client):
    assert client.post("/api/_echo", headers=GOOD).status_code == 200
    referer = {"X-Sidereal": "1", "Referer": ORIGIN + "/daily/2026-07-14"}
    assert client.post("/api/_echo", headers=referer).status_code == 200


def test_allowed_origins_setting_admits_dev_server(config_file, monkeypatch, dist):
    monkeypatch.setenv("SIDEREAL_WEB__ALLOWED_ORIGINS", '["http://localhost:5173"]')
    app = create_app(load_settings(), dist_dir=dist)
    app.post("/api/_echo")(lambda: {"ok": True})
    c = TestClient(app, base_url="http://testserver:8470")
    h = {"X-Sidereal": "1", "Origin": "http://localhost:5173"}
    assert c.post("/api/_echo", headers=h).status_code == 200


def test_security_headers_and_no_store(client):
    api = client.get("/api/health")
    assert api.headers["content-security-policy"] == CSP
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["referrer-policy"] == "no-referrer"
    assert api.headers["cache-control"] == "no-store"
    page = client.get("/")
    assert page.headers["content-security-policy"] == CSP
    assert page.headers.get("cache-control") != "no-store"
    assert "script-src 'self';" in CSP and "unsafe-inline" not in CSP


def test_spa_fallback_and_assets(client):
    assert "<title>Sidereal</title>" in client.get("/").text
    assert "<title>Sidereal</title>" in client.get("/daily/2026-07-14").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404
    assert "outside dist" not in client.get("/../secret.txt").text
    assert "outside dist" not in client.get("/assets/..%2F..%2Fsecret.txt").text


def test_ui_not_built_page(settings, tmp_path: Path):
    c = TestClient(create_app(settings, dist_dir=tmp_path / "no-dist"))
    r = c.get("/")
    assert r.status_code == 503
    assert "UI not built: run npm run build" in r.text


def test_openapi_lists_health(client):
    assert "/api/health" in client.get("/api/openapi.json").json()["paths"]


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost", "127.0.0.2"])
def test_loopback_hosts(host):
    assert is_loopback(host)


def test_refuses_nonloopback_without_auth(settings):
    for host in ("0.0.0.0", "192.168.1.20", "::", "vm.lan"):
        assert not is_loopback(host)
        with pytest.raises(UnsafeBindError):
            check_bind(host, settings, user_count=5)  # auth off: users don't matter
    check_bind("127.0.0.1", settings, user_count=0)


def test_refuses_nonloopback_with_auth_but_no_user(settings):
    on = settings.model_copy(update={"auth": settings.auth.model_copy(update={"mode": "on"})})
    with pytest.raises(UnsafeBindError):
        check_bind("192.168.1.20", on, user_count=0)
    check_bind("192.168.1.20", on, user_count=1)

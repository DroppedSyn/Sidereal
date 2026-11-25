"""/api/auth/* and the session middleware over every /api route (M25, plan §11.2)."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from starlette.requests import Request

from sidereal.auth import ratelimit, sessions
from sidereal.auth.middleware import PUBLIC, client_ip
from sidereal.bootstrap import migrate
from sidereal.db import users_repo
from tests.auth_helpers import (  # noqa: F401
    PASSWORD,
    WRITE,
    add_user,
    auth_settings,
    fast_hasher,
    login,
    make_client,
    open_conn,
)

pytestmark = pytest.mark.usefixtures("fast_hasher")


@pytest.fixture
def on(config_file, monkeypatch):
    s = auth_settings(config_file, monkeypatch)
    conn = open_conn(s)
    add_user(conn)
    conn.close()
    return s


@pytest.fixture
def client(on, tmp_path):
    return make_client(on, tmp_path)


def _api_routes(app):
    """Every documented /api operation (from the OpenAPI schema, so new routes are covered)."""
    for path, ops in app.openapi()["paths"].items():
        if path in PUBLIC:
            continue
        concrete = path.replace("{day}", "2026-07-14")
        concrete = re.sub(r"\{[^}]+\}", "1", concrete)
        for method in ops:
            yield method.upper(), concrete


def test_every_api_route_needs_a_session(client):
    routes = list(_api_routes(client.app))
    assert len(routes) >= 9  # gazette, days x2, stories, runs x3, sources, me
    for method, path in routes:
        r = client.request(method, path, headers=WRITE)
        assert r.status_code == 401, (method, path)
        assert r.json() == {"detail": "authentication required"}
    for path in ("/api/openapi.json", "/api/nope", "/api/gazette/", "/api"):
        assert client.get(path).status_code == 401, path


def test_write_guard_runs_before_auth(client):
    assert client.post("/api/runs").status_code == 403
    assert client.post("/api/auth/login", json={"username": "owner", "password": PASSWORD}
                       ).status_code == 403
    assert "set-cookie" not in client.post("/api/auth/login", json={}).headers


def test_ui_shell_needs_no_session(client):
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 200


def test_login_then_routes_work(client):
    r = login(client)
    assert r.status_code == 200 and r.json() == {"auth": "on", "username": "owner"}
    assert client.get("/api/auth/me").json() == {"auth": "on", "username": "owner"}
    assert client.get("/api/runs").status_code == 200
    assert client.get("/api/sources").status_code == 200
    assert PASSWORD not in r.text and client.cookies["sidereal_session"] not in r.text


def test_login_cookie_flags(client):
    cookie = login(client).headers["set-cookie"]
    assert cookie.startswith("sidereal_session=")
    for flag in ("HttpOnly", "SameSite=strict", "Path=/"):
        assert flag in cookie
    assert "Secure" not in cookie  # web.https is off


def test_secure_cookie_with_https(config_file, monkeypatch, tmp_path):
    monkeypatch.setenv("SIDEREAL_WEB__HTTPS", "true")
    s = auth_settings(config_file, monkeypatch)
    conn = open_conn(s)
    add_user(conn)
    conn.close()
    c = make_client(s, tmp_path, base_url="https://testserver:8470")
    r = c.post("/api/auth/login", json={"username": "owner", "password": PASSWORD},
               headers={"X-Sidereal": "1", "Origin": "https://testserver:8470"})
    assert "Secure" in r.headers["set-cookie"]
    assert c.get("/api/runs").status_code == 200


def test_wrong_password_and_unknown_user_same_response(client):
    wrong = login(client, password="not the password")
    unknown = login(client, name="nobody", password="not the password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.content == unknown.content == b'{"detail":"invalid username, password or code"}'
    assert "set-cookie" not in wrong.headers and "set-cookie" not in unknown.headers


def test_rate_limit_answers_429(client):
    for _ in range(ratelimit.MAX_PER_USER_IP):
        assert login(client, password="not the password").status_code == 401
    r = login(client)  # right password, still limited
    assert r.status_code == 429
    assert r.headers["retry-after"] == str(ratelimit.retry_after_s())
    assert "set-cookie" not in r.headers
    for _ in range(ratelimit.MAX_PER_USER_IP):
        login(client, name="nobody", password="x" * 12)
    assert login(client, name="nobody").content == r.content


def test_logout_invalidates_session(client, on):
    login(client)
    token = client.cookies["sidereal_session"]
    out = client.post("/api/auth/logout", headers=WRITE)
    assert out.status_code == 204
    assert 'sidereal_session=""' in out.headers["set-cookie"]
    conn = open_conn(on)
    assert users_repo.get_session(conn, sessions.token_hash(token)) is None
    conn.close()
    client.cookies.set("sidereal_session", token)  # replay the old cookie
    assert client.get("/api/runs").status_code == 401


def test_logout_needs_write_guard(client, on):
    login(client)
    assert client.post("/api/auth/logout").status_code == 403
    assert client.get("/api/runs").status_code == 200  # still logged in


def test_logout_without_session_is_fine(client):
    assert client.post("/api/auth/logout", headers=WRITE).status_code == 204


def test_expired_session_rejected_and_cookie_cleared(client, on):
    login(client)
    conn = open_conn(on)
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z'")
    conn.commit()
    r = client.get("/api/runs")
    assert r.status_code == 401
    assert 'sidereal_session=""' in r.headers["set-cookie"]
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    conn.close()


def test_idle_session_rejected(client, on):
    login(client)
    conn = open_conn(on)
    old = "2000-01-01T00:00:00Z"
    conn.execute("UPDATE sessions SET last_seen_at = ?", (old,))
    conn.commit()
    conn.close()
    assert client.get("/api/runs").status_code == 401


def test_forged_cookie_rejected(client, on):
    login(client)
    token = client.cookies["sidereal_session"]
    conn = open_conn(on)
    stored = conn.execute("SELECT id_hash FROM sessions").fetchone()[0]
    conn.close()
    client.cookies.clear()
    for forged in (stored, token[:-2] + "AA", "x" * 43):
        client.cookies.set("sidereal_session", forged)
        assert client.get("/api/runs").status_code == 401, forged


def test_login_rotates_session(client, on):
    login(client)
    first = client.cookies["sidereal_session"]
    login(client)
    second = client.cookies["sidereal_session"]
    assert first != second
    conn = open_conn(on)
    assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    conn.close()


def test_password_change_by_cli_ends_sessions(client, on):
    login(client)
    conn = open_conn(on)
    users_repo.delete_user_sessions(conn, 1)
    conn.close()
    assert client.get("/api/runs").status_code == 401


def test_health_minimal_without_session(client):
    body = client.get("/api/health").json()
    assert body == {"status": "ok", "version": None, "db": None}
    login(client)
    full = client.get("/api/health").json()
    assert full["version"] is not None and full["db"] == "ok"


def test_validation_errors_do_not_echo_password(client):
    r = client.post("/api/auth/login", headers=WRITE,
                    json={"username": "owner", "password": ["hunter2-secret-value"]})
    assert r.status_code == 422
    assert "hunter2-secret-value" not in r.text
    # Other routes keep the default 422 body.
    assert client.get("/api/runs", params={"limit": "x"}).status_code == 401


def test_auth_off_everything_open(settings, tmp_path):
    migrate(settings)
    c = make_client(settings, tmp_path)
    assert c.get("/api/runs").status_code == 200
    assert c.get("/api/sources").status_code == 200
    assert c.get("/api/auth/me").json() == {"auth": "off", "username": None}
    assert c.get("/api/health").json()["version"] is not None
    r = c.post("/api/auth/login", headers=WRITE, json={"username": "a", "password": "b"})
    assert r.status_code == 404


def _request(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


def test_client_ip_ignores_forwarded_for_from_untrusted_peer():
    assert client_ip(_request("10.0.0.9", "1.2.3.4"), []) == "10.0.0.9"
    assert client_ip(_request("10.0.0.9", "1.2.3.4"), ["127.0.0.1"]) == "10.0.0.9"


def test_client_ip_from_trusted_proxy():
    trusted = ["127.0.0.1"]
    assert client_ip(_request("127.0.0.1", "1.2.3.4"), trusted) == "1.2.3.4"
    # The client may prepend anything; the rightmost untrusted hop counts.
    assert client_ip(_request("127.0.0.1", "6.6.6.6, 1.2.3.4"), trusted) == "1.2.3.4"
    assert client_ip(_request("127.0.0.1", "1.2.3.4, 127.0.0.1"), trusted) == "1.2.3.4"
    assert client_ip(_request("127.0.0.1", "garbage"), trusted) == "127.0.0.1"
    assert client_ip(_request("127.0.0.1"), trusted) == "127.0.0.1"


def test_expired_cutoff_constant():
    assert sessions.IDLE == timedelta(days=7) and sessions.ABSOLUTE == timedelta(days=30)

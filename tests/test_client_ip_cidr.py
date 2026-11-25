"""Client IP for the login rate limit behind a proxy given as a CIDR network (M30)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from sidereal.api.app import create_app
from sidereal.auth.middleware import client_ip
from tests.auth_helpers import (  # noqa: F401
    PASSWORD,
    WRITE,
    add_user,
    auth_settings,
    fast_hasher,
    open_conn,
)

pytestmark = pytest.mark.usefixtures("fast_hasher")


def _request(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(("peer", "proxies", "want"), [
    ("10.0.0.5", ["10.0.0.0/24"], "203.0.113.7"),       # peer inside the network
    ("10.0.0.255", ["10.0.0.0/24"], "203.0.113.7"),     # last address of it
    ("10.0.1.5", ["10.0.0.0/24"], "10.0.1.5"),          # just outside: XFF ignored
    ("192.168.1.9", ["10.0.0.0/8", "192.168.1.8/30"], "203.0.113.7"),
    ("192.168.1.12", ["10.0.0.0/8", "192.168.1.8/30"], "192.168.1.12"),
    ("fd00::5", ["fd00::/64"], "203.0.113.7"),
    ("fd00:0:0:1::5", ["fd00::/64"], "fd00:0:0:1::5"),
    ("::ffff:10.0.0.5", ["10.0.0.0/24"], "203.0.113.7"),  # dual-stack socket form
    ("10.0.0.5", ["::/0"], "10.0.0.5"),                   # a v6 network never covers v4
    ("10.0.0.5", ["10.0.0.5"], "203.0.113.7"),            # single IPs still work
])
def test_peer_in_cidr(peer, proxies, want):
    assert client_ip(_request(peer, "203.0.113.7"), proxies) == want


def test_trusted_hops_inside_the_network_are_skipped():
    proxies = ["10.0.0.0/24"]
    xff = "6.6.6.6, 203.0.113.7, 10.0.0.9, 10.0.0.3"
    assert client_ip(_request("10.0.0.5", xff), proxies) == "203.0.113.7"
    # every hop trusted: the peer itself
    assert client_ip(_request("10.0.0.5", "10.0.0.9"), proxies) == "10.0.0.5"


def _client(config_file, monkeypatch, tmp_path, peer):
    monkeypatch.setenv("SIDEREAL_WEB__TRUSTED_PROXIES", json.dumps(["10.0.0.0/24"]))
    s = auth_settings(config_file, monkeypatch)
    conn = open_conn(s)
    add_user(conn)
    conn.close()
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>Sidereal</title>")
    return s, TestClient(create_app(s, dist_dir=dist), base_url="http://testserver:8470",
                         client=(peer, 50000))


def _fail(c, ip):
    return c.post("/api/auth/login", headers={**WRITE, "X-Forwarded-For": ip},
                  json={"username": "owner", "password": "wrong " + PASSWORD})


def test_rate_limit_counts_the_forwarded_client(config_file, monkeypatch, tmp_path):
    s, c = _client(config_file, monkeypatch, tmp_path, "10.0.0.5")
    assert [_fail(c, "203.0.113.7").status_code for _ in range(5)] == [401] * 5
    assert _fail(c, "203.0.113.7").status_code == 429
    # another client behind the same proxy has its own bucket
    assert _fail(c, "203.0.113.8").status_code == 401
    conn = open_conn(s)
    ips = {r[0] for r in conn.execute("SELECT ip FROM login_attempts")}
    conn.close()
    assert ips == {"203.0.113.7", "203.0.113.8"}


def test_untrusted_peer_shares_its_own_bucket(config_file, monkeypatch, tmp_path):
    _, c = _client(config_file, monkeypatch, tmp_path, "10.0.1.5")  # outside 10.0.0.0/24
    for i in range(5):
        assert _fail(c, f"203.0.113.{i}").status_code == 401
    assert _fail(c, "203.0.113.99").status_code == 429  # spoofed XFF doesn't help

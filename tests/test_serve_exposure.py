"""``serve`` refuses a loopback bind that is exposed anyway (M30, rule 9 widened): a reverse proxy
(``trusted_proxies``) or a non-loopback ``allowed_hosts`` name needs auth on and a user."""

from __future__ import annotations

import json

import pytest
import uvicorn

from sidereal.api.bind import UnsafeBindError, check_bind, exposure, is_loopback_name
from sidereal.cli import main
from sidereal.config import load_settings
from tests.auth_helpers import add_user, fast_hasher, open_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("fast_hasher")
LOCAL = '["127.0.0.1", "localhost"]'


@pytest.fixture
def served(monkeypatch):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    return calls


@pytest.fixture
def local(config_file, monkeypatch):
    monkeypatch.setenv("SIDEREAL_WEB__ALLOWED_HOSTS", LOCAL)


def test_plain_loopback_still_serves_with_auth_off(local, served):
    assert main(["serve"]) == 0
    assert served[0]["host"] == "127.0.0.1"


@pytest.mark.parametrize(("var", "value", "why"), [
    ("TRUSTED_PROXIES", '["127.0.0.1"]', "web.trusted_proxies is set"),
    ("TRUSTED_PROXIES", '["10.0.0.0/24"]', "web.trusted_proxies is set"),
    ("ALLOWED_HOSTS", '["127.0.0.1", "sidereal.lan"]', "non-loopback names (sidereal.lan)"),
    ("ALLOWED_HOSTS", '["127.0.0.1", "192.168.1.50"]', "non-loopback names (192.168.1.50)"),
    ("ALLOWED_HOSTS", '["*"]', "non-loopback names (*)"),
])
def test_loopback_bind_refused_when_exposed(local, monkeypatch, served, capsys, var, value, why):
    monkeypatch.setenv(f"SIDEREAL_WEB__{var}", value)
    assert main(["serve"]) == 2
    err = capsys.readouterr().err
    assert why in err and "auth.mode is off" in err
    assert served == []


def test_proxied_needs_a_user_too(local, monkeypatch, served, capsys):
    monkeypatch.setenv("SIDEREAL_WEB__TRUSTED_PROXIES", '["127.0.0.1"]')
    monkeypatch.setenv("SIDEREAL_AUTH__MODE", "on")
    assert main(["serve"]) == 2
    assert "no user exists" in capsys.readouterr().err
    s = load_settings()
    from sidereal.bootstrap import migrate

    migrate(s)
    conn = open_conn(s)
    add_user(conn)
    conn.close()
    assert main(["serve"]) == 0
    assert served == [{"host": "127.0.0.1", "port": 8470, "proxy_headers": False}]


def test_exposure_reasons(local, monkeypatch):
    s = load_settings()
    assert exposure("127.0.0.1", s) == []
    assert exposure("::1", s) == []
    assert exposure("0.0.0.0", s) == ["bind 0.0.0.0 is not loopback"]
    monkeypatch.setenv("SIDEREAL_WEB__TRUSTED_PROXIES", json.dumps(["::1"]))
    monkeypatch.setenv("SIDEREAL_WEB__ALLOWED_HOSTS", json.dumps(["localhost", "vm", "a.lan"]))
    s = load_settings()
    assert exposure("vm", s) == [
        "bind vm is not loopback",
        "web.trusted_proxies is set (served through a proxy)",
        "web.allowed_hosts has non-loopback names (vm, a.lan)",
    ]
    with pytest.raises(UnsafeBindError, match="auth.mode is off"):
        check_bind("127.0.0.1", s, user_count=3)


@pytest.mark.parametrize(("name", "loopback"), [
    ("127.0.0.1", True), ("::1", True), ("[::1]", True), ("localhost", True),
    ("LocalHost", True), ("ui.localhost", True), ("localhost.", True),
    ("testserver", False), ("sidereal.lan", False), ("localhost.lan", False),
    ("mylocalhost", False), ("10.0.0.1", False), ("*", False), ("", False),
])
def test_is_loopback_name(name, loopback):
    assert is_loopback_name(name) is loopback

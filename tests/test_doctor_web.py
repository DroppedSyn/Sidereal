"""``sidereal doctor`` web exposure checks (M30): each misconfiguration and the clean cases."""

from __future__ import annotations

import json

import pytest

from sidereal import commands, doctor, doctor_web, paths
from sidereal.cli import main
from sidereal.config import load_settings
from tests.auth_helpers import add_user, fast_hasher, open_conn  # noqa: F401
from tests.fake_ollama import FakeOllama
from tests.pipeline_helpers import NOW, ollama_for

pytestmark = pytest.mark.usefixtures("fast_hasher")
LOCAL = ["127.0.0.1", "localhost"]


def mk(monkeypatch, *, hosts=LOCAL, proxies=(), origins=(), https=False, auth="off",
       host="127.0.0.1"):
    env = {"ALLOWED_HOSTS": list(hosts), "TRUSTED_PROXIES": list(proxies),
           "ALLOWED_ORIGINS": list(origins), "HTTPS": https, "HOST": host}
    for key, value in env.items():
        monkeypatch.setenv(f"SIDEREAL_WEB__{key}", json.dumps(value))
    monkeypatch.setenv("SIDEREAL_AUTH__MODE", auth)
    return load_settings()


def by_name(checks):
    return {c.name: c for c in checks}


def with_user(settings, disabled=False):
    from sidereal.bootstrap import migrate

    migrate(settings)
    conn = open_conn(settings)
    add_user(conn)
    if disabled:
        conn.execute("UPDATE users SET disabled = 1")
        conn.commit()
    conn.close()


# --- web exposure -------------------------------------------------------------------------

def test_loopback_only_is_ok_with_auth_off(config_file, monkeypatch):
    c = by_name(doctor_web.check_web_exposure(mk(monkeypatch)))
    assert c["web exposure"].level == doctor.OK
    assert "loopback only (127.0.0.1)" in c["web exposure"].detail
    assert c["web bind"].detail == "127.0.0.1 (from web.host)"
    assert "origins" not in c


@pytest.mark.parametrize(("kw", "why"), [
    ({"proxies": ["127.0.0.1"]}, "trusted_proxies"),
    ({"proxies": ["10.0.0.0/24"]}, "trusted_proxies"),
    ({"hosts": [*LOCAL, "sidereal.lan"]}, "sidereal.lan"),
    ({"hosts": [*LOCAL, "192.168.1.50"]}, "192.168.1.50"),
    ({"hosts": ["*"]}, "allowed_hosts"),
    ({"host": "0.0.0.0"}, "bind 0.0.0.0"),
    ({"host": "192.168.1.50"}, "bind 192.168.1.50"),
])
def test_exposed_with_auth_off_fails(config_file, monkeypatch, kw, why):
    c = by_name(doctor_web.check_web_exposure(mk(monkeypatch, **kw)))["web exposure"]
    assert c.level == doctor.FAIL
    assert why in c.detail and "auth.mode is off" in c.detail


@pytest.mark.parametrize("name", ["::1", "127.0.0.2", "LOCALHOST", "app.localhost", "localhost."])
def test_loopback_names_are_not_exposure(config_file, monkeypatch, name):
    c = by_name(doctor_web.check_web_exposure(mk(monkeypatch, hosts=[*LOCAL, name])))
    assert c["web exposure"].level == doctor.OK


def test_exposed_with_auth_on_but_no_user_fails(config_file, monkeypatch):
    s = mk(monkeypatch, proxies=["127.0.0.1"], auth="on")
    c = by_name(doctor_web.check_web_exposure(s))["web exposure"]
    assert c.level == doctor.FAIL and "no active user" in c.detail
    assert not s.db_path.exists()  # read-only: no DB created


def test_disabled_user_does_not_count(config_file, monkeypatch):
    s = mk(monkeypatch, proxies=["127.0.0.1"], auth="on")
    with_user(s, disabled=True)
    assert by_name(doctor_web.check_web_exposure(s))["web exposure"].level == doctor.FAIL


def test_exposed_with_auth_and_user_is_ok(config_file, monkeypatch):
    s = mk(monkeypatch, proxies=["127.0.0.1"], hosts=[*LOCAL, "sidereal.lan"], auth="on")
    with_user(s)
    c = by_name(doctor_web.check_web_exposure(s))["web exposure"]
    assert c.level == doctor.OK and "auth on, 1 active user(s)" in c.detail


def test_installed_unit_host_overrides_web_host(config_file, monkeypatch):
    unit_dir = paths.systemd_user_dir()
    unit_dir.mkdir(parents=True)
    (unit_dir / "sidereal-web.service").write_text(
        "[Service]\nExecStart=/x/.venv/bin/sidereal serve --host 0.0.0.0 --port 8470\n")
    c = by_name(doctor_web.check_web_exposure(mk(monkeypatch)))
    assert c["web bind"].detail == "0.0.0.0 (from sidereal-web.service)"
    assert c["web exposure"].level == doctor.FAIL


@pytest.mark.parametrize(("text", "want"), [
    ("ExecStart=/s serve --host 127.0.0.1 --port 8470", "127.0.0.1"),
    ("ExecStart=/s serve --host=192.168.1.5", "192.168.1.5"),
    ("ExecStart = /s serve --port 1 --host ::", "::"),
    ("ExecStart=/s serve --port 8470", None),
    ("ExecStart=/s serve --host", None),
    ("# ExecStart=/s serve --host 0.0.0.0", None),
    ("ExecStart=/s 'unterminated", None),
])
def test_unit_host(tmp_path, text, want):
    unit = tmp_path / "u.service"
    unit.write_text(f"[Service]\n{text}\n")
    assert doctor_web.unit_host(unit) == want
    assert doctor_web.unit_host(tmp_path / "missing") is None


# --- https --------------------------------------------------------------------------------

@pytest.mark.parametrize(("kw", "level", "text"), [
    ({}, doctor.OK, "off (loopback only)"),
    ({"proxies": ["127.0.0.1"]}, doctor.WARN, "behind a proxy"),
    ({"host": "0.0.0.0"}, doctor.WARN, "bound on 0.0.0.0"),
    ({"proxies": ["127.0.0.1"], "https": True}, doctor.OK, "Secure"),
    ({"https": True}, doctor.OK, "Secure"),  # loopback (ssh tunnel): browsers allow it
    ({"host": "0.0.0.0", "https": True}, doctor.WARN, "plain HTTP"),
    ({"host": "0.0.0.0", "https": True, "proxies": ["192.168.1.2"]}, doctor.OK, "Secure"),
])
def test_https(config_file, monkeypatch, kw, level, text):
    c = by_name(doctor_web.check_web_exposure(mk(monkeypatch, **kw)))["https"]
    assert c.level == level and text in c.detail


# --- trusted proxies, origins -------------------------------------------------------------

@pytest.mark.parametrize(("proxies", "level"), [
    ([], doctor.OK), (["127.0.0.1", "::1"], doctor.OK), (["10.0.0.0/24"], doctor.OK),
    (["10.0.0.0/23"], doctor.WARN), (["0.0.0.0/0"], doctor.WARN),
    (["fd00::/64"], doctor.OK), (["fd00::/63"], doctor.WARN), (["::/0"], doctor.WARN),
])
def test_wide_proxy_networks_warn(config_file, monkeypatch, proxies, level):
    c = by_name(doctor_web.check_web_exposure(mk(monkeypatch, proxies=proxies)))
    assert c["trusted proxies"].level == level


def test_proxied_name_without_origin_warns(config_file, monkeypatch):
    s = mk(monkeypatch, proxies=["127.0.0.1"], hosts=[*LOCAL, "sidereal.lan", "*.lan"])
    c = by_name(doctor_web.check_web_exposure(s))["origins"]
    assert c.level == doctor.WARN and "sidereal.lan" in c.detail and "*.lan" not in c.detail
    s = mk(monkeypatch, proxies=["127.0.0.1"], hosts=[*LOCAL, "Sidereal.lan"],
           origins=["https://sidereal.lan", "not a url ["])
    assert by_name(doctor_web.check_web_exposure(s))["origins"].level == doctor.OK


# --- through the CLI ----------------------------------------------------------------------

@pytest.fixture
def cli(config_file, monkeypatch):
    fake = FakeOllama(models=["qwen3.8:27b"])
    monkeypatch.setattr(commands, "make_ollama",
                        lambda settings, *, timeout_s=None: ollama_for(fake, settings))
    monkeypatch.setattr(doctor, "utc_now", lambda: NOW)
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)
    monkeypatch.setattr(doctor, "DISK_FAIL_BYTES", 0)


def test_doctor_exits_1_when_proxied_without_auth(cli, monkeypatch, capsys):
    mk(monkeypatch, proxies=["127.0.0.1"])
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "❌ web exposure: web.trusted_proxies is set" in out
    assert "⚠ https: off while behind a proxy" in out


def test_doctor_clean_lan_setup(cli, monkeypatch, capsys):
    s = mk(monkeypatch, proxies=["127.0.0.1", "::1"], hosts=[*LOCAL, "sidereal.lan"],
           origins=["https://sidereal.lan"], https=True, auth="on")
    assert main(["init"]) == 0
    with_user(s)
    capsys.readouterr()
    main(["doctor"])
    out = capsys.readouterr().out
    for line in ("✅ web exposure:", "✅ https: on", "✅ trusted proxies: 127.0.0.1/32, ::1/128",
                 "✅ origins: https://sidereal.lan"):
        assert line in out

"""``web.trusted_proxies``: single IPs or CIDR networks, v4 and v6; anything else is a
ConfigError, never silently dropped (M30)."""

from __future__ import annotations

import ipaddress
import json

import pytest

from sidereal.cli import main
from sidereal.config import ConfigError, load_settings, parse_proxy, proxy_networks


def _load(monkeypatch, proxies):
    monkeypatch.setenv("SIDEREAL_WEB__TRUSTED_PROXIES", json.dumps(proxies))
    return load_settings()


@pytest.mark.parametrize(("entry", "network"), [
    ("127.0.0.1", "127.0.0.1/32"),
    ("10.0.0.0/24", "10.0.0.0/24"),
    (" 192.168.1.0/28 ", "192.168.1.0/28"),
    ("::1", "::1/128"),
    ("fd00::/64", "fd00::/64"),
    ("2001:db8::/32", "2001:db8::/32"),
])
def test_parse_valid(entry, network):
    assert parse_proxy(entry) == ipaddress.ip_network(network)


@pytest.mark.parametrize("entry", [
    "", "  ", "proxy.lan", "localhost", "10.0.0.1/24",  # host bits set: a typo, not a network
    "10.0.0.0/33", "fd00::/129", "300.1.1.1", "10.0.0.0/", "[::1]", "*",
])
def test_parse_invalid(entry):
    with pytest.raises(ValueError, match="trusted_proxies"):
        parse_proxy(entry)


def test_settings_accept_cidrs(config_file, monkeypatch):
    s = _load(monkeypatch, ["127.0.0.1", "10.0.0.0/24", "fd00::/64"])
    assert s.web.trusted_proxies == ["127.0.0.1", "10.0.0.0/24", "fd00::/64"]
    assert proxy_networks(s.web.trusted_proxies) == (
        ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("10.0.0.0/24"),
        ipaddress.ip_network("fd00::/64"))


@pytest.mark.parametrize("bad", ["10.0.0.1/24", "proxy.lan", ""])
def test_invalid_entry_is_config_error(config_file, monkeypatch, bad):
    with pytest.raises(ConfigError, match="trusted_proxies"):
        _load(monkeypatch, ["127.0.0.1", bad])


def test_invalid_entry_in_toml_exits_2(config_file, capsys):
    text = config_file.read_text().replace("[web]", '[web]\ntrusted_proxies = ["10.0.0.0/8x"]', 1)
    config_file.write_text(text)
    assert main(["doctor"]) == 2
    assert "trusted_proxies" in capsys.readouterr().err


def test_default_is_empty(settings):
    assert settings.web.trusted_proxies == []
    assert proxy_networks([]) == ()

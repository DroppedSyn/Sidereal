"""``deploy/Caddyfile.example`` (M30): read as text (Caddy isn't installed on the VM): balanced
blocks, the proxy to the loopback app, TLS, a body cap, and no header the app already sends."""

from __future__ import annotations

import re

from sidereal import paths
from sidereal.api.security import SECURITY_HEADERS

CADDYFILE = paths.project_root() / "deploy" / "Caddyfile.example"


def _lines() -> list[str]:
    """Directive lines without comments or blank lines."""
    out = []
    for raw in CADDYFILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.lstrip().startswith("#") else ""
        if line:
            out.append(line)
    return out


def _site_block() -> list[str]:
    lines = _lines()
    start = next(i for i, ln in enumerate(lines) if ln.endswith("{") and ln != "{"
                 and not ln.startswith(("servers", "timeouts")))
    depth, block = 0, []
    for ln in lines[start:]:
        depth += ln.count("{") - ln.count("}")
        block.append(ln)
        if depth == 0:
            return block
    raise AssertionError("site block never closes")


def test_braces_balance():
    depth = 0
    for ln in _lines():
        depth += ln.count("{") - ln.count("}")
        assert depth >= 0, ln
    assert depth == 0


def test_reverse_proxy_to_loopback_app():
    block = _site_block()
    assert block[0] == "sidereal.lan {"
    assert "reverse_proxy 127.0.0.1:8470" in block
    assert sum(ln.startswith("reverse_proxy") for ln in _lines()) == 1


def test_tls_internal_and_body_cap():
    block = _site_block()
    assert "tls internal" in block
    caps = [ln for ln in block if ln.startswith("max_size")]
    assert caps == ["max_size 1MB"]


def test_no_header_duplicates_the_app():
    app_headers = {h.lower() for h in SECURITY_HEADERS} | {"cache-control"}
    for ln in _site_block():
        m = re.match(r"^[?+>]?([A-Za-z][A-Za-z-]+)\s+\"", ln)
        if m:
            assert m.group(1).lower() not in app_headers, ln


def test_hsts_off_for_tls_internal():
    assert not any(ln.startswith("Strict-Transport-Security") for ln in _lines())
    assert "# Strict-Transport-Security" in CADDYFILE.read_text(encoding="utf-8")


def test_uses_tabs_like_caddy_fmt():
    for raw in CADDYFILE.read_text(encoding="utf-8").splitlines():
        assert not raw.startswith(" "), raw

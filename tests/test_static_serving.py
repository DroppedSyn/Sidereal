"""``api/static.py``: web/dist serving, SPA fallback, cache headers, traversal, MIME types (M21)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import unquote_to_bytes

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.security import CSP
from sidereal.api.static import (
    ASSET_CACHE,
    PAGE_CACHE,
    is_unsafe_path,
    media_type_for,
    resolve_asset,
)
from sidereal.bootstrap import migrate

ROOT = Path(__file__).resolve().parents[1]
REAL_DIST = ROOT / "web" / "dist"
INDEX = "<!doctype html><title>Sidereal</title>"
SECRET = "outside dist"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text(INDEX)
    (d / "favicon.svg").write_text("<svg/>")
    (d / "assets" / "index-abc123.js").write_text("console.log(1)")
    (d / "assets" / "index-abc123.css").write_text("body{}")
    (d / "assets" / "logo-abc123.svg").write_text("<svg/>")
    (d / "assets" / "font-abc123.woff2").write_bytes(b"wOF2")
    (tmp_path / "secret.txt").write_text(SECRET)
    return d


def make_client(settings, dist: Path) -> TestClient:
    migrate(settings)
    return TestClient(create_app(settings, dist_dir=dist), base_url="http://testserver:8470")


@pytest.fixture
def client(settings, dist) -> TestClient:
    return make_client(settings, dist)


def raw_get(app, raw_path: bytes) -> tuple[int, dict[str, str], bytes]:
    """GET with an exact path, bypassing httpx's dot-segment normalisation."""
    path = raw_path.split(b"?")[0]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": unquote_to_bytes(path).decode("latin-1"), "raw_path": path,
        "query_string": b"", "root_path": "", "headers": [(b"host", b"testserver:8470")],
        "client": ("127.0.0.1", 1), "server": ("testserver", 8470),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], headers, body


# --- cache headers -------------------------------------------------------------------------


def test_index_is_no_cache_html_with_csp(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.text == INDEX
    assert r.headers["cache-control"] == PAGE_CACHE == "no-cache"
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/index.html", "/daily/2026-07-14", "/runs", "/assets"])
def test_spa_fallback_is_no_cache_html_with_csp(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.text == INDEX
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CSP


def test_hashed_asset_is_immutable(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert r.text == "console.log(1)"
    assert r.headers["cache-control"] == ASSET_CACHE == "public, max-age=31536000, immutable"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_root_file_outside_assets_is_not_immutable(client):
    r = client.get("/favicon.svg")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("image/svg+xml")


def test_api_stays_no_store(client):
    for path in ("/api/health", "/api/nope"):
        r = client.get(path)
        assert r.headers["cache-control"] == "no-store", path
        assert "immutable" not in r.headers["cache-control"]
    assert client.get("/api/nope").status_code == 404


def test_not_built_page_is_not_cached(settings, tmp_path: Path):
    r = make_client(settings, tmp_path / "no-dist").get("/")
    assert r.status_code == 503
    assert r.headers["cache-control"] == "no-store"


# --- missing assets ------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/assets/index-old999.js", "/assets/nope/x.css", "/assets/"])
def test_missing_asset_is_404_not_the_shell(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert "Sidereal" not in r.text
    assert "immutable" not in r.headers.get("cache-control", "")


# --- MIME types ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "media"),
    [
        ("/assets/index-abc123.js", "text/javascript"),
        ("/assets/index-abc123.css", "text/css"),
        ("/assets/logo-abc123.svg", "image/svg+xml"),
        ("/assets/font-abc123.woff2", "font/woff2"),
    ],
)
def test_media_types(client, path, media):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0] == media
    assert r.headers["x-content-type-options"] == "nosniff"


def test_media_type_fallbacks(tmp_path: Path):
    assert media_type_for(tmp_path / "a.JS") == "text/javascript"
    assert media_type_for(tmp_path / "a.pdf") == "application/pdf"
    assert media_type_for(tmp_path / "blob.unknownext") == "application/octet-stream"


# --- traversal -----------------------------------------------------------------------------


TRAVERSALS = [
    b"/../secret.txt",
    b"/assets/../../secret.txt",
    b"/%2e%2e/secret.txt",
    b"/%2E%2E/secret.txt",
    b"/%2e%2e%2fsecret.txt",
    b"/assets/..%2F..%2Fsecret.txt",
    b"/assets/%2e%2e/%2e%2e/secret.txt",
    b"/..%5csecret.txt",
    b"//etc/passwd",
    b"/%2Fetc%2Fpasswd",
]


@pytest.mark.parametrize("raw", TRAVERSALS)
def test_traversal_is_404(client, raw):
    status, headers, body = raw_get(client.app, raw)
    assert status == 404
    assert SECRET.encode() not in body
    assert b"root:" not in body
    assert "immutable" not in headers.get("cache-control", "")


@pytest.mark.parametrize(
    "rel", ["../secret.txt", "assets/../../secret.txt", "a/../b", "..", "/etc/passwd",
            "\\etc\\passwd", "..\\secret.txt", "a\x00b"],
)
def test_unsafe_paths(rel):
    assert is_unsafe_path(rel)


@pytest.mark.parametrize("rel", ["index.html", "assets/index-abc.js", "a..b/c", "x/..y", "..z"])
def test_safe_paths(rel):
    assert not is_unsafe_path(rel)


def test_resolve_asset_rejects_escapes(dist: Path):
    js = dist / "assets" / "index-abc123.js"
    assert resolve_asset(dist, "assets/index-abc123.js") == js.resolve()
    for rel in ("", "../secret.txt", "assets/../../secret.txt", str(dist.parent / "secret.txt")):
        assert resolve_asset(dist, rel) is None, rel
    assert resolve_asset(dist, "assets") is None  # a directory is not a file


def test_symlink_out_of_dist_is_not_served(settings, dist: Path):
    (dist / "assets" / "leak-abc123.js").symlink_to(dist.parent / "secret.txt")
    (dist / "leak.txt").symlink_to(dist.parent / "secret.txt")
    assert resolve_asset(dist, "assets/leak-abc123.js") is None
    assert resolve_asset(dist, "leak.txt") is None
    c = make_client(settings, dist)
    r = c.get("/assets/leak-abc123.js")
    assert r.status_code == 404 and SECRET not in r.text
    r = c.get("/leak.txt")
    assert SECRET not in r.text and r.text == INDEX


def test_symlink_inside_dist_is_served(dist: Path):
    (dist / "assets" / "alias-abc123.js").symlink_to(dist / "assets" / "index-abc123.js")
    assert resolve_asset(dist, "assets/alias-abc123.js") is not None


# --- the real build ------------------------------------------------------------------------


def test_real_build_served_with_cache_headers_and_csp(settings):
    index = REAL_DIST / "index.html"
    if not index.exists():
        pytest.skip("web/dist not built")
    c = make_client(settings, REAL_DIST)
    page = c.get("/")
    assert page.headers["content-security-policy"] == CSP
    assert page.headers["cache-control"] == "no-cache"
    refs = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
    assert refs, "index.html references no /assets/ files"
    for ref in refs:
        r = c.get(ref)
        assert r.status_code == 200, ref
        assert r.headers["cache-control"] == ASSET_CACHE, ref
        expected = "text/javascript" if ref.endswith(".js") else "text/css"
        assert r.headers["content-type"].split(";")[0] == expected, ref

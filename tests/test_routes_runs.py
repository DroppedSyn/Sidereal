"""GET /api/runs, /api/runs/{id} and POST /api/runs (plan §10.1, §11.1, §12.1, rule 12)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sidereal.api import routes_runs
from sidereal.api.app import create_app
from sidereal.bootstrap import migrate
from sidereal.db.connect import connect
from sidereal.pipeline.lock import RunLock, lock_path
from tests.factories import make_run, seed_demo

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
ORIGIN = "http://testserver:8470"
WRITE = {"X-Sidereal": "1", "Origin": ORIGIN}


@pytest.fixture
def conn(settings):
    migrate(settings)
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def client(settings, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    return TestClient(create_app(settings, dist_dir=dist), base_url=ORIGIN)


@pytest.fixture
def spawned(monkeypatch):
    """Replace the spawn: tests never start a run."""
    calls: list[int] = []
    monkeypatch.setattr(routes_runs, "spawn_run", lambda: calls.append(1))
    return calls


@pytest.fixture
def proc(monkeypatch):
    """Replace ``subprocess.run`` inside routes_runs and record each call."""
    calls: list[tuple[tuple, dict]] = []
    result = {"returncode": 0, "stderr": b""}

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], result["returncode"], None,
                                           result["stderr"])

    monkeypatch.setattr(routes_runs.subprocess, "run", fake)
    return calls, result


# --- GET ---

def test_list_newest_first_with_stats(client, conn):
    a = make_run(conn, at=NOW, stats={"ingest": {"new": 3}})
    b = make_run(conn, at=NOW + timedelta(hours=4), status="failed", error="boom")
    c = make_run(conn, at=NOW + timedelta(hours=8), status="running", trigger="manual")
    body = client.get("/api/runs").json()
    assert [r["id"] for r in body] == [c, b, a]
    assert body[2] == {"id": a, "started_at": "2026-07-14T08:00:00Z",
                       "finished_at": "2026-07-14T08:05:00Z", "trigger": "timer",
                       "status": "ok", "duration_s": 300.0, "stats": {"ingest": {"new": 3}},
                       "error": None}
    assert body[1]["error"] == "boom"
    assert (body[0]["finished_at"], body[0]["duration_s"], body[0]["trigger"]) == (
        None, None, "manual")


def test_list_pagination(client, conn):
    ids = [make_run(conn, at=NOW + timedelta(hours=k)) for k in range(5)]
    first = client.get("/api/runs?limit=2").json()
    assert [r["id"] for r in first] == [ids[4], ids[3]]
    nxt = client.get(f"/api/runs?limit=2&before={first[-1]['id']}").json()
    assert [r["id"] for r in nxt] == [ids[2], ids[1]]
    assert client.get(f"/api/runs?before={ids[0]}").json() == []
    assert len(client.get("/api/runs").json()) == 5


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "before=0", "limit=x"])
def test_bad_params_422(client, conn, query):
    assert client.get(f"/api/runs?{query}").status_code == 422


def test_detail_and_404(client, conn):
    rid = make_run(conn, at=NOW, stats={"x": 1})
    assert client.get(f"/api/runs/{rid}").json()["stats"] == {"x": 1}
    assert client.get("/api/runs/999").status_code == 404
    assert client.get("/api/runs/0").status_code == 422


def test_demo_runs(client, conn):
    n = seed_demo(conn)["runs"]
    body = client.get("/api/runs?limit=200").json()
    assert len(body) == n
    assert {r["status"] for r in body} == {"ok", "partial", "failed"}


def test_no_database_is_503(client, settings):
    assert client.get("/api/runs").status_code == 503
    assert not settings.db_path.exists()


# --- POST run-now ---

def test_post_starts_run(client, spawned):
    r = client.post("/api/runs", headers=WRITE)
    assert r.status_code == 202
    assert r.json() == {"status": "started", "unit": "sidereal-run-manual.service"}
    assert spawned == [1]


def test_post_needs_custom_header(client, spawned):
    for headers in ({"Origin": ORIGIN}, {"Origin": ORIGIN, "X-Sidereal": "0"}):
        assert client.post("/api/runs", headers=headers).status_code == 403
    assert spawned == []


@pytest.mark.parametrize("origin", ["http://evil.example", "http://testserver:9999", "null",
                                    None])
def test_post_needs_allowed_origin(client, spawned, origin):
    headers = {"X-Sidereal": "1"}
    if origin is not None:
        headers["Origin"] = origin
    assert client.post("/api/runs", headers=headers).status_code == 403
    assert spawned == []


def test_post_409_while_locked(client, settings, spawned):
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with RunLock(lock_path(settings.state_dir)):
        r = client.post("/api/runs", headers=WRITE)
    assert r.status_code == 409
    assert spawned == []
    assert client.post("/api/runs", headers=WRITE).status_code == 202  # released
    assert spawned == [1]


def test_post_needs_no_database(client, settings, spawned):
    assert client.post("/api/runs", headers=WRITE).status_code == 202
    assert not settings.db_path.exists()
    assert not lock_path(settings.state_dir).exists()  # the lock probe never creates it


def test_fixed_argv_without_request_data(client, proc):
    calls, _ = proc
    r = client.post("/api/runs?unit=evil.service&trigger=x;rm", headers={
        **WRITE, "Content-Type": "application/json", "X-Unit": "evil.service"},
        content=b'{"argv": ["rm", "-rf", "/"], "unit": "evil.service"}')
    assert r.status_code == 202
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (["systemctl", "--user", "start", "--no-block",
                     "sidereal-run-manual.service"],)
    assert list(routes_runs.START_ARGV) == args[0]
    assert not kwargs.get("shell")
    assert "evil" not in repr(calls) and "rm" not in " ".join(args[0])
    assert kwargs["timeout"] == routes_runs.START_TIMEOUT_S


def test_systemctl_failure_is_503(client, proc):
    calls, result = proc
    result.update(returncode=5, stderr=b"Unit sidereal-run-manual.service not found.")
    r = client.post("/api/runs", headers=WRITE)
    assert r.status_code == 503
    assert "systemctl exit 5" in r.json()["detail"]


@pytest.mark.parametrize("exc", [FileNotFoundError("systemctl"),
                                 subprocess.TimeoutExpired("systemctl", 15)])
def test_systemctl_missing_or_slow_is_503(client, monkeypatch, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(routes_runs.subprocess, "run", boom)
    r = client.post("/api/runs", headers=WRITE)
    assert r.status_code == 503
    assert type(exc).__name__ in r.json()["detail"]

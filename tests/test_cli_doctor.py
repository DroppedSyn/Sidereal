"""``sidereal doctor``: one line per check, exit 1 on any ❌, never creates or writes anything."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta

import httpx
import pytest

from sidereal import commands, doctor, paths
from sidereal.cli import main
from sidereal.db import runs_repo, sources_repo
from sidereal.db.connect import connect
from sidereal.pipeline import lock
from tests.fake_ollama import FakeOllama
from tests.pipeline_helpers import NOW, ollama_for


@pytest.fixture
def fake(settings, monkeypatch):
    f = FakeOllama(models=["qwen3.8:27b"])
    f.closed = []

    def make(settings, *, timeout_s=None):
        f.timeout_s = timeout_s
        client = ollama_for(f, settings)
        real = client.aclose

        async def aclose():
            f.closed.append(True)
            await real()

        client.aclose = aclose
        return client

    monkeypatch.setattr(commands, "make_ollama", make)
    monkeypatch.setattr(doctor, "utc_now", lambda: NOW)
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)  # tmp dirs live on a small /tmp
    monkeypatch.setattr(doctor, "DISK_FAIL_BYTES", 0)
    return f


@pytest.fixture
def ready(settings, fake, capsys):
    assert main(["init"]) == 0
    capsys.readouterr()
    return settings


def run_doctor(capsys) -> tuple[int, dict[str, str]]:
    code = main(["doctor"])
    lines = capsys.readouterr().out.splitlines()
    return code, {ln.split(": ", 1)[0]: ln for ln in lines}


def finish(settings, status, at, error=None):
    conn = connect(settings.db_path)
    rid = runs_repo.start_run(conn, trigger="timer", at=at)
    runs_repo.finish_run(conn, rid, status=status, stats={}, at=at, error=error)
    conn.close()


def test_healthy_setup_exits_0(ready, fake, capsys):
    finish(ready, "ok", NOW - timedelta(hours=1))
    code, lines = run_doctor(capsys)
    assert code == 0, lines
    assert lines["✅ config"].endswith("sidereal.toml")
    assert "✅ ollama" in lines and "✅ model qwen3.8:27b" in lines
    assert "✅ last run" in lines and "run 1 ok, 1.0 h ago" in lines["✅ last run"]
    assert lines["✅ run lock"].endswith("free")
    assert lines["✅ sources"].endswith("21 of 21 enabled sources ok")
    assert "⚠ systemd" in lines
    assert fake.closed == [True] and fake.timeout_s == commands.DOCTOR_OLLAMA_TIMEOUT_S
    assert {p for _, p, _ in fake.requests} == {"/api/tags"}  # never loads a model


def test_before_init_fails_and_creates_nothing(settings, fake, capsys):
    code, lines = run_doctor(capsys)
    assert code == 1
    assert "❌ state dir" in lines and "❌ database" in lines
    assert not settings.state_dir.exists() and not settings.db_path.exists()


def test_never_writes_db_or_lock_file(ready, fake, capsys):
    db = ready.db_path
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    run_doctor(capsys)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert not lock.lock_path(ready.state_dir).exists()


def test_missing_model_and_unreachable_ollama(ready, fake, capsys):
    fake.models = ["other:1b"]
    code, lines = run_doctor(capsys)
    assert code == 1 and "missing (ollama pull qwen3.8:27b)" in lines["❌ model qwen3.8:27b"]
    fake.errors["/api/tags"] = httpx.ConnectError("refused")
    code, lines = run_doctor(capsys)
    assert code == 1 and "unreachable (LLMUnavailable)" in lines["❌ ollama"]


def test_no_runs_and_old_run_only_warn(ready, fake, capsys):
    code, lines = run_doctor(capsys)
    assert code == 0 and lines["⚠ last run"].endswith("no runs yet")
    finish(ready, "ok", NOW - timedelta(hours=5))
    code, lines = run_doctor(capsys)
    assert code == 0 and "older than 5 h" in lines["⚠ last run"]


def test_failed_last_run_fails_skipped_ignored(ready, fake, capsys):
    finish(ready, "failed", NOW - timedelta(hours=1), error="RuntimeError: bug")
    conn = connect(ready.db_path)
    runs_repo.mark_skipped(conn, trigger="timer", at=NOW, reason="locked")
    conn.close()
    code, lines = run_doctor(capsys)
    assert code == 1 and lines["❌ last run"].endswith("RuntimeError: bug")


def test_failing_source_fails_stale_warns(ready, fake, capsys):
    finish(ready, "ok", NOW - timedelta(hours=1))
    conn = connect(ready.db_path)
    krebs = sources_repo.get_by_key(conn, "krebs")
    for _ in range(3):
        sources_repo.record_fetch_error(conn, krebs.id, at=NOW, error="FetchHTTPError: HTTP 500")
    blog = sources_repo.get_by_key(conn, "azure-blog")
    for _ in range(6):
        sources_repo.record_fetch_ok(conn, blog.id, at=NOW, etag=None, last_modified=None,
                                     entry_count=0)
    conn.close()
    code, lines = run_doctor(capsys)
    assert code == 1
    assert lines["❌ source krebs"].endswith("failing: FetchHTTPError: HTTP 500")
    assert lines["⚠ source azure-blog"].endswith("empty")
    assert lines["⚠ sources"].endswith("19 of 21 enabled sources ok")


def test_old_schema_fails(ready, fake, capsys):
    conn = sqlite3.connect(ready.db_path)
    conn.execute("DELETE FROM schema_version")
    conn.commit()
    conn.close()
    code, lines = run_doctor(capsys)
    assert code == 1 and "code expects" in lines["❌ database"]


def test_env_file_mode(ready, fake, capsys):
    env = paths.config_dir() / "env"
    env.write_text("SIDEREAL_SMTP_PASSWORD=hunter2\n")
    env.chmod(0o644)
    code, lines = run_doctor(capsys)
    assert code == 1 and "chmod 600" in lines["❌ env file"]
    assert all("hunter2" not in ln for ln in lines.values())
    env.chmod(0o600)
    code, lines = run_doctor(capsys)
    assert code == 0 and "✅ env file" in lines


def test_lock_held_is_reported(ready, fake, capsys):
    with lock.RunLock(lock.lock_path(ready.state_dir)):
        code, lines = run_doctor(capsys)
    assert code == 0 and "run is in progress (pid " in lines["✅ run lock"]


def test_low_disk(ready, fake, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 10**18)
    code, lines = run_doctor(capsys)
    assert code == 0 and "GB free" in lines["⚠ state dir"]
    monkeypatch.setattr(doctor, "DISK_FAIL_BYTES", 10**18)
    code, lines = run_doctor(capsys)
    assert code == 1 and "❌ state dir" in lines


def test_stale_source_uses_newest_item(ready, fake, capsys):
    from tests.pipeline_helpers import add_story, start

    conn = connect(ready.db_path)
    rid = start(conn)
    add_story(conn, rid, source="schneier", at=NOW - timedelta(days=9))
    add_story(conn, rid, source="krebs", at=NOW - timedelta(days=1))
    conn.close()
    code, lines = run_doctor(capsys)
    assert lines["⚠ source schneier"].endswith("stale")
    assert "⚠ source krebs" not in lines

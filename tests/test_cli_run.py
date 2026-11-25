"""``sidereal run`` / ``rescore`` through ``cli.main`` with fixture feeds and a fake Ollama."""

from __future__ import annotations

import httpx
import pytest

from sidereal import commands
from sidereal.cli import main
from sidereal.db import runs_repo
from sidereal.db.connect import connect
from sidereal.pipeline import lock, placement, runner
from tests.pipeline_helpers import NOW, FeedServer, count, ollama_for, smart_ollama


class Clients:
    """Patches ``commands.make_fetcher`` / ``make_ollama``; records instances and closes."""

    def __init__(self, settings, monkeypatch):
        conn = connect(settings.db_path)
        self.feeds = FeedServer(conn)
        conn.close()
        self.fake = smart_ollama()
        self.closed: list[str] = []
        self.made: list[str] = []
        monkeypatch.setattr(commands, "make_fetcher", self._fetcher)
        monkeypatch.setattr(commands, "make_ollama", self._ollama)

    def _track(self, client, name):
        self.made.append(name)
        real = client.aclose

        async def aclose():
            self.closed.append(name)
            await real()

        client.aclose = aclose
        return client

    def _fetcher(self, settings):
        return self._track(self.feeds.fetcher(), "fetcher")

    def _ollama(self, settings, *, timeout_s=None):
        return self._track(ollama_for(self.fake, settings), "ollama")


@pytest.fixture
def clients(settings, monkeypatch, capsys):
    assert main(["init"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(runner, "utc_now", lambda: NOW)
    monkeypatch.setattr(commands, "utc_now", lambda: NOW)
    return Clients(settings, monkeypatch)


def runs(settings):
    conn = connect(settings.db_path)
    try:
        return runs_repo.list_runs(conn)
    finally:
        conn.close()


def test_run_ok_exits_0_and_closes_clients(settings, clients, capsys):
    assert main(["run", "--no-gate"]) == 0
    out = capsys.readouterr().out
    assert "run 1: ok" in out and "buckets:" in out
    [row] = runs(settings)
    assert row.status == "ok" and row.trigger == "manual" and row.stats["gate"] == "skipped"
    assert sorted(clients.closed) == ["fetcher", "ollama"]
    assert not lock.is_held(lock.lock_path(settings.state_dir))


def test_partial_exits_0(settings, clients, capsys):
    clients.feeds.overrides["krebs"] = httpx.Response(500)
    assert main(["run", "--no-gate", "--trigger", "timer"]) == 0
    [row] = runs(settings)
    assert row.status == "partial" and row.trigger == "timer"
    assert "run 1: partial (1 source(s) failed)" in capsys.readouterr().out


def test_failed_run_exits_1(settings, clients, monkeypatch, capsys):
    async def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(runner.ingest, "ingest", boom)
    assert main(["run", "--no-gate"]) == 1
    [row] = runs(settings)
    assert row.status == "failed" and row.error == "RuntimeError: bug"
    assert "run 1: failed (RuntimeError: bug)" in capsys.readouterr().out
    assert sorted(clients.closed) == ["fetcher", "ollama"]


def test_clients_closed_and_lock_released_when_runner_raises(settings, clients, monkeypatch):
    async def crash(*a, **k):
        raise KeyboardInterrupt  # escapes run_once's own except Exception

    monkeypatch.setattr(runner, "run_once", crash)
    with pytest.raises(KeyboardInterrupt):
        main(["run", "--no-gate"])
    assert sorted(clients.closed) == ["fetcher", "ollama"]
    assert not lock.is_held(lock.lock_path(settings.state_dir))


def test_lock_held_records_skipped_and_exits_0(settings, clients, capsys):
    with lock.RunLock(lock.lock_path(settings.state_dir)):
        assert main(["run", "--no-gate", "--trigger", "timer"]) == 0
    [row] = runs(settings)
    assert row.status == "skipped" and row.trigger == "timer"
    assert row.error.startswith("run already in progress")
    assert "run 1: skipped" in capsys.readouterr().out
    assert clients.made == [] and clients.feeds.requests == []


def test_unknown_source_exits_2_without_a_run_row(settings, clients, capsys):
    assert main(["run", "--no-gate", "--source", "nope"]) == 2
    assert "unknown source key 'nope'" in capsys.readouterr().err
    assert runs(settings) == []
    assert sorted(clients.closed) == ["fetcher", "ollama"]


def test_options_passed_to_runner(settings, clients, monkeypatch):
    seen = {}

    async def fake_run_once(settings, conn, **kw):
        seen.update(kw)
        rid = runs_repo.start_run(conn, trigger=kw["trigger"], at=NOW)
        runs_repo.finish_run(conn, rid, status="ok", stats={}, at=NOW)
        return runs_repo.get_run(conn, rid)

    monkeypatch.setattr(runner, "run_once", fake_run_once)
    assert main(["run", "--source", "krebs", "--max-assess", "3"]) == 0
    assert seen["only_source"] == "krebs" and seen["max_assess"] == 3
    assert seen["trigger"] == "manual" and seen["gate"] is not None
    assert main(["run", "--no-gate"]) == 0
    assert seen["gate"] is None and seen["max_assess"] is None and seen["only_source"] is None


@pytest.mark.parametrize("argv", [["--max-assess", "-1"], ["--trigger", "catchup"],
                                  ["--max-assess", "x"]])
def test_bad_options_exit_2(settings, clients, argv):
    with pytest.raises(SystemExit) as exc:
        main(["run", *argv])
    assert exc.value.code == 2


def test_dry_run_prints_counts_and_writes_nothing(settings, clients, capsys):
    assert main(["run", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("dry run (nothing written)")
    assert '"failed": 0' in out and '"new": ' in out
    conn = connect(settings.db_path)
    try:
        assert count(conn, "runs") == count(conn, "stories") == count(conn, "items") == 0
    finally:
        conn.close()
    assert clients.made == ["fetcher"] and clients.closed == ["fetcher"]
    assert clients.fake.requests == []
    assert len(clients.feeds.requests) >= 21


def test_dry_run_ignores_the_lock_and_rejects_unknown_source(settings, clients, capsys):
    with lock.RunLock(lock.lock_path(settings.state_dir)):
        assert main(["run", "--dry-run", "--source", "krebs"]) == 0
        assert main(["run", "--dry-run", "--source", "nope"]) == 2
    assert runs(settings) == []


def test_rescore_prints_result(settings, clients, monkeypatch, capsys):
    seen = {}

    def fake(conn, cfg, *, day=None):
        seen["day"], seen["cfg"] = day, cfg
        return {"rescored": 2, "buckets": {"top": 1, "side": 1}, "days": {"2026-11-25"}}

    monkeypatch.setattr(placement, "rescore", fake)
    assert main(["rescore", "--day", "2026-11-25"]) == 0
    out = capsys.readouterr().out
    assert "rescored: 2" in out and "days: 2026-11-25" in out
    assert seen == {"day": "2026-11-25", "cfg": settings.scoring}


def test_rescore_real_empty_db(settings, clients, capsys):
    assert main(["rescore"]) == 0
    assert "rescored: 0" in capsys.readouterr().out


def test_rescore_bad_day_exits_2(settings, clients, capsys):
    assert main(["rescore", "--day", "25.11.2026"]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_rescore_refuses_while_a_run_holds_the_lock(settings, clients, capsys):
    with lock.RunLock(lock.lock_path(settings.state_dir)):
        assert main(["rescore"]) == 1
    assert "run already in progress" in capsys.readouterr().err
    assert runs(settings) == []

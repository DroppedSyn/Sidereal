"""Tests for the GPU politeness gate (plan §7.5): fake clock, fake runs dir, fake probe."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sidereal.config import GateSettings
from sidereal.llm.gate import Gate, GateResult
from sidereal.llm.ollama import LLMUnavailable, ProbeResult


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []
        self.on_sleep = None  # optional callable(n) run after the n-th sleep (1-based)

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))


class FakeProbe:
    """Replies in order; the last one repeats."""

    def __init__(self, replies: list[ProbeResult | Exception]) -> None:
        self.replies = replies
        self.calls = 0

    async def __call__(self) -> ProbeResult:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        if isinstance(reply, Exception):
            raise reply
        return reply


def state(runs: Path, name: str, text: str) -> None:
    (runs / name).mkdir(parents=True, exist_ok=True)
    (runs / name / "state").write_text(text + "\n")


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    d = tmp_path / "runs"
    d.mkdir()
    return d


@pytest.fixture
def clk() -> FakeClock:
    return FakeClock()


def make(runs_dir: Path | None, probe, clk: FakeClock, **kw) -> Gate:
    kw.setdefault("poll_seconds", 10.0)
    kw.setdefault("max_wait_minutes", 1.0)
    return Gate(runs_dir=runs_dir, probe=probe, clock=clk, sleep=clk.sleep, **kw)


# --- pi-bridge activity ---

async def test_idle(runs, clk):
    state(runs, "r1", "done")
    probe = FakeProbe([ProbeResult(100, 0)])
    result = await make(runs, probe, clk).wait()
    assert result == GateResult(0.0, False, 1, "idle")
    assert clk.sleeps == []
    assert probe.calls == 1


async def test_pi_running_then_done(runs, clk):
    state(runs, "r1", "running")
    probe = FakeProbe([ProbeResult(100, 0)])

    def on_sleep(n: int) -> None:
        if n == 2:
            state(runs, "r1", "done")

    clk.on_sleep = on_sleep
    result = await make(runs, probe, clk).wait()
    assert result == GateResult(20.0, False, 3, "idle")
    assert clk.sleeps == [10.0, 10.0]
    assert probe.calls == 1  # only on the third check


@pytest.mark.parametrize("word", ["preparing", "queued", "done", "failed", "timeout", "stopped"])
def test_non_running_state_not_busy(runs, clk, word):
    state(runs, "r1", word)
    assert make(runs, None, clk).pi_busy() is False


def test_running_among_others_is_busy(runs, clk):
    for i, word in enumerate(["preparing", "queued", "done", "failed", "timeout", "stopped"]):
        state(runs, f"r{i}", word)
    state(runs, "r9", "running")
    assert make(runs, None, clk).pi_busy() is True


def test_running_with_whitespace_is_busy(runs, clk):
    state(runs, "r1", "  running\n")
    assert make(runs, None, clk).pi_busy() is True


def test_missing_runs_dir_not_busy(tmp_path, clk):
    assert make(tmp_path / "nope", None, clk).pi_busy() is False
    assert make(None, None, clk).pi_busy() is False


def test_garbage_state_ignored(runs, clk):
    (runs / "r1").mkdir()
    (runs / "r1" / "state").write_bytes(b"\xff\xfe\x00")
    (runs / "r2" / "state").mkdir(parents=True)  # state is a directory
    state(runs, "r3", "done")
    state(runs, "r4", "running and more")
    (runs / "stray_file").write_text("running\n")
    assert make(runs, None, clk).pi_busy() is False


# --- probe ---

async def test_probe_slow_is_busy(clk):
    probe = FakeProbe([ProbeResult(20_001, 0)])
    assert await make(None, probe, clk).busy_reason() == "probe_slow"


async def test_probe_at_threshold_not_busy(clk):
    probe = FakeProbe([ProbeResult(20_000, 0)])
    assert await make(None, probe, clk).busy_reason() is None


async def test_probe_load_time_excluded(clk):
    # 25 s total but 10 s of it was loading: 15 s of real work -> not busy
    assert await make(None, FakeProbe([ProbeResult(25_000, 10_000)]), clk).busy_reason() is None
    # 35 s total, 10 s loading: 25 s of real work -> busy
    busy = make(None, FakeProbe([ProbeResult(35_000, 10_000)]), clk)
    assert await busy.busy_reason() == "probe_slow"


async def test_probe_threshold_is_configurable(clk):
    probe = FakeProbe([ProbeResult(6_000, 0)])
    assert await make(None, probe, clk, probe_busy_seconds=5.0).busy_reason() == "probe_slow"
    assert await make(None, probe, clk, probe_busy_seconds=6.0).busy_reason() is None


async def test_probe_skipped_while_pi_running(runs, clk):
    state(runs, "r1", "running")
    probe = FakeProbe([ProbeResult(100, 0)])
    assert await make(runs, probe, clk).busy_reason() == "pi_bridge"
    assert probe.calls == 0


async def test_probe_error_not_busy(clk, caplog):
    probe = FakeProbe([LLMUnavailable("ollama /api/generate: timed out")])
    with caplog.at_level(logging.WARNING, logger="sidereal.llm.gate"):
        result = await make(None, probe, clk).wait()
    assert result == GateResult(0.0, False, 1, "idle")
    assert probe.calls == 1
    assert "LLMUnavailable" in caplog.text
    assert "timed out" not in caplog.text  # type name only


async def test_probe_slow_then_fast_waits(clk):
    slow = ProbeResult(30_000, 0)
    probe = FakeProbe([slow, slow, ProbeResult(100, 0)])
    result = await make(None, probe, clk).wait()
    assert result == GateResult(20.0, False, 3, "idle")
    assert clk.sleeps == [10.0, 10.0]
    assert probe.calls == 3


async def test_no_probe(clk):
    assert await make(None, None, clk).wait() == GateResult(0.0, False, 1, "idle")


# --- wait loop ---

async def test_timeout(runs, clk, caplog):
    state(runs, "r1", "running")
    with caplog.at_level(logging.WARNING, logger="sidereal.llm.gate"):
        result = await make(runs, None, clk).wait()
    assert result == GateResult(60.0, True, 7, "timeout")
    assert clk.sleeps == [10.0] * 6
    assert "gate_timeout" in caplog.text


async def test_timeout_last_sleep_shortened(runs, clk):
    state(runs, "r1", "running")
    result = await make(runs, None, clk, poll_seconds=25.0).wait()
    assert clk.sleeps == [25.0, 25.0, 10.0]
    assert result == GateResult(60.0, True, 4, "timeout")


async def test_timeout_when_probe_always_slow(clk):
    probe = FakeProbe([ProbeResult(30_000, 0)])
    result = await make(None, probe, clk, poll_seconds=30.0, max_wait_minutes=2.0).wait()
    assert result == GateResult(120.0, True, 5, "timeout")
    assert clk.sleeps == [30.0] * 4
    assert probe.calls == 5


async def test_skip(runs, clk):
    state(runs, "r1", "running")
    probe = FakeProbe([ProbeResult(100, 0)])
    result = await make(runs, probe, clk).wait(skip=True)
    assert result == GateResult(0.0, False, 0, "skipped")
    assert probe.calls == 0
    assert clk.sleeps == []


# --- from_settings ---

async def test_from_settings_uses_every_setting(runs):
    gs = GateSettings(
        pi_bridge_runs_dir=str(runs),
        probe_busy_seconds=7.0,
        poll_seconds=5.0,
        max_wait_minutes=2.0,
    )
    clk = FakeClock()
    probe = FakeProbe([ProbeResult(100, 0)])
    gate = Gate.from_settings(gs, probe=probe, clock=clk, sleep=clk.sleep)
    assert gate.runs_dir == runs
    assert gate.probe is probe
    assert gate.probe_busy_seconds == 7.0
    assert gate.poll_seconds == 5.0
    assert gate.max_wait_minutes == 2.0
    # and they drive behaviour: running pi -> 5 s polls until 120 s
    state(runs, "r1", "running")
    result = await gate.wait()
    assert result == GateResult(120.0, True, 25, "timeout")
    assert clk.sleeps == [5.0] * 24


def test_from_settings_defaults():
    gate = Gate.from_settings(GateSettings(), probe=None)
    assert gate.runs_dir == Path.home() / ".pi-bridge" / "runs"
    assert (gate.probe_busy_seconds, gate.poll_seconds, gate.max_wait_minutes) == (20.0, 60.0, 90.0)


def test_from_settings_empty_string_disables_pi_check():
    assert Gate.from_settings(GateSettings(pi_bridge_runs_dir=""), probe=None).runs_dir is None


def test_from_settings_tilde():
    gate = Gate.from_settings(GateSettings(pi_bridge_runs_dir="~/x"), probe=None)
    assert gate.runs_dir == Path.home() / "x"

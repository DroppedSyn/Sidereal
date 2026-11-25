"""GPU politeness gate: check pi-bridge activity and probe Ollama before running (plan §7.5).

Busy signals, checked in order:
  1. pi-bridge activity on this VM (any run dir whose state is "running")
  2. Latency probe: a 1-token /api/generate on the triage model; if > probe_busy_seconds
     the host is treated as busy.

Policy: busy → wait poll_seconds and re-check, up to max_wait_minutes, then run anyway
and log gate_timeout. The run record stores gate_wait_s. ``sidereal run --no-gate`` skips it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sidereal.config import GateSettings
from sidereal.llm.ollama import LLMError, ProbeResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateResult:
    waited_s: float   # clock() at return minus clock() at start
    timed_out: bool
    checks: int       # number of busy checks made (0 when skipped)
    reason: str       # "skipped" | "idle" | "timeout"


class Gate:
    def __init__(
        self,
        *,
        runs_dir: Path | None,
        probe: Callable[[], Awaitable[ProbeResult]] | None,
        probe_busy_seconds: float = 20.0,
        poll_seconds: float = 60.0,
        max_wait_minutes: float = 90.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.runs_dir = runs_dir
        self.probe = probe
        self.probe_busy_seconds = probe_busy_seconds
        self.poll_seconds = poll_seconds
        self.max_wait_minutes = max_wait_minutes
        self._clock = clock
        self._sleep = sleep

    @classmethod
    def from_settings(
        cls,
        gs: GateSettings,
        *,
        probe: Callable[[], Awaitable[ProbeResult]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> Gate:
        raw = gs.pi_bridge_runs_dir
        if raw == "":
            runs_dir: Path | None = None
        else:
            runs_dir = Path(raw).expanduser()
        return cls(
            runs_dir=runs_dir,
            probe=probe,
            probe_busy_seconds=gs.probe_busy_seconds,
            poll_seconds=gs.poll_seconds,
            max_wait_minutes=gs.max_wait_minutes,
            clock=clock,
            sleep=sleep,
        )

    def pi_busy(self) -> bool:
        """Check if any pi-bridge run is currently running."""
        if self.runs_dir is None or not self.runs_dir.is_dir():
            return False
        for state_file in self.runs_dir.glob("*/state"):
            try:
                text = state_file.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            if text.strip() == "running":
                return True
        return False

    async def busy_reason(self) -> str | None:
        """Return a reason string if busy, else None."""
        if self.pi_busy():
            return "pi_bridge"
        if self.probe is None:
            return None
        try:
            r = await self.probe()
        except LLMError as exc:
            log.warning("gate probe failed: %s", type(exc).__name__)
            return None
        if (r.total_ms - r.load_ms) / 1000 > self.probe_busy_seconds:
            return "probe_slow"
        return None

    async def wait(self, *, skip: bool = False) -> GateResult:
        """Wait until the GPU is idle, or time out."""
        if skip:
            return GateResult(0.0, False, 0, "skipped")

        start = self._clock()
        max_s = self.max_wait_minutes * 60
        checks = 0

        while True:
            checks += 1
            reason = await self.busy_reason()
            waited = self._clock() - start

            if reason is None:
                return GateResult(waited, False, checks, "idle")

            if waited >= max_s:
                log.warning("gate_timeout after %.0f s (%d checks)", waited, checks)
                return GateResult(waited, True, checks, "timeout")

            log.info("busy: %s (check %d)", reason, checks)
            remaining = max_s - waited
            await self._sleep(min(self.poll_seconds, remaining))

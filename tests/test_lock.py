"""Tests for src/sidereal/pipeline/lock.py — run.lock fcntl.flock."""

from __future__ import annotations

import os
import select
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidereal.pipeline.lock import (
    LOCK_FILENAME,
    LockInfo,
    RunLock,
    RunLocked,
    held_by,
    is_held,
    lock_path,
    read_info,
)

T0 = datetime(2026, 11, 25, 8, 0, 0, 123456, tzinfo=UTC)

CHILD = (
    "import sys\n"
    "from pathlib import Path\n"
    "from sidereal.pipeline.lock import RunLock\n"
    "with RunLock(Path(sys.argv[1])):\n"
    "    print('locked', flush=True)\n"
    "    sys.stdin.read()\n"
)


@pytest.fixture
def start_holder():
    """Start child processes holding the lock; any still alive at teardown are killed."""
    procs = []

    def start(path):
        proc = subprocess.Popen(
            [sys.executable, "-c", CHILD, str(path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        procs.append(proc)
        ready, _, _ = select.select([proc.stdout], [], [], 10)
        assert ready, "holder did not report 'locked' within 10 s"
        assert proc.stdout.readline().strip() == "locked"
        return proc

    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)
        proc.stdin.close()
        proc.stdout.close()


@pytest.fixture
def p(tmp_path):
    return tmp_path / "run.lock"


# ── 1 ───────────────────────────────────────────────────────────────
def test_lock_path(p):
    assert lock_path(p.parent) == p.parent / LOCK_FILENAME


# ── 2 ───────────────────────────────────────────────────────────────
def test_acquire_writes_pid_and_time(p):
    with RunLock(p, now=lambda: T0) as lk:
        assert lk.held is True
    assert p.read_text() == f"{os.getpid()} 2026-11-25T08:00:00Z\n"


# ── 3 ───────────────────────────────────────────────────────────────
def test_release_keeps_file(p):
    with RunLock(p, now=lambda: T0) as lk:
        held_text = p.read_text()
        assert lk.held is True
    assert p.exists()
    assert lk.held is False
    assert p.read_text() == held_text == f"{os.getpid()} 2026-11-25T08:00:00Z\n"


# ── 4 ───────────────────────────────────────────────────────────────
def test_creates_parent_dir(p):
    p2 = p.parent / "a" / "b" / "run.lock"
    with RunLock(p2):
        assert p2.exists()


# ── 5 ───────────────────────────────────────────────────────────────
def test_second_lock_same_process_conflicts(p):
    a = RunLock(p)
    a.acquire()
    with pytest.raises(RunLocked, match="run already in progress") as ei:
        RunLock(p).acquire()
    assert ei.value.pid == os.getpid()
    assert ei.value.path == p
    a.release()
    with RunLock(p) as b:
        assert b.held is True


# ── 6 ───────────────────────────────────────────────────────────────
def test_conflict_does_not_touch_holders_file(p):
    lock_a = RunLock(p, now=lambda: T0)
    lock_a.acquire()
    original = p.read_text()
    with pytest.raises(RunLocked, match="pid"):
        RunLock(p, now=lambda: T0 + timedelta(hours=1)).acquire()
    assert p.read_text() == original
    lock_a.release()


# ── 7 ───────────────────────────────────────────────────────────────
def test_other_process_holds_lock(p, start_holder):
    proc = start_holder(p)
    with pytest.raises(RunLocked, match=f"pid {proc.pid}") as ei:
        RunLock(p).acquire()
    assert ei.value.pid == proc.pid
    assert is_held(p) is True
    assert held_by(p) == proc.pid


# ── 8 ───────────────────────────────────────────────────────────────
def test_acquire_after_holder_exits(p, start_holder):
    proc = start_holder(p)
    proc.stdin.close()
    assert proc.wait(timeout=10) == 0
    with RunLock(p) as lk:
        assert lk.held is True
        assert held_by(p) == os.getpid()


# ── 9 ───────────────────────────────────────────────────────────────
def test_acquire_after_holder_killed(p, start_holder):
    proc = start_holder(p)
    proc.kill()
    proc.wait(timeout=10)
    assert held_by(p) == proc.pid
    assert is_held(p) is False
    with RunLock(p) as lk:
        assert lk.held is True
        assert held_by(p) == os.getpid()


# ── 10 ──────────────────────────────────────────────────────────────
def test_garbage_file_without_holder(p):
    p.write_text("not a pid\x00\nmore junk\n")
    assert held_by(p) is None
    with RunLock(p, now=lambda: T0):
        assert p.read_text() == f"{os.getpid()} 2026-11-25T08:00:00Z\n"


# ── 11 ──────────────────────────────────────────────────────────────
def test_longer_old_content_truncated(p):
    p.write_text("9" * 200 + " x\n")
    with RunLock(p, now=lambda: T0):
        assert p.read_text() == f"{os.getpid()} 2026-11-25T08:00:00Z\n"


# ── 12 ──────────────────────────────────────────────────────────────
def test_acquire_twice_same_object(p):
    lk = RunLock(p)
    lk.acquire()
    with pytest.raises(RuntimeError, match="already acquired"):
        lk.acquire()
    lk.release()


# ── 13 ──────────────────────────────────────────────────────────────
def test_release_is_idempotent(p):
    lk = RunLock(p)
    lk.release()  # without acquire is fine
    lk.acquire()
    lk.release()
    lk.release()
    assert lk.held is False


# ── 14 ──────────────────────────────────────────────────────────────
def test_exit_does_not_suppress(p):
    lk = RunLock(p)
    with pytest.raises(ValueError, match="boom"):
        with lk:
            raise ValueError("boom")
    assert lk.held is False
    with RunLock(p) as again:
        assert again.held is True


# ── 15 ──────────────────────────────────────────────────────────────
def test_failed_acquire_leaves_no_fd_open(p):
    a = RunLock(p)
    a.acquire()
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(5):
        with pytest.raises(RunLocked, match="in progress"):
            RunLock(p).acquire()
    after = len(os.listdir("/proc/self/fd"))
    assert after == before
    a.release()


# ── 16 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "123 2026-11-25T08:00:00Z\n",
            LockInfo(pid=123, started_at="2026-11-25T08:00:00Z"),
        ),
        ("", None),
        ("abc 2026\n", None),
        ("123\n", None),
        ("123 a b\n", None),
        ("0 x\n", None),
        ("-5 x\n", None),
        ("\xff\xfe junk", None),
    ],
)
def test_read_info(p, text, expected):
    p.write_text(text, encoding="latin-1")
    assert read_info(p) == expected


# ── 17 ──────────────────────────────────────────────────────────────
def test_missing_file(p):
    assert read_info(p) is None
    assert held_by(p) is None
    assert is_held(p) is False
    assert p.exists() is False


# ── 18 ──────────────────────────────────────────────────────────────
def test_is_held_in_process(p):
    assert is_held(p) is False
    lk = RunLock(p)
    lk.acquire()
    assert is_held(p) is True
    lk.release()
    assert is_held(p) is False
    # is_held leaves content unchanged
    lk.acquire()
    content = p.read_text()
    is_held(p)
    assert p.read_text() == content
    lk.release()


# ── 19 ──────────────────────────────────────────────────────────────
def test_message_without_pid():
    path = Path("/x/run.lock")
    assert str(RunLocked(path, None)) == "run already in progress (lock /x/run.lock)"
    assert str(RunLocked(path, 42)) == "run already in progress (lock /x/run.lock, pid 42)"


# ── 20 (review) ─────────────────────────────────────────────────────
def test_is_held_leaves_no_fd_or_lock(p):
    p.write_text("123 2026-11-25T08:00:00Z\n")
    before = len(os.listdir("/proc/self/fd"))
    assert is_held(p) is False
    with RunLock(p) as lk:
        assert is_held(p) is True
    assert len(os.listdir("/proc/self/fd")) == before
    assert lk.held is False

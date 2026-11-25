"""Run lock: fcntl.flock on ``$STATE/run.lock`` so that runs never overlap.

A second run sees the lock is taken and gives up.  The kernel releases a
flock when the holding process dies, so a leftover file from a crashed run
is harmless — never treat the file's existence or content as "locked".
Only the flock decides.

Verified on Linux (Python 3.13): two ``os.open`` fds on the same file in ONE
process conflict: the second ``flock(LOCK_EX | LOCK_NB)`` raises
``BlockingIOError`` (errno 11) until the first is unlocked; a read-only
(``O_RDONLY``) fd is blocked the same way and can take the lock.
"""

from __future__ import annotations

import fcntl
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sidereal.timeutil import iso_z, utc_now

logger = logging.getLogger(__name__)

LOCK_FILENAME = "run.lock"


def lock_path(state_dir: Path) -> Path:
    """``state_dir / LOCK_FILENAME``."""
    return state_dir / LOCK_FILENAME


class RunLocked(Exception):
    """Another process (or another open file in this process) holds the run lock."""

    def __init__(self, path: Path, pid: int | None) -> None:
        self.path = path
        self.pid = pid
        if pid is not None:
            super().__init__(f"run already in progress (lock {path}, pid {pid})")
        else:
            super().__init__(f"run already in progress (lock {path})")


@dataclass(frozen=True)
class LockInfo:
    pid: int
    started_at: str  # the iso_z text as written, e.g. "2026-11-25T08:00:00Z"


def read_info(path: Path) -> LockInfo | None:
    """Read the file WITHOUT locking.

    ``None`` if the file is missing/unreadable (``OSError``), or the bytes are
    not ASCII (``UnicodeDecodeError``), or the content is not exactly one line
    ``'<pid> <started_at>'`` (after ``.strip()``: ``split()`` gives exactly 2
    parts, the first is all ASCII digits and ``int > 0``).  Never raises.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    stripped = text.strip()
    parts = stripped.split()
    if len(parts) != 2:
        return None
    pid_str, started_at = parts
    if not pid_str.isascii() or not pid_str.isdigit():
        return None
    pid = int(pid_str)
    if pid <= 0:
        return None
    return LockInfo(pid=pid, started_at=started_at)


def held_by(path: Path) -> int | None:
    """``read_info(path).pid`` or ``None``.  The file may be stale."""
    info = read_info(path)
    if info is None:
        return None
    return info.pid


def is_held(path: Path) -> bool:
    """True if some open file currently holds the flock.

    Missing file → ``False`` (do not create it).  A read-only fd may take
    flock on Linux.  Never writes the file.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


class RunLock:
    """Context-managed ``fcntl.flock`` on a single file."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.path = Path(path)
        self._now = now
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        """``True`` while this object holds the lock."""
        return self._fd is not None

    def acquire(self) -> None:
        """Take an exclusive ``LOCK_EX`` lock on *self.path*."""
        if self._fd is not None:
            raise RuntimeError("run lock already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise RunLocked(self.path, held_by(self.path)) from None
        except OSError:
            os.close(fd)
            raise
        # Lock held — write pid + timestamp.
        try:
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, f"{os.getpid()} {iso_z(self._now())}\n".encode("ascii"))
            os.fsync(fd)
        except OSError:
            # If writing fails, release the flock and close.
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
            raise
        self._fd = fd

    def release(self) -> None:
        """Release the flock.  The file is LEFT IN PLACE."""
        if self._fd is None:
            return
        fd = self._fd
        self._fd = None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)

    def __enter__(self) -> RunLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()  # returns None: never suppresses

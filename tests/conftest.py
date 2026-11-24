"""Shared fixtures. Every test runs with temp config/state dirs and no network (rule 7)."""

from __future__ import annotations

import socket
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from sidereal.config import Settings, load_settings
from sidereal.db.connect import connect
from sidereal.db.migrations import apply_migrations

FIXTURES = Path(__file__).parent / "fixtures"
TEST_CONFIG = """\
[web]
# TestClient sends Host: testserver; tests allow it here, the default stays loopback-only.
allowed_hosts = ["127.0.0.1", "localhost", "testserver"]
"""


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config and state at tmp dirs and drop any SIDEREAL_* variables from the shell."""
    import os

    for name in list(os.environ):
        if name.startswith("SIDEREAL_"):
            monkeypatch.delenv(name)
    home = tmp_path / "home"
    (home / ".config" / "sidereal").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    return home


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test tries to resolve or connect to anything (AF_UNIX stays allowed)."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("network access is disabled in tests (plan rule 7)")

    real_connect = socket.socket.connect

    def guarded_connect(self: socket.socket, address: object) -> None:
        if self.family == socket.AF_UNIX:
            return real_connect(self, address)
        refuse()

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def config_file(isolated_env: Path) -> Path:
    path = isolated_env / ".config" / "sidereal" / "sidereal.toml"
    path.write_text(TEST_CONFIG)
    return path


@pytest.fixture
def settings(config_file: Path) -> Settings:
    """Settings from the test config: state under the tmp HOME, `testserver` an allowed host."""
    return load_settings()


@pytest.fixture
def db(settings: Settings) -> Iterator[sqlite3.Connection]:
    """A migrated, empty database in the tmp state dir."""
    conn = connect(settings.db_path)
    apply_migrations(conn)
    yield conn
    conn.close()

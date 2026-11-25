"""Shared helpers for the M25 auth tests: a fast Argon2 hasher, users, an auth-on app."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.auth import passwords
from sidereal.bootstrap import migrate
from sidereal.config import Settings, load_settings
from sidereal.db import users_repo
from sidereal.db.connect import Connection, connect

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)
ORIGIN = "http://testserver:8470"
WRITE = {"X-Sidereal": "1", "Origin": ORIGIN}
PASSWORD = "correct horse battery"


@pytest.fixture
def fast_hasher(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Argon2id with minimal cost: same code paths, milliseconds per hash."""
    monkeypatch.setattr(passwords, "_hasher",
                        PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))
    passwords._dummy_hash.cache_clear()
    yield
    passwords._dummy_hash.cache_clear()


def auth_settings(config_file: Path, monkeypatch: pytest.MonkeyPatch, **auth: object) -> Settings:
    monkeypatch.setenv("SIDEREAL_AUTH__MODE", "on")
    for key, value in auth.items():
        monkeypatch.setenv(f"SIDEREAL_AUTH__{key.upper()}", str(value).lower())
    s = load_settings()
    migrate(s)
    return s


def add_user(conn: Connection, name: str = "owner", password: str = PASSWORD) -> int:
    return users_repo.add_user(conn, name, passwords.hash_password(password), now=NOW)


def open_conn(settings: Settings) -> Connection:
    return connect(settings.db_path)


def make_client(settings: Settings, tmp_path: Path, *, base_url: str = ORIGIN) -> TestClient:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<!doctype html><title>Sidereal</title>")
    return TestClient(create_app(settings, dist_dir=dist), base_url=base_url)


def login(client: TestClient, name: str = "owner", password: str = PASSWORD, **extra: object):
    return client.post("/api/auth/login", headers=WRITE,
                       json={"username": name, "password": password, **extra})

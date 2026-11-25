"""Rule 9 with real users (M25): ``serve`` counts active users before binding."""

from __future__ import annotations

import pytest
import uvicorn

from sidereal.api.bind import UnsafeBindError, check_bind, count_users
from sidereal.cli import main
from sidereal.db.connect import connect
from tests.auth_helpers import add_user, auth_settings, fast_hasher  # noqa: F401

pytestmark = pytest.mark.usefixtures("fast_hasher")


@pytest.fixture
def served(monkeypatch):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append(kw))
    return calls


def test_count_users_without_db(settings):
    assert count_users(settings) == 0
    assert not settings.db_path.exists()


def test_bind_refused_with_auth_on_and_no_user(config_file, monkeypatch, served, capsys):
    s = auth_settings(config_file, monkeypatch)
    with pytest.raises(UnsafeBindError, match="no user"):
        check_bind("192.168.1.20", s, user_count=count_users(s))
    assert main(["serve", "--host", "192.168.1.20"]) == 2
    assert "no user exists" in capsys.readouterr().err
    assert served == []


def test_bind_allowed_with_auth_on_and_a_user(config_file, monkeypatch, served):
    s = auth_settings(config_file, monkeypatch)
    conn = connect(s.db_path)
    add_user(conn)
    conn.close()
    check_bind("192.168.1.20", s, user_count=count_users(s))
    assert main(["serve", "--host", "192.168.1.20"]) == 0
    assert served == [{"host": "192.168.1.20", "port": 8470, "proxy_headers": False}]


def test_disabled_user_does_not_count(config_file, monkeypatch, served):
    s = auth_settings(config_file, monkeypatch)
    conn = connect(s.db_path)
    add_user(conn)
    conn.execute("UPDATE users SET disabled = 1")
    conn.commit()
    conn.close()
    assert count_users(s) == 0
    assert main(["serve", "--host", "192.168.1.20"]) == 2


def test_users_do_not_help_with_auth_off(settings, served, capsys, monkeypatch):
    from sidereal.bootstrap import migrate

    migrate(settings)
    conn = connect(settings.db_path)
    add_user(conn)
    conn.close()
    assert main(["serve", "--host", "0.0.0.0"]) == 2
    assert "auth.mode is off" in capsys.readouterr().err
    # the test config's `testserver` host counts as exposure since M30: loopback names only
    monkeypatch.setenv("SIDEREAL_WEB__ALLOWED_HOSTS", '["127.0.0.1", "localhost"]')
    assert main(["serve"]) == 0  # loopback default
    assert served[0]["host"] == "127.0.0.1"

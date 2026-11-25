"""``sidereal user add|passwd|list|delete|totp`` (M25): passwords only via getpass, never echoed."""

from __future__ import annotations

import builtins
import getpass
import logging
import time

import pytest

from sidereal.auth import passwords, sessions, totp
from sidereal.cli import main
from sidereal.db import users_repo
from sidereal.db.connect import connect
from tests.auth_helpers import NOW, fast_hasher  # noqa: F401

pytestmark = pytest.mark.usefixtures("fast_hasher")
SECRET = "a long secret passphrase"


@pytest.fixture
def prompts(monkeypatch):
    """Answers for getpass (in order); input() is forbidden unless a test allows it."""
    answers: list[str] = []
    asked: list[str] = []

    def fake_getpass(prompt: str = "Password: ", stream=None) -> str:
        asked.append(prompt)
        return answers.pop(0)

    def no_input(prompt: str = "") -> str:
        raise AssertionError("input() used where getpass was expected")

    monkeypatch.setattr(getpass, "getpass", fake_getpass)
    monkeypatch.setattr(builtins, "input", no_input)
    return answers, asked


def _conn(settings):
    return connect(settings.db_path)


def _all_output(capsys, caplog) -> str:
    cap = capsys.readouterr()
    return cap.out + cap.err + caplog.text


def test_add_prompts_twice_and_never_echoes(settings, prompts, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    answers, asked = prompts
    answers += [SECRET, SECRET]
    assert main(["user", "add", "Owner"]) == 0
    assert asked == ["New password: ", "Repeat password: "]
    assert SECRET not in _all_output(capsys, caplog)
    conn = _conn(settings)
    u = users_repo.get_by_username(conn, "owner")
    assert u is not None and u.pw_hash.startswith("$argon2id$")
    assert passwords.verify(u.pw_hash, SECRET)
    assert SECRET not in "\n".join(conn.iterdump())
    conn.close()


def test_add_mismatch_or_weak_creates_nothing(settings, prompts, capsys, caplog):
    answers, _ = prompts
    answers += [SECRET, SECRET + "x"]
    assert main(["user", "add", "owner"]) == 1
    answers += ["too short"]
    assert main(["user", "add", "owner"]) == 1
    out = _all_output(capsys, caplog)
    assert "do not match" in out and "at least 12" in out
    assert SECRET not in out and "too short" not in out
    conn = _conn(settings)
    assert users_repo.count_active_users(conn) == 0
    conn.close()


def test_add_rejects_bad_name_and_duplicate(settings, prompts, capsys):
    answers, _ = prompts
    assert main(["user", "add", "bad name"]) == 2
    answers += [SECRET, SECRET]
    assert main(["user", "add", "owner"]) == 0
    assert main(["user", "add", "OWNER"]) == 1  # no prompt: refused before asking
    assert "already exists" in capsys.readouterr().err


def test_password_is_never_accepted_on_argv(settings, prompts, capsys):
    with pytest.raises(SystemExit) as e:
        main(["user", "add", "owner", SECRET])
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        main(["user", "add", "owner", "--password", SECRET])


def _add(prompts, name="owner"):
    answers, _ = prompts
    answers += [SECRET, SECRET]
    assert main(["user", "add", name]) == 0


def test_passwd_changes_hash_and_ends_sessions(settings, prompts, capsys, caplog):
    _add(prompts)
    conn = _conn(settings)
    sessions.create(conn, 1, now=NOW, user_agent=None, ip=None)
    old = users_repo.get_user(conn, 1).pw_hash
    answers, _ = prompts
    answers += ["another long secret", "another long secret"]
    assert main(["user", "passwd", "owner"]) == 0
    assert "1 session(s) ended" in capsys.readouterr().out
    new = users_repo.get_user(conn, 1).pw_hash
    assert new != old and passwords.verify(new, "another long secret")
    assert users_repo.count_sessions(conn, 1) == 0
    conn.close()
    assert main(["user", "passwd", "nobody"]) == 1
    assert "another long secret" not in _all_output(capsys, caplog)


def test_list_and_delete(settings, prompts, capsys):
    _add(prompts)
    _add(prompts, "alice")
    capsys.readouterr()
    assert main(["user", "list"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("alice ") and "owner " in out
    assert "no-totp" in out and "argon2" not in out
    assert main(["user", "delete", "alice"]) == 0
    assert main(["user", "delete", "alice"]) == 1
    capsys.readouterr()
    main(["user", "list"])
    assert "alice" not in capsys.readouterr().out


def test_list_empty(settings, prompts, capsys):
    assert main(["user", "list"]) == 0
    assert "no users" in capsys.readouterr().out


def test_totp_on_needs_a_valid_code_then_off(settings, prompts, monkeypatch, capsys):
    _add(prompts)
    secret = totp.new_secret()
    monkeypatch.setattr(totp, "new_secret", lambda: secret)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "000000")
    code_ok = totp.code_at(secret, time.time())
    if code_ok == "000000":  # pragma: no cover - 1 in a million
        pytest.skip("random code collided")
    assert main(["user", "totp", "owner"]) == 1
    conn = _conn(settings)
    assert users_repo.get_user(conn, 1).totp_secret is None
    monkeypatch.setattr(builtins, "input", lambda prompt="": totp.code_at(
        secret, time.time()))
    assert main(["user", "totp", "owner"]) == 0
    assert users_repo.get_user(conn, 1).totp_secret == secret
    assert f"otpauth://totp/Sidereal:owner?secret={secret}" in capsys.readouterr().out
    assert main(["user", "totp", "owner", "--off"]) == 0
    assert users_repo.get_user(conn, 1).totp_secret is None
    conn.close()


def test_user_not_a_planned_stub(settings, prompts, capsys):
    assert main(["user", "list"]) == 0
    assert "not implemented" not in capsys.readouterr().err

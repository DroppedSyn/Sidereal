"""``sidereal user add|passwd|list|delete|totp`` (plan §9.3, §11.2).

Passwords are read only with ``getpass`` (no echo), twice, and never accepted on the command line
or printed. The first account is created here: there is no default account and no sign-up API.
"""

from __future__ import annotations

import argparse
import getpass
import time

from sidereal.auth import passwords, totp
from sidereal.auth.login import normalize_username, valid_username
from sidereal.config import Settings
from sidereal.db import users_repo
from sidereal.db.connect import Connection, connect
from sidereal.timeutil import utc_now

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2


def _out(text: str) -> None:
    from sidereal.cli import out

    out(text)


def _err(text: str) -> None:
    from sidereal.cli import err

    err(text)


def read_new_password() -> str | None:
    """Prompt twice without echo; None (after a message) on mismatch or a weak password."""
    first = getpass.getpass("New password: ")
    try:
        passwords.check_policy(first)
    except passwords.WeakPassword as exc:
        _err(f"error: {exc}")
        return None
    if getpass.getpass("Repeat password: ") != first:
        _err("error: the passwords do not match")
        return None
    return first


def _user(conn: Connection, name: str) -> users_repo.UserRow | None:
    user = users_repo.get_by_username(conn, normalize_username(name))
    if user is None:
        _err(f"error: no user {normalize_username(name)!r}")
    return user


def _add(conn: Connection, args: argparse.Namespace) -> int:
    name = normalize_username(args.name)
    if not valid_username(name):
        _err("error: username must be 1-64 characters: a-z, 0-9, '.', '_', '-'"
             " (starting with a letter or digit)")
        return EXIT_CONFIG
    if users_repo.get_by_username(conn, name) is not None:
        _err(f"error: user {name!r} already exists")
        return EXIT_FAILED
    password = read_new_password()
    if password is None:
        return EXIT_FAILED
    try:
        users_repo.add_user(conn, name, passwords.hash_password(password), now=utc_now())
    except users_repo.UserExists:
        _err(f"error: user {name!r} already exists")
        return EXIT_FAILED
    _out(f"user {name!r} added")
    return EXIT_OK


def _passwd(conn: Connection, args: argparse.Namespace) -> int:
    user = _user(conn, args.name)
    if user is None:
        return EXIT_FAILED
    password = read_new_password()
    if password is None:
        return EXIT_FAILED
    users_repo.set_password(conn, user.id, passwords.hash_password(password))
    ended = users_repo.delete_user_sessions(conn, user.id)
    _out(f"password changed for {user.username!r}; {ended} session(s) ended")
    return EXIT_OK


def _list(conn: Connection, args: argparse.Namespace) -> int:
    users = users_repo.list_users(conn)
    if not users:
        _out("no users (create one: sidereal user add NAME)")
    for u in users:
        flags = ["totp" if u.totp_secret else "no-totp"] + (["disabled"] if u.disabled else [])
        sessions = users_repo.count_sessions(conn, u.id)
        _out(f"{u.username}  created {u.created_at}  {' '.join(flags)}  sessions {sessions}")
    return EXIT_OK


def _delete(conn: Connection, args: argparse.Namespace) -> int:
    user = _user(conn, args.name)
    if user is None:
        return EXIT_FAILED
    users_repo.delete_user(conn, user.id)
    _out(f"user {user.username!r} deleted (and their sessions)")
    return EXIT_OK


def _totp(conn: Connection, args: argparse.Namespace) -> int:
    user = _user(conn, args.name)
    if user is None:
        return EXIT_FAILED
    if args.off:
        users_repo.set_totp(conn, user.id, None)
        _out(f"TOTP turned off for {user.username!r}")
        return EXIT_OK
    secret = totp.new_secret()
    _out("Add this account to your authenticator app, then enter the code it shows.")
    _out(f"secret: {secret}")
    _out(f"uri:    {totp.provisioning_uri(secret, user.username)}")
    code = input("Code: ")
    if not totp.verify(secret, code, time.time()):
        _err("error: wrong code, TOTP not turned on")
        return EXIT_FAILED
    users_repo.set_totp(conn, user.id, secret)
    users_repo.delete_user_sessions(conn, user.id)
    _out(f"TOTP turned on for {user.username!r}; existing sessions ended")
    return EXIT_OK


ACTIONS = {"add": _add, "passwd": _passwd, "list": _list, "delete": _delete, "totp": _totp}


def cmd_user(settings: Settings, args: argparse.Namespace) -> int:
    from sidereal.bootstrap import migrate

    migrate(settings)
    conn = connect(settings.db_path)
    try:
        return ACTIONS[args.action](conn, args)
    finally:
        conn.close()


def add_parser(sub: argparse._SubParsersAction) -> None:
    user = sub.add_parser("user", help="manage login accounts (passwords are prompted)")
    actions = user.add_subparsers(dest="action", required=True)
    actions.add_parser("add", help="create a user").add_argument("name")
    actions.add_parser("passwd", help="change a password, end its sessions").add_argument("name")
    actions.add_parser("list", help="list users")
    actions.add_parser("delete", help="delete a user and their sessions").add_argument("name")
    t = actions.add_parser("totp", help="turn on TOTP (shows a secret to scan) or --off")
    t.add_argument("name")
    t.add_argument("--off", action="store_true")
    user.set_defaults(func=cmd_user)

"""``sidereal notify test [--channel email|discord]`` (M28): send one fixed test message on each
configured channel (or on ``--channel``, configured or not). Touches no DB. Exit 0 when every
send worked, 1 when one failed, 2 when nothing is configured. Secrets are never printed."""

from __future__ import annotations

import argparse
import asyncio

from sidereal.config import Settings
from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from sidereal.notify.base import NotifyError, load_secrets
from sidereal.notify.dispatcher import send_test

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2


def make_fetcher(settings: Settings) -> Fetcher:
    return Fetcher(guard=UrlGuard())


def _out(text: str) -> None:
    from sidereal.cli import out

    out(text)


def _err(text: str) -> None:
    from sidereal.cli import err

    err(text)


async def _test(settings: Settings, names: list[str]) -> int:
    try:
        secrets = load_secrets()
    except NotifyError as exc:
        _err(f"notify: {exc}")
        return EXIT_CONFIG
    fetcher = make_fetcher(settings)
    code = EXIT_OK
    try:
        for name in names:
            try:
                await send_test(settings, name, fetcher=fetcher, secrets=secrets)
            except NotifyError as exc:
                _err(f"{name}: failed ({exc})")
                code = EXIT_FAILED
            else:
                _out(f"{name}: sent")
    finally:
        await fetcher.aclose()
    return code


def cmd_notify(settings: Settings, args: argparse.Namespace) -> int:
    names = [args.channel] if args.channel else list(dict.fromkeys(settings.notify.channels))
    if not names:
        _err("notify: no channels configured (set [notify] channels, or pass --channel)")
        return EXIT_CONFIG
    return asyncio.run(_test(settings, names))


def add_parser(sub: argparse._SubParsersAction) -> None:
    notify = sub.add_parser("notify", help="notifications: send a test message")
    actions = notify.add_subparsers(dest="action", required=True)
    test = actions.add_parser("test", help="send a test message on the configured channels")
    test.add_argument("--channel", choices=("email", "discord"), default=None)
    notify.set_defaults(func=cmd_notify)

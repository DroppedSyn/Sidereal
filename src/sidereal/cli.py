"""Command line: ``sidereal <command>`` (plan §9.3).

Output policy: user-facing output goes through ``out()`` / ``err()`` here (sys.stdout/stderr);
``print`` is banned in ``src/`` by the static rules, everything else logs.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from sidereal import __version__
from sidereal.auth.usercli import add_parser as add_user_parser
from sidereal.commands import add_parsers
from sidereal.config import ConfigError, Settings, load_settings
from sidereal.db.migrations import MigrationError
from sidereal.notify.notifycli import add_parser as add_notify_parser

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2

# Commands specified in the plan but built in later milestones.
PLANNED = {
    "reassess": "unscheduled",  # §9.3 lists it, no milestone row builds it
    "eval": "M16",
}


def out(text: str) -> None:
    sys.stdout.write(text + "\n")


def err(text: str) -> None:
    sys.stderr.write(text + "\n")


def cmd_init(settings: Settings, args: argparse.Namespace) -> int:
    from sidereal.bootstrap import init

    report = init(settings)
    out(f"database: {report.db_path}")
    out(f"migrations applied: {report.migrations_applied or 'none (up to date)'}")
    out(f"sources added: {report.sources_added}")
    out(f"focus areas added: {report.focus_areas_added}")
    return EXIT_OK


def cmd_openapi(settings: Settings, args: argparse.Namespace) -> int:
    from sidereal.api.app import create_app

    out(json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True))
    return EXIT_OK


def cmd_serve(settings: Settings, args: argparse.Namespace) -> int:
    import uvicorn

    from sidereal.api.bind import UnsafeBindError, check_bind, count_users
    from sidereal.bootstrap import migrate

    host = args.host or settings.web.host
    port = args.port or settings.web.port
    try:
        check_bind(host, settings, user_count=count_users(settings))
    except UnsafeBindError as exc:
        err(str(exc))
        return EXIT_CONFIG
    migrate(settings)
    # proxy_headers off: client IPs come from X-Forwarded-For only via web.trusted_proxies
    # (auth.middleware.client_ip), never from uvicorn's own 127.0.0.1 default.
    if args.reload:
        uvicorn.run("sidereal.api.asgi:app", host=host, port=port, reload=True,
                    proxy_headers=False)
    else:
        from sidereal.api.app import create_app

        uvicorn.run(create_app(settings), host=host, port=port, proxy_headers=False)
    return EXIT_OK


def cmd_planned(settings: Settings, args: argparse.Namespace) -> int:
    err(f"sidereal {args.command}: not implemented yet ({PLANNED[args.command]})")
    return EXIT_CONFIG


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sidereal", description="Personal intelligence feed.")
    parser.add_argument("--version", action="version", version=f"sidereal {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create dirs and DB, seed sources and focus areas").set_defaults(
        func=cmd_init
    )
    sub.add_parser("openapi", help="print the OpenAPI JSON").set_defaults(func=cmd_openapi)
    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true", help="auto-reload (development)")
    serve.set_defaults(func=cmd_serve)
    add_parsers(sub)
    add_user_parser(sub)
    add_notify_parser(sub)
    for name, milestone in PLANNED.items():
        sub.add_parser(name, help=f"(not implemented yet, {milestone})").set_defaults(
            func=cmd_planned
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if extra and args.command not in PLANNED:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        settings = load_settings()
        return args.func(settings, args)
    except (ConfigError, MigrationError) as exc:
        err(f"error: {exc}")
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())

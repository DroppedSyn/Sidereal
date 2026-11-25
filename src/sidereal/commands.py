"""``sidereal run`` / ``rescore`` / ``doctor`` / ``backup`` (plan §9.3, §12.4, §12.5), kept out
of ``cli.py`` so the parser stays thin. Network clients come from ``make_fetcher`` /
``make_ollama`` (tests monkeypatch them); every client opened here is closed here, also on error.

Exit codes (§9.2): 0 ok / partial / skipped, 1 failed, 2 config error (bad ``--source``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re

from sidereal.config import Settings
from sidereal.db import runs_repo
from sidereal.db.connect import connect
from sidereal.llm.ollama import OllamaClient
from sidereal.net.fetch import Fetcher
from sidereal.net.guard import UrlGuard
from sidereal.overrides import effective_settings
from sidereal.pipeline import lock, placement, runner
from sidereal.timeutil import utc_now

log = logging.getLogger(__name__)

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2
DOCTOR_OLLAMA_TIMEOUT_S = 10.0
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def make_fetcher(settings: Settings) -> Fetcher:
    return Fetcher(guard=UrlGuard())


def make_ollama(settings: Settings, *, timeout_s: float | None = None) -> OllamaClient:
    kw = {} if timeout_s is None else {"timeout_s": timeout_s}
    return OllamaClient(settings.ollama.url, never_unload=settings.models.never_unload, **kw)


def _out(text: str) -> None:
    from sidereal.cli import out

    out(text)


def _err(text: str) -> None:
    from sidereal.cli import err

    err(text)


async def _close(*clients: Fetcher | OllamaClient | None) -> None:
    for c in clients:
        if c is not None:
            try:
                await c.aclose()
            except Exception as exc:  # closing must not hide the run's own outcome
                log.warning("closing %s failed: %s", type(c).__name__, type(exc).__name__)


async def _dry_run(settings: Settings, args: argparse.Namespace) -> dict:
    fetcher = make_fetcher(settings)
    conn = connect(settings.db_path)
    try:
        return await runner.dry_run(settings, conn, fetcher=fetcher, only_source=args.source)
    finally:
        conn.close()
        await _close(fetcher)


async def _run(settings: Settings, args: argparse.Namespace) -> runs_repo.RunRow:
    fetcher = ollama = None
    conn = connect(settings.db_path)
    try:
        fetcher = make_fetcher(settings)
        ollama = make_ollama(settings)
        gate = None if args.no_gate else runner.make_gate(settings, ollama)
        return await runner.run_once(settings, conn, fetcher=fetcher, ollama=ollama,
                                     trigger=args.trigger, gate=gate, only_source=args.source,
                                     max_assess=args.max_assess)
    finally:
        conn.close()
        await _close(fetcher, ollama)


def _print_counts(stats: dict) -> None:
    for key in ("sources", "items", "stories", "prefilter", "triage", "enrich", "assess",
                "buckets", "digest", "notify", "retention", "durations_s"):
        if key in stats:
            _out(f"{key}: {json.dumps(stats[key], sort_keys=True)}")


def cmd_run(settings: Settings, args: argparse.Namespace) -> int:
    from sidereal.bootstrap import migrate

    migrate(settings)  # dirs + schema; idempotent, so safe even while another run holds the lock
    try:
        if args.dry_run:
            counts = asyncio.run(_dry_run(settings, args))
            _out("dry run (nothing written)")
            _print_counts(counts)
            return EXIT_OK
        with lock.RunLock(lock.lock_path(settings.state_dir)):
            row = asyncio.run(_run(settings, args))
    except lock.RunLocked as exc:
        conn = connect(settings.db_path)
        try:
            run_id = runs_repo.mark_skipped(conn, trigger=args.trigger, at=utc_now(),
                                            reason=str(exc))
        finally:
            conn.close()
        _out(f"run {run_id}: skipped ({exc})")
        return EXIT_OK
    except ValueError as exc:  # unknown --source / trigger, raised before any run row
        _err(f"error: {exc}")
        return EXIT_CONFIG
    _out(f"run {row.id}: {row.status}" + (f" ({row.error})" if row.error else ""))
    _print_counts(row.stats)
    return EXIT_FAILED if row.status == "failed" else EXIT_OK


def cmd_rescore(settings: Settings, args: argparse.Namespace) -> int:
    """Recompute scores and buckets from stored assessments (no LLM). Takes the run lock so it
    never races a run's placement; a held lock → exit 1 (try again later)."""
    from sidereal.bootstrap import migrate

    if args.day is not None and not _DAY.match(args.day):
        _err(f"error: --day must be YYYY-MM-DD, got {args.day!r}")
        return EXIT_CONFIG
    migrate(settings)
    try:
        with lock.RunLock(lock.lock_path(settings.state_dir)):
            conn = connect(settings.db_path)
            try:
                cfg = effective_settings(settings, conn).scoring
                result = placement.rescore(conn, cfg, day=args.day)
            finally:
                conn.close()
    except lock.RunLocked as exc:
        _err(f"rescore: {exc}; try again when it has finished")
        return EXIT_FAILED
    _out(f"rescored: {result['rescored']}")
    _out(f"buckets: {json.dumps(result['buckets'], sort_keys=True)}")
    _out(f"days: {', '.join(sorted(result['days'])) or 'none'}")
    return EXIT_OK


async def _doctor(settings: Settings) -> list:
    from sidereal.doctor import run_checks

    ollama = make_ollama(settings, timeout_s=DOCTOR_OLLAMA_TIMEOUT_S)
    try:
        return await run_checks(settings, ollama)
    finally:
        await _close(ollama)


def cmd_doctor(settings: Settings, args: argparse.Namespace) -> int:
    from sidereal.doctor import FAIL

    checks = asyncio.run(_doctor(settings))
    for c in checks:
        _out(c.line())
    return EXIT_FAILED if any(c.level == FAIL for c in checks) else EXIT_OK


def cmd_backup(settings: Settings, args: argparse.Namespace) -> int:
    """Online backup to ``$STATE/backups`` keeping ``retention.backup_keep`` (plan §12.4).
    No run lock needed: the backup API copies a consistent snapshot while a run writes."""
    from sidereal.db.backup import BackupError, make_backup

    try:
        result = make_backup(settings.db_path, settings.state_dir / "backups", at=utc_now(),
                             keep=settings.retention.backup_keep)
    except BackupError as exc:
        _err(f"backup: {exc}")
        return EXIT_FAILED
    _out(f"backup: {result.path} ({result.size / 1e6:.1f} MB)")
    _out(f"removed: {len(result.removed)} old backup(s)")
    return EXIT_OK


def non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return value


def add_parsers(sub: argparse._SubParsersAction) -> None:
    run = sub.add_parser("run", help="one pipeline run (fetch, triage, assess, digests)")
    run.add_argument("--no-gate", action="store_true", help="skip the GPU politeness gate")
    run.add_argument("--source", default=None, metavar="KEY", help="only this source")
    run.add_argument("--dry-run", action="store_true",
                     help="fetch + normalise + dedupe, print counts, write nothing")
    run.add_argument("--max-assess", type=non_negative_int, default=None, metavar="N")
    run.add_argument("--trigger", choices=("manual", "timer"), default="manual")
    run.set_defaults(func=cmd_run)
    rescore = sub.add_parser("rescore", help="recompute scores/buckets (no LLM)")
    rescore.add_argument("--day", default=None, metavar="YYYY-MM-DD")
    rescore.set_defaults(func=cmd_rescore)
    sub.add_parser("doctor", help="check config, DB, Ollama, sources, systemd").set_defaults(
        func=cmd_doctor)
    sub.add_parser("backup", help="online DB backup to $STATE/backups").set_defaults(
        func=cmd_backup)

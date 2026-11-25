"""Notification dispatch (M28, plan §9.1 ``notify.dispatch``, §16 M28).

After a run: for each channel in ``notify.channels``, the TOP stories first seen within
``LOOKBACK_HOURS`` that were never sent on that channel (``notify_repo.pending_top``; hidden
stories skipped) go out as one batch, then are recorded so nothing is sent twice. During quiet
hours (``quiet_start``-``quiet_end`` in ``schedule.tz``) nothing is sent: the stories stay
pending and the first run after ``quiet_end`` sends them.

Never raises: a channel failure is logged (type and safe message, secrets scrubbed) and
returned in the stats; the stories stay pending for the next run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sidereal.config import Settings
from sidereal.db import Connection, notify_repo
from sidereal.net.fetch import Fetcher
from sidereal.notify.base import Notice, NotifyError, Secrets, error_text, load_secrets
from sidereal.notify.discord import DiscordChannel
from sidereal.notify.email import EmailChannel

log = logging.getLogger(__name__)

LOOKBACK_HOURS = 48  # older TOP stories are never sent (no flood when a channel is turned on)
MAX_PER_RUN = 20


class Channel(Protocol):
    name: str

    async def send(self, notices: list[Notice], *, heading: str) -> None: ...


ChannelFactory = Callable[[str, Settings, Secrets, Fetcher], Channel]


def make_channel(name: str, settings: Settings, secrets: Secrets, fetcher: Fetcher) -> Channel:
    """The channel object, or NotifyError when it is not configured."""
    if name == "email":
        return EmailChannel(settings.notify, secrets.smtp_password)
    if name == "discord":
        return DiscordChannel(secrets.discord_webhook_url, fetcher)
    raise NotifyError(f"unknown channel {name!r}")


def _hhmm(text: str) -> time:
    try:
        return time.fromisoformat(text)
    except ValueError as exc:
        raise NotifyError(f"bad quiet-hours time {text!r} (HH:MM)") from exc


def in_quiet_hours(now: datetime, settings: Settings) -> bool:
    """True when local ``now`` is in [quiet_start, quiet_end) (wrapping midnight);
    equal start and end means no quiet hours."""
    start, end = _hhmm(settings.notify.quiet_start), _hhmm(settings.notify.quiet_end)
    if start == end:
        return False
    t = now.astimezone(ZoneInfo(settings.schedule.tz)).time()
    return start <= t < end if start < end else (t >= start or t < end)


def heading_for(n: int) -> str:
    return f"Sidereal: {n} new TOP {'story' if n == 1 else 'stories'}"


def _notice(p: notify_repo.PendingStory) -> Notice:
    return Notice(story_id=p.story_id, title=p.title, url=p.url, sources=p.sources, why=p.why)


async def dispatch(conn: Connection, settings: Settings, *, fetcher: Fetcher, now: datetime,
                   run_id: int | None, secrets: Secrets | None = None,
                   factory: ChannelFactory = make_channel) -> dict[str, Any]:
    """Send pending TOP stories on every configured channel. Returns per-channel stats
    ``{"sent": n}`` / ``{"held": n}`` (quiet hours) / ``{"error": "...", "pending": n}``."""
    stats: dict[str, Any] = {}
    if not settings.notify.channels:
        return stats
    try:
        secrets = secrets if secrets is not None else load_secrets()
    except NotifyError as exc:
        log.warning("notify: %s", exc)
        return {name: {"error": str(exc)} for name in settings.notify.channels}
    try:
        quiet = in_quiet_hours(now, settings)
    except NotifyError as exc:
        return {name: {"error": str(exc)} for name in settings.notify.channels}
    since = now - timedelta(hours=LOOKBACK_HOURS)
    for name in dict.fromkeys(settings.notify.channels):
        pending: list = []
        try:
            pending = notify_repo.pending_top(conn, name, since=since, limit=MAX_PER_RUN)
            if not pending:
                stats[name] = {"sent": 0}
                continue
            if quiet:
                stats[name] = {"held": len(pending)}
                continue
            channel = factory(name, settings, secrets, fetcher)
            await channel.send([_notice(p) for p in pending], heading=heading_for(len(pending)))
            notify_repo.mark_sent(conn, [p.story_id for p in pending], name,
                                  run_id=run_id, at=now)
            stats[name] = {"sent": len(pending)}
            log.info("notify %s: sent %d stor%s", name, len(pending),
                     "y" if len(pending) == 1 else "ies")
        except Exception as exc:  # a notify failure never fails the run
            text = error_text(exc, secrets)
            log.warning("notify %s failed: %s", name, text)
            stats[name] = {"error": text, "pending": len(pending)}
    return stats


async def send_test(settings: Settings, name: str, *, fetcher: Fetcher,
                    secrets: Secrets | None = None,
                    factory: ChannelFactory = make_channel) -> None:
    """``sidereal notify test``: one fixed message on ``name``; NotifyError on failure."""
    secrets = secrets if secrets is not None else load_secrets()
    channel = factory(name, settings, secrets, fetcher)
    notice = Notice(story_id=0, title="Sidereal test notification", url="",
                    sources=("sidereal",), why="If you can read this, notifications work.")
    try:
        await channel.send([notice], heading="Sidereal: test notification")
    except NotifyError:
        raise
    except Exception as exc:
        raise NotifyError(error_text(exc, secrets)) from None

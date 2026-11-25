"""Validation for sources edited in the settings UI (M27). Pure: no DB, no network.

- ``check_source_url(url)``: http(s), and every *static* rule of ``net.guard`` (no whitespace,
  userinfo, odd ports or numeric host forms; IP literals must be public), plus local-looking host
  names (``localhost``, single labels, ``.local``/``.lan``/``.internal``/``.home.arpa``…). DNS is
  not consulted here: the fetcher re-checks every hop with real resolution, and "Test feed" does
  too, so a public-looking name that resolves to a private address is still refused at fetch time.
- ``clean_options(kind, key, options)``: only the keys the adapter of ``kind`` reads, each type-
  and range-checked; regex options compiled with ``base.option_regex`` (same semantics as a run).

Both raise ``ValueError`` with a message safe to return to the client.
"""

from __future__ import annotations

import re
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from sidereal.net.guard import UrlBlocked, UrlGuard
from sidereal.sources.base import REGISTRY, option_regex
from sidereal.sources.hn_algolia import hn_options

MAX_URL = 2000
_STATIC_ADDRESS = "1.1.1.1"  # stands in for DNS: only the guard's static rules are exercised
_LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal", ".home.arpa", ".localdomain",
                   ".intranet", ".corp", ".home")
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}"
                   r"[a-z0-9])?)+$")

COMMON_OPTIONS = frozenset({"article_hosts", "max_bytes"})
REGEX_OPTIONS = ("include_regex", "exclude_regex", "error_title_regex", "product_regex")
KIND_OPTIONS: dict[str, frozenset[str]] = {
    "rss": COMMON_OPTIONS | {"include_regex", "exclude_regex", "error_title_regex"},
    "msrc": COMMON_OPTIONS | {"include_regex", "exclude_regex", "error_title_regex",
                              "product_regex"},
    "cisa_kev": COMMON_OPTIONS,
    "hn_algolia": COMMON_OPTIONS | {"queries", "min_points"},
}
MAX_HOSTS = 20
MAX_REGEX = 500
MAX_QUERIES = 20
MAX_QUERY = 100
MAX_BYTES_RANGE = (10_000, 20_000_000)
MAX_MIN_POINTS = 10_000


async def _static_resolver(host: str, port: int) -> list[str]:
    return [_STATIC_ADDRESS]


_GUARD = UrlGuard(resolver=_static_resolver)


def _run_now(coro: Coroutine[Any, Any, Any]) -> Any:
    """Drive a coroutine that never suspends (the static resolver doesn't), without an event
    loop, so this works inside FastAPI's request parsing as well as in a worker thread."""
    try:
        coro.send(None)
    except StopIteration as stop:
        return stop.value
    coro.close()
    raise RuntimeError("URL check suspended unexpectedly")


def is_local_name(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES)


def check_source_url(url: str) -> str:
    """``url`` stripped, if it may be fetched as far as static checks can tell."""
    url = url.strip()
    if not url:
        raise ValueError("URL is required")
    if len(url) > MAX_URL:
        raise ValueError(f"URL is longer than {MAX_URL} characters")
    try:
        checked = _run_now(_GUARD.check(url))
    except UrlBlocked as exc:
        raise ValueError(f"URL refused: {exc.reason}") from None
    if checked.addresses != (_STATIC_ADDRESS,):  # an IP literal: already checked as public
        return url
    if is_local_name(checked.host):
        raise ValueError(f"URL refused: {checked.host} is a local host name")
    return url


@dataclass(frozen=True)
class ProbeSource:
    """A SourceLike stand-in so option checks run exactly like an adapter would."""

    key: str
    options: dict[str, Any]
    url: str = ""
    max_items: int = 1
    etag: str | None = None
    last_modified: str | None = None


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"options.{name} must be an integer from {lo} to {hi}")
    return value


def _hosts(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_HOSTS:
        raise ValueError(f"options.article_hosts must be a list of at most {MAX_HOSTS} host names")
    out: list[str] = []
    for entry in value:
        host = entry.strip().lower().rstrip(".") if isinstance(entry, str) else ""
        if not _HOST.match(host) or is_local_name(host) or host.rsplit(".", 1)[-1].isdigit():
            raise ValueError(
                f"options.article_hosts: {str(entry)[:80]!r} is not a public host name")
        if host not in out:
            out.append(host)
    return out


def _queries(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_QUERIES:
        raise ValueError(f"options.queries must be a list of 1 to {MAX_QUERIES} search terms")
    out = []
    for q in value:
        if not isinstance(q, str) or not q.strip() or len(q) > MAX_QUERY:
            raise ValueError(f"options.queries: each term must be 1 to {MAX_QUERY} characters")
        out.append(" ".join(q.split()))
    return out


def clean_options(kind: str, key: str, options: dict[str, Any]) -> dict[str, Any]:
    """Validated options for a source of ``kind``; unknown keys are refused, empty regex
    strings dropped (= the adapter's default)."""
    if kind not in KIND_OPTIONS or kind not in REGISTRY:
        raise ValueError(f"unknown source kind {kind!r}")
    unknown = sorted(set(options) - KIND_OPTIONS[kind])
    if unknown:
        raise ValueError(f"options not used by {kind} sources: {', '.join(unknown)}")
    out: dict[str, Any] = {}
    for name, value in options.items():
        if name == "article_hosts":
            out[name] = _hosts(value)
        elif name == "max_bytes":
            out[name] = _int(value, name, *MAX_BYTES_RANGE)
        elif name == "min_points":
            out[name] = _int(value, name, 0, MAX_MIN_POINTS)
        elif name == "queries":
            out[name] = _queries(value)
        elif name in REGEX_OPTIONS:
            if value is None or value == "":
                continue
            if not isinstance(value, str) or len(value) > MAX_REGEX:
                raise ValueError(f"options.{name} must be a regular expression of at most "
                                 f"{MAX_REGEX} characters")
            out[name] = value
    probe = ProbeSource(key=key, options=out)
    for name in REGEX_OPTIONS:
        if name in out:
            option_regex(probe, name)  # ValueError names the option, like a run would
    if kind == "hn_algolia":
        hn_options(probe)  # queries are required for this kind
    return out

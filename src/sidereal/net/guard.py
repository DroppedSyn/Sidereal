"""URL guard against SSRF (plan §6.2). Every outbound internet request is checked here first.

Public API:
- ``UrlGuard(resolver=None, allowed_ports=(80, 443), allow_private=False)``
- ``await guard.check(url, allow_hosts=None) -> CheckedUrl`` or raises ``UrlBlocked(reason)``.
  The fetcher calls it for the first URL **and for every redirect hop**.
- ``CheckedUrl(url, host, port, addresses)``: ``host`` is the lowercased IDNA (ASCII) host without
  a trailing dot or brackets; ``addresses`` are the resolved IPs (all of them were checked).

Rules, in order:
1. No whitespace, control characters or backslashes anywhere in the URL.
2. Scheme ``http`` or ``https``; a host is required; no userinfo (``user:pass@``).
3. Port (explicit or the scheme default) in ``allowed_ports``.
4. Numeric host forms other than a strict dotted quad are refused (``2130706433``, ``0x7f.1``,
   ``017700000001``, ``127.1``): any host whose last label is all digits or ``0x…`` must parse as
   a strict ``a.b.c.d``. IPv6 literals need brackets and may not carry a zone id.
5. ``allow_hosts`` (when given, even empty): the host must equal an entry or be a subdomain of one
   (case-insensitive, trailing dot ignored, compared IDNA-encoded). An empty list allows nothing.
6. IP-literal hosts are checked directly; names are resolved with ``resolver`` and the URL is
   refused if resolution fails, returns nothing, or **any** address is not public.

"Public" means not private, loopback, link-local, multicast, reserved, unspecified, and
``is_global``. CGNAT ``100.64/10`` is therefore refused. For IPv6, an embedded IPv4 address is
also checked: IPv4-mapped ``::ffff:a.b.c.d``, IPv4-compatible ``::a.b.c.d``, 6to4 ``2002::/16``,
NAT64 ``64:ff9b::/96`` and Teredo (client address). This does not rely on the ``ipaddress``
behaviour of a particular Python version.

``allow_private=True`` (notifiers on the LAN, plan §1 rule 3) skips the public-address test but
still refuses unspecified and multicast addresses and every syntactic rule above.

Accepted limitation (TOCTOU, plan §6.2): the guard resolves the name, then httpx resolves it again
when connecting, so a DNS answer that changes in between (DNS rebinding) is not caught. Accepted
for v1; the per-source ``article_hosts`` allowlist for enrichment closes most of it.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["CheckedUrl", "Resolver", "UrlBlocked", "UrlGuard", "default_resolver"]

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

_DEFAULT_PORTS = {"http": 80, "https": 443}
_BAD_CHARS = re.compile(r"[\x00-\x20\x7f\\]")
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]*|[0-9]+)$")
_HOST_CHARS = re.compile(r"^[a-z0-9_-]+(\.[a-z0-9_-]+)*$")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class UrlBlocked(Exception):
    """The URL may not be fetched. ``reason`` says why (safe to log)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CheckedUrl:
    url: str
    host: str
    port: int
    addresses: tuple[str, ...]


async def default_resolver(host: str, port: int) -> list[str]:
    """Resolve ``host`` with the event loop's ``getaddrinfo`` (TCP); returns IP strings."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _normalise_host(host: str) -> str:
    """Lowercase, strip one trailing dot, IDNA-encode. Raises ``UrlBlocked`` if malformed."""
    host = host.strip().lower()
    if host.endswith("."):
        host = host[:-1]
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UrlBlocked(f"invalid host name {host!r}") from exc
    if not _HOST_CHARS.match(host):
        raise UrlBlocked(f"invalid host name {host!r}")
    return host


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    if ip in _NAT64 or int(ip) >> 32 == 0:  # NAT64, or IPv4-compatible ::a.b.c.d
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _why_not_public(ip: IPAddress) -> str | None:
    for attr in ("unspecified", "loopback", "multicast", "link_local", "private", "reserved"):
        if getattr(ip, f"is_{attr}"):
            return attr
    if not ip.is_global:
        return "not global"
    return None


def _address_problem(ip: IPAddress, allow_private: bool) -> str | None:
    """Return why ``ip`` must not be contacted, or ``None`` if it is fine."""
    candidates: list[IPAddress] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_ipv4(ip)
        if inner is not None:
            candidates.insert(0, inner)  # report the embedded address first
    for addr in candidates:
        if allow_private:
            why = "unspecified" if addr.is_unspecified else (
                "multicast" if addr.is_multicast else None)
        else:
            why = _why_not_public(addr)
        if why is not None:
            embedded = f" (embedded IPv4 {addr})" if addr is not ip else ""
            return f"address {ip} is {why}{embedded}"
    return None


def _parse_ip(text: str) -> IPAddress:
    try:
        return ipaddress.ip_address(text.split("%", 1)[0])  # resolver may add an IPv6 scope id
    except ValueError as exc:
        raise UrlBlocked(f"resolver returned a non-IP value {text!r}") from exc


class UrlGuard:
    """Checks URLs before any outbound fetch. See the module docstring for the rules."""

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        allowed_ports: Iterable[int] = (80, 443),
        allow_private: bool = False,
    ) -> None:
        self._resolver: Resolver = resolver or default_resolver
        self._ports = frozenset(allowed_ports)
        self._allow_private = allow_private

    async def check(self, url: str, *, allow_hosts: Iterable[str] | None = None) -> CheckedUrl:
        """Return the checked URL or raise ``UrlBlocked``. Call it again for every redirect hop."""
        if not isinstance(url, str) or _BAD_CHARS.search(url):
            raise UrlBlocked("URL contains whitespace, control characters or backslashes")
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise UrlBlocked(f"malformed URL: {exc}") from exc
        scheme = parts.scheme.lower()
        if scheme not in _DEFAULT_PORTS:
            raise UrlBlocked(f"scheme {scheme or '(none)'!r} is not allowed")
        if "@" in parts.netloc:
            raise UrlBlocked("URLs with userinfo are not allowed")
        raw_host = parts.hostname or ""
        if not raw_host:
            raise UrlBlocked("URL has no host")
        port = port if port is not None else _DEFAULT_PORTS[scheme]
        if port not in self._ports:
            raise UrlBlocked(f"port {port} is not allowed")

        literal = self._ip_literal(parts.netloc, raw_host)
        host = str(literal) if literal is not None else _normalise_host(raw_host)
        if allow_hosts is not None:
            self._check_allowlist(host, allow_hosts)

        if literal is not None:
            ips = [literal]
        else:
            try:
                resolved = await self._resolver(host, port)
            except (OSError, UnicodeError) as exc:
                raise UrlBlocked(f"cannot resolve {host}: {type(exc).__name__}") from exc
            ips = [_parse_ip(a) for a in resolved]
            if not ips:
                raise UrlBlocked(f"cannot resolve {host}: no addresses")
        for ip in ips:  # ANY bad address blocks the URL
            problem = _address_problem(ip, self._allow_private)
            if problem is not None:
                raise UrlBlocked(problem)
        addresses = tuple(dict.fromkeys(str(ip) for ip in ips))
        return CheckedUrl(url=url, host=host, port=port, addresses=addresses)

    @staticmethod
    def _ip_literal(netloc: str, host: str) -> IPAddress | None:
        if netloc.startswith("["):
            if "%" in host:
                raise UrlBlocked("IPv6 zone ids are not allowed")
            try:
                return ipaddress.IPv6Address(host)
            except ValueError as exc:
                raise UrlBlocked(f"invalid IPv6 literal {host!r}") from exc
        labels = host.rstrip(".").split(".")
        if not _NUMERIC_LABEL.match(labels[-1]):
            return None
        try:
            return ipaddress.IPv4Address(host.rstrip("."))  # strict dotted quad only
        except ValueError as exc:
            raise UrlBlocked(f"numeric host form {host!r} is not allowed") from exc

    @staticmethod
    def _check_allowlist(host: str, allow_hosts: Iterable[str]) -> None:
        for entry in allow_hosts:
            try:
                allowed = _normalise_host(entry)
            except UrlBlocked:
                continue
            if host == allowed or host.endswith("." + allowed):
                return
        raise UrlBlocked(f"host {host} is not in the allowed hosts for this source")

"""URL helpers for Sidereal."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import SplitResult, unquote_plus, urlsplit

TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "mc_cid", "mc_eid", "ocid",
    "wt.mc_id", "cmp", "sc_cid",
})


def _is_tracking(key: str) -> bool:
    return key.startswith("utm_") or key in TRACKING_PARAMS


def _split(url: str) -> SplitResult | None:
    """Parse a URL; return SplitResult or None if not http(s)."""
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    if not parsed.hostname:
        return None
    try:
        _ = parsed.port
    except ValueError:
        return None
    return parsed


def is_http_url(url: str) -> bool:
    """True if url is http(s) with a non-empty hostname and valid port."""
    return _split(url) is not None


def host_of(url: str) -> str | None:
    """Lowercased hostname of an http(s) URL, else None."""
    parsed = _split(url)
    if parsed is None:
        return None
    return parsed.hostname


def canonicalize(url: str) -> str:
    """Canonical form of an http(s) URL; ValueError if not valid."""
    parsed = _split(url)
    if parsed is None:
        raise ValueError(f"not a valid http(s) URL: {url!r}")

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    netloc = hostname
    if ":" in hostname:
        netloc = f"[{hostname}]"

    # Port: keep unless default
    port = parsed.port
    if port is not None:
        default = 80 if scheme == "http" else 443
        if port != default:
            netloc = f"{netloc}:{port}"

    # Userinfo is dropped (not added to netloc).

    # Path
    path = parsed.path
    if not path:
        path = "/"
    elif len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    # Query: drop tracking params, sort remaining raw pieces
    query = ""
    if parsed.query:
        pieces = parsed.query.split("&")
        filtered = []
        for piece in pieces:
            if not piece:
                continue
            eq_pos = piece.find("=")
            if eq_pos >= 0:
                raw_key = piece[:eq_pos]
            else:
                raw_key = piece
            key = unquote_plus(raw_key).lower()
            if _is_tracking(key):
                continue
            filtered.append(piece)
        filtered.sort()
        if filtered:
            query = "&".join(filtered)

    result = f"{scheme}://{netloc}{path}"
    if query:
        result += f"?{query}"
    return result


def host_matches(host: str, allowlist: Iterable[str]) -> bool:
    """host matches an allowlist entry (exact or subdomain)."""
    h = host.lower().rstrip(".")
    if not h:
        return False
    for entry in allowlist:
        e = entry.lower().rstrip(".")
        if not e:
            continue
        if h == e:
            return True
        if h.endswith(f".{e}"):
            return True
    return False

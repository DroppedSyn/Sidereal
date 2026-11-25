"""Source adapters; importing this package registers every adapter kind in REGISTRY."""

from __future__ import annotations

from sidereal.sources import cisa_kev, hn_algolia, msrc, rss
from sidereal.sources.base import REGISTRY

__all__ = ["REGISTRY", "cisa_kev", "hn_algolia", "msrc", "rss"]

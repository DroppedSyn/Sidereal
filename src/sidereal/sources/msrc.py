"""Microsoft Security Response Center update guide adapter (plan §6.1)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, ClassVar

from sidereal.sources.base import (
    RawItem,
    SourceLike,
    apply_age_cap,
    newest_first,
    option_regex,
    register,
)
from sidereal.sources.rss import RssAdapter, filter_titles

__all__ = ["CVE_RE", "DEFAULT_PRODUCT_REGEX", "MsrcAdapter", "extract_cve_ids"]

DEFAULT_PRODUCT_REGEX = (
    r"(?i)azure|entra|windows server|exchange|sharepoint|defender|hyper-v"
    r"|windows kernel|remote desktop|dns|tcp/ip|kerberos|ntlm|active directory"
)
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)


def extract_cve_ids(*texts: str) -> list[str]:
    """All CVE ids across texts in order, uppercased, duplicates removed keeping the first."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in CVE_RE.finditer(text):
            seen.setdefault(match.group(0).upper(), None)
    return list(seen)


@register
class MsrcAdapter(RssAdapter):
    kind: ClassVar[str] = "msrc"

    def make_item(
        self, source: SourceLike, entry: Mapping[str, Any], now: datetime
    ) -> RawItem | None:
        item = super().make_item(source, entry, now)
        if item is None:
            return None
        cve_ids = extract_cve_ids(item.title, item.guid or "", item.url)
        return replace(item, extra={"cve_ids": cve_ids})

    def select(
        self,
        source: SourceLike,
        items: list[RawItem],
        now: datetime,
        max_age_hours: float | None,
    ) -> list[RawItem]:
        """msrc: age cap → include/exclude → product_regex → newest `max_items`. The cap comes
        last so a busy Patch Tuesday of other products cannot push matching entries out."""
        items = apply_age_cap(items, now, max_age_hours)
        items = filter_titles(items, source)
        product = option_regex(source, "product_regex", DEFAULT_PRODUCT_REGEX)
        if product is not None:
            items = [it for it in items if product.search(it.title)]
        return newest_first(items, source.max_items)

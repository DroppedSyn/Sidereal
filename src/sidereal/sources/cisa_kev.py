"""CISA KEV JSON catalogue adapter (plan §6.1)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any, ClassVar

from sidereal.net.fetch import Fetcher
from sidereal.sources.base import (
    FetchResult,
    RawItem,
    SourceBroken,
    SourceLike,
    apply_age_cap,
    newest_first,
    register,
)

JSON_ACCEPT = "application/json"
NVD_URL = "https://nvd.nist.gov/vuln/detail/{cve}"


@register
class CisaKevAdapter:
    kind: ClassVar[str] = "cisa_kev"

    async def fetch(
        self,
        source: SourceLike,
        fetcher: Fetcher,
        now: datetime,
        *,
        max_age_hours: float | None = None,
    ) -> FetchResult:
        resp = await fetcher.get(
            source.url,
            etag=source.etag,
            last_modified=source.last_modified,
            max_bytes=source.options.get("max_bytes"),
            accept=JSON_ACCEPT,
        )
        if resp.not_modified:
            return FetchResult(
                items=[],
                not_modified=True,
                etag=resp.etag,
                last_modified=resp.last_modified,
            )
        entries = vulnerabilities(source, resp.content)
        items = [item for entry in entries if (item := kev_item(source, entry)) is not None]
        items = apply_age_cap(items, now, max_age_hours)
        items = newest_first(items, source.max_items)
        return FetchResult(
            items=items, etag=resp.etag, last_modified=resp.last_modified,
            entry_count=len(entries),
        )


def date_added(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        d = date.fromisoformat(value.strip())
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    except (ValueError, AttributeError):
        return None


def kev_item(source: SourceLike, entry: Any) -> RawItem | None:
    if not isinstance(entry, dict):
        return None
    cve = str(entry.get("cveID") or "").strip()
    if not cve:
        return None
    d = date_added(entry.get("dateAdded"))
    if d is None:
        return None
    vendor_project = str(entry.get("vendorProject") or "").strip()
    product = str(entry.get("product") or "").strip()
    vulnerability_name = str(entry.get("vulnerabilityName") or "").strip()
    short_description = str(entry.get("shortDescription") or "").strip()
    required_action = str(entry.get("requiredAction") or "").strip()
    due_date = str(entry.get("dueDate") or "").strip()
    ransomware = str(entry.get("knownRansomwareCampaignUse") or "").strip().lower() == "known"
    parts = []
    if short_description:
        parts.append(short_description)
    if required_action:
        parts.append(f"Required action: {required_action}")
    if due_date:
        parts.append(f"Due date: {due_date}")
    if ransomware:
        parts.append("Known ransomware campaign use.")
    return RawItem(
        source_key=source.key,
        guid=f"kev:{cve}",
        url=NVD_URL.format(cve=cve),
        title=f"KEV: {vendor_project} {product}: {vulnerability_name}",
        published=d,
        author=None,
        excerpt_html="\n\n".join(parts),
        extra={
            "kev": True,
            "cve_ids": [cve],
            "vendor": vendor_project,
            "product": product,
            "ransomware": ransomware,
        },
    )


def vulnerabilities(source: SourceLike, content: bytes) -> list[Any]:
    """The catalogue's raw ``vulnerabilities`` list; bad JSON / no list → SourceBroken."""
    try:
        data = json.loads(content)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceBroken(f"{source.key}: not JSON") from exc
    if not isinstance(data, dict) or not isinstance(
        data.get("vulnerabilities"), list
    ):
        raise SourceBroken(f"{source.key}: no vulnerabilities list")
    return data["vulnerabilities"]


def parse_kev(source: SourceLike, content: bytes) -> list[RawItem]:
    return [
        item
        for entry in vulnerabilities(source, content)
        if (item := kev_item(source, entry)) is not None
    ]

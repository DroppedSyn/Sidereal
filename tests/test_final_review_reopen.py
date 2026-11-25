"""Final review: a filtered / triaged-out story that gains an item is reopened (state ``new``),
so an always-keep signal arriving by a join (here a Microsoft KEV entry sharing the CVE) is not
buried with the story."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest

from sidereal.db import stories_repo
from sidereal.pipeline import placement
from sidereal.pipeline.runner import run_once
from tests.pipeline_helpers import (
    NOW,
    FeedServer,
    add_story,
    ollama_for,
    seeded_db,
    smart_ollama,
    start,
    state_of,
)

CVE = "CVE-2026-99999"


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


def _kev_body() -> bytes:
    return json.dumps({"title": "KEV", "catalogVersion": "x", "count": 1, "vulnerabilities": [{
        "cveID": CVE, "vendorProject": "Microsoft", "product": "Windows",
        "vulnerabilityName": "Microsoft Windows Kernel Elevation of Privilege Vulnerability",
        "dateAdded": "2026-11-24", "shortDescription": "A flaw.", "requiredAction": "Patch.",
        "dueDate": "2026-12-15", "knownRansomwareCampaignUse": "Unknown"}]}).encode()


async def test_kev_join_reopens_triaged_out_story(settings, conn):
    sid = add_story(conn, start(conn, NOW - timedelta(hours=2)),
                    title="Local bakery wins regional bread award again",
                    at=NOW - timedelta(hours=2), day="2026-11-24", cve_ids=(CVE,))
    stories_repo.set_triage(conn, sid, 0)
    stories_repo.set_state(conn, sid, "triaged_out", reason="triage")
    server = FeedServer(conn)
    server.overrides["cisa-kev"] = httpx.Response(
        200, content=_kev_body(), headers={"content-type": "application/json"})
    row = await run_once(settings, conn, fetcher=server.fetcher(),
                         ollama=ollama_for(smart_ollama(), settings), now=NOW,
                         only_source="cisa-kev")
    assert row.status == "ok", row.error
    assert row.stats["stories"]["joined"] == 1 and row.stats["stories"]["reopened"] == 1
    story = stories_repo.get_story(conn, sid)
    assert story.flags.get("kev") is True
    assert story.state == "assessed" and story.bucket is not None


@pytest.mark.parametrize("state", ["filtered", "triaged_out"])
def test_reopen_resets_dropped_states(conn, state):
    sid = add_story(conn, start(conn))
    stories_repo.set_state(conn, sid, state, reason="too_old")
    assert placement.reopen(conn, [sid]) == 1
    assert state_of(conn, sid) == "new"
    assert stories_repo.get_story(conn, sid).filter_reason is None


@pytest.mark.parametrize("state", ["new", "assessed", "assess_failed"])
def test_reopen_leaves_other_states(conn, state):
    sid = add_story(conn, start(conn))
    stories_repo.set_state(conn, sid, state)
    assert placement.reopen(conn, [sid, 9999]) == 0
    assert state_of(conn, sid) == state

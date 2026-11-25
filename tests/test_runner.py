"""pipeline/runner.py (M13b): whole runs over the recorded feeds with a fake Ollama."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from sidereal.db import assessments_repo, digests_repo, runs_repo, sources_repo, stories_repo
from sidereal.llm.gate import GateResult
from sidereal.pipeline import ingest, runner
from sidereal.pipeline.digest_step import digest_set
from sidereal.pipeline.runner import dry_run, run_once
from sidereal.timeutil import iso_z
from tests.adapter_helpers import feed_bytes
from tests.pipeline_helpers import (
    NOW,
    FakeClock,
    FeedServer,
    assess_reply,
    chats,
    count,
    ollama_for,
    seeded_db,
    smart_ollama,
)


@pytest.fixture
def conn(settings):
    c = seeded_db(settings)
    yield c
    c.close()


async def _run(settings, conn, server=None, fake=None, **kw):
    server = server or FeedServer(conn)
    fake = fake or smart_ollama()
    row = await run_once(settings, conn, fetcher=server.fetcher(),
                         ollama=ollama_for(fake, settings), **{"now": NOW, **kw})
    return row, server, fake


async def test_end_to_end_places_stories_and_writes_digest(settings, conn):
    def by_title(title):
        if "KEV" in title:
            return assess_reply(3, 3, 3, 2, exploited_in_wild=True)
        if "Azure" in title:
            return assess_reply(3, 2, 2, 2)
        return assess_reply(1, 1, 0, 1, focus="industry")

    row, _, fake = await _run(settings, conn, fake=smart_ollama(assess=by_title))
    assert row.status == "ok", row.error
    assert row.error is None and row.finished_at is not None
    s = row.stats
    assert s["sources"]["ok"] == 21 and s["sources"]["failed"] == 0
    assert s["items"]["new"] > 50 and s["stories"]["new"] > 50
    assert s["assess"]["ok"] == settings.budget.max_assess_per_run
    assert sum(s["buckets"].values()) == s["assess"]["ok"]
    assert s["buckets"]["top"] > 0 and s["buckets"]["side"] + s["buckets"]["drop"] > 0
    assert s["triage"]["calls"] >= 1 and s["gate"] == "skipped"
    assessed = [x for x in stories_repo.stories_since(conn, NOW - timedelta(days=9))
                if x.state == "assessed"]
    assert len(assessed) == s["assess"]["ok"]
    for story in assessed:
        a = assessments_repo.get_assessment(conn, story.id)
        assert story.bucket in ("top", "relevant", "side", "drop") and story.score is not None
        assert a.raw["focus"] in ("azure-networking", "industry")
        assert a.prompt_version == "assess.v1"
    kev = [x for x in assessed if x.title.startswith("KEV:")]
    assert kev and all(x.flags.get("kev") and x.flags.get("exploited") for x in kev)
    digest = digests_repo.get_day_digest(conn, "2026-11-25")
    assert digest is not None and digest.headline == "A headline" and digest.run_id == row.id
    assert digest.story_ids == [sid for _, sid in digest_set(conn, "2026-11-25", settings)]
    assert len(chats(fake, "digest")) == 1


async def test_rerun_inserts_no_duplicates(settings, conn):
    first, _, _ = await _run(settings, conn)
    items, stories = count(conn, "items"), count(conn, "stories")
    second, _, fake = await _run(settings, conn, now=NOW + timedelta(hours=4))
    assert count(conn, "items") == items and count(conn, "stories") == stories
    assert second.stats["items"]["new"] == 0
    assert second.stats["items"]["duplicate"] == first.stats["items"]["new"]
    assert second.stats["stories"] == {"new": 0, "joined": 0, "reopened": 0}


async def test_backlog_carried_to_next_run(settings, conn):
    first, _, _ = await _run(settings, conn, max_assess=5)
    assert first.stats["assess"]["ok"] == 5 and first.stats["assess"]["deferred"] > 0
    pending = len(stories_repo.pending_stories(conn))
    assert pending == first.stats["assess"]["deferred"]
    second, _, fake = await _run(settings, conn, now=NOW + timedelta(hours=4), max_assess=5)
    assert second.stats["assess"]["ok"] == 5
    assert chats(fake, "triage") == []  # kept stories are not triaged twice
    assert len(stories_repo.pending_stories(conn)) == pending - 5


async def test_broken_and_failing_sources_make_the_run_partial(settings, conn):
    server = FeedServer(conn)
    server.overrides["krebs"] = httpx.Response(
        200, content=feed_bytes("msrc-blog-html.html"), headers={"content-type": "text/html"})
    server.overrides["darkreading"] = httpx.Response(500)
    server.overrides["hn-cloud-sec"] = lambda req: (_ for _ in ()).throw(RuntimeError("boom"))
    row, _, _ = await _run(settings, conn, server=server)
    assert row.status == "partial"
    assert "3 source(s) failed" in row.error
    assert sorted(row.stats["sources"]["failed_keys"]) == ["darkreading", "hn-cloud-sec", "krebs"]
    assert row.stats["sources"]["ok"] == 18 and row.stats["assess"]["ok"] > 0
    krebs = sources_repo.get_by_key(conn, "krebs")
    dark = sources_repo.get_by_key(conn, "darkreading")
    assert krebs.last_error.startswith("broken: ") and krebs.consecutive_failures == 1
    assert dark.last_error.startswith("FetchHTTPError") and dark.last_ok_at is None
    ok = sources_repo.get_by_key(conn, "bleepingcomputer")
    assert ok.last_ok_at == iso_z(NOW) and ok.consecutive_failures == 0


async def test_deadline_leaves_stories_new(settings, conn):
    clock = FakeClock()

    def slow(title):
        clock.t += 10 * 60  # each assessment "takes" 10 minutes of the 45-minute budget
        return assess_reply()

    row, _, fake = await _run(settings, conn, fake=smart_ollama(assess=slow), clock=clock)
    assert row.status == "partial" and "deadline reached" in row.error
    assert row.stats["assess"]["ok"] == 5  # 0, 10, 20, 30, 40 min started; 50 > 45 stops
    assert len(chats(fake, "assess")) == 5
    assert row.stats["assess"]["deferred"] > 0
    assert len(stories_repo.pending_stories(conn)) == row.stats["assess"]["deferred"]
    assert row.stats["digest"]["skipped"] >= 1 and chats(fake, "digest") == []


async def test_ollama_down_is_partial_and_keeps_stories_new(settings, conn):
    fake = smart_ollama()
    fake.errors["/api/chat"] = httpx.ConnectError("refused")
    row, _, _ = await _run(settings, conn, fake=fake)
    assert row.status == "partial" and "ollama unavailable" in row.error
    assert count(conn, "items") > 0 and count(conn, "assessments") == 0
    states = {s.state for s in stories_repo.stories_since(conn, NOW - timedelta(days=9))}
    assert states <= {"new", "filtered"}
    assert "digest" not in row.stats


async def test_unexpected_error_fails_the_run_but_keeps_ingest(settings, conn, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(runner, "run_assess", boom)
    row, _, _ = await _run(settings, conn)
    assert row.status == "failed" and row.error == "RuntimeError: bug"
    assert count(conn, "items") > 0 and row.finished_at is not None


async def test_stale_running_run_marked_failed(settings, conn):
    stale = runs_repo.start_run(conn, trigger="timer", at=NOW - timedelta(hours=4))
    row, _, _ = await _run(settings, conn)
    old = runs_repo.get_run(conn, stale)
    assert old.status == "failed" and old.error == "interrupted"
    assert row.stats["recovered_runs"] == 1 and row.status == "ok"


async def test_bad_arguments_raise_before_a_run_row(settings, conn):
    with pytest.raises(ValueError, match="unknown source key"):
        await _run(settings, conn, only_source="nope")
    with pytest.raises(ValueError, match="unknown trigger"):
        await _run(settings, conn, trigger="cron")
    assert count(conn, "runs") == 0


async def test_only_source_fetches_just_that_source(settings, conn):
    row, server, _ = await _run(settings, conn, only_source="cisa-kev")
    assert row.stats["sources"]["ok"] == 1
    feed_requests = [u for u in server.requests if u in server.by_url or "algolia" in u]
    assert feed_requests == [sources_repo.get_by_key(conn, "cisa-kev").url]


async def test_backfill_on_first_run_then_max_age(settings, conn, monkeypatch):
    seen = []
    real = ingest.ingest

    async def spy(*a, **kw):
        seen.append(kw["max_age_hours"])
        return await real(*a, **kw)

    monkeypatch.setattr(ingest, "ingest", spy)
    await _run(settings, conn)
    await _run(settings, conn, now=NOW + timedelta(hours=4))
    assert seen == [settings.ingest.backfill_hours, settings.ingest.max_age_hours]


async def test_models_unloaded_after_run_except_protected(settings, conn):
    settings = settings.model_copy(update={"models": settings.models.model_copy(
        update={"digest": "qwen3.6:35b-a3b-coding"})})
    _, _, fake = await _run(settings, conn)
    unloaded = [b["model"] for b in fake.calls("/api/generate") if b.get("keep_alive") == 0]
    assert unloaded == ["qwen3.8:27b"]


async def test_no_llm_work_means_no_unload(settings, conn):
    server = FeedServer(conn)
    for key in server.by_url.values():
        server.overrides[key] = httpx.Response(304)
    _, _, fake = await _run(settings, conn, server=server)
    assert fake.calls("/api/generate") == [] and fake.calls("/api/chat") == []


class _Gate:
    def __init__(self, clock):
        self.clock = clock

    async def wait(self, *, skip=False):
        self.clock.t += 50 * 60  # waiting does not eat into the run's deadline
        return GateResult(3000.0, False, 3, "idle")


async def test_gate_wait_recorded_and_not_counted_against_deadline(settings, conn):
    clock = FakeClock()
    row, _, _ = await _run(settings, conn, gate=_Gate(clock), clock=clock)
    assert row.stats["gate_wait_s"] == 3000.0 and row.stats["gate"] == "idle"
    assert row.status == "ok" and row.stats["assess"]["ok"] == 40


async def test_make_gate_probes_the_triage_model(settings, conn):
    fake = smart_ollama()
    gate = runner.make_gate(settings.model_copy(update={"gate": settings.gate.model_copy(
        update={"pi_bridge_runs_dir": ""})}), ollama_for(fake, settings))
    result = await gate.wait()
    assert result.reason == "idle"
    probe = fake.calls("/api/generate")[0]
    assert probe["model"] == settings.models.triage and probe["options"]["num_predict"] == 1


async def test_dry_run_writes_nothing(settings, conn):
    server = FeedServer(conn)
    counts = await dry_run(settings, conn, fetcher=server.fetcher(), now=NOW)
    assert counts["sources"]["ok"] == 21 and counts["items"]["new"] > 50
    assert counts["stories"]["new"] > 50 and counts["stories"]["joined"] == 0
    assert count(conn, "runs") == 0 and count(conn, "items") == 0
    assert all(s.last_fetch_at is None for s in sources_repo.list_sources(conn))


async def test_assessed_story_joined_later_is_replaced_without_llm(settings, conn):
    first, _, _ = await _run(settings, conn, only_source="bleepingcomputer")
    story = next(s for s in stories_repo.stories_since(conn, NOW - timedelta(days=9))
                 if s.state == "assessed")
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>THN</title>'
        f"<item><title>{story.title.replace('&', '&amp;').replace('<', '&lt;')}</title>"
        "<link>https://thehackernews.com/2026/11/joined.html</link>"
        "<guid>thn-joined</guid><pubDate>Tue, 24 Nov 2026 20:00:00 +0000</pubDate>"
        "</item></channel></rss>"
    ).encode()
    server = FeedServer(conn)
    server.overrides["thehackernews"] = httpx.Response(
        200, content=feed, headers={"content-type": "application/rss+xml"})
    second, _, fake = await _run(settings, conn, server=server, only_source="thehackernews",
                                 now=NOW + timedelta(hours=1))
    assert second.stats["stories"] == {"new": 0, "joined": 1, "reopened": 0}
    after = stories_repo.get_story(conn, story.id)
    assert after.score == pytest.approx(story.score + settings.scoring.corroboration_bonus)
    assert chats(fake, "assess") == []  # placement only, no new assessment

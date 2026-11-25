"""GET /api/weeks, /api/weeks/{week} and the Markdown export (M29)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.week_export import md_link, md_text
from sidereal.bootstrap import migrate
from sidereal.db.connect import connect
from sidereal.db.feedback_repo import set_hidden
from sidereal.db.week_digests_repo import save_week_digest
from tests.factories import make_run, make_story

AT = datetime(2026, 11, 29, 20, 0, tzinfo=UTC)


def _client(settings, dist):
    return TestClient(create_app(settings, dist_dir=dist), base_url="http://testserver:8470")


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    return d


@pytest.fixture
def conn(settings):
    migrate(settings)
    c = connect(settings.db_path)
    yield c
    c.close()


@pytest.fixture
def client(settings, dist, conn):
    return _client(settings, dist)


@pytest.fixture
def run(conn):
    return make_run(conn, at=datetime(2026, 11, 1, tzinfo=UTC))


def _get(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    return r.json()


def _digest(conn, week, run, *, ids=(), overview="Overview.", headline="Headline"):
    save_week_digest(conn, week, overview=overview, headline=headline, story_ids=ids,
                     model="m", run_id=run, at=AT)


def _story(conn, run, day, hour=12, **kw):
    y, m, d = (int(x) for x in day.split("-"))
    return make_story(conn, run_id=run, first_seen=datetime(y, m, d, hour, tzinfo=UTC), **kw)


def test_list_empty_and_newest_first(client, conn, run):
    assert _get(client, "/api/weeks") == []
    _digest(conn, "2026-W53", run, ids=(1, 2))
    _digest(conn, "2027-W01", run)
    _digest(conn, "2026-W48", run, headline="H48")
    got = _get(client, "/api/weeks")
    assert [w["week"] for w in got] == ["2027-W01", "2026-W53", "2026-W48"]
    assert got[1] == {"week": "2026-W53", "label": "Week 53 · 28.12.2026 – 03.01.2027",
                      "start_day": "2026-12-28", "end_day": "2027-01-03",
                      "headline": "Headline", "story_count": 2,
                      "updated_at": "2026-11-29T20:00:00Z"}
    assert [w["week"] for w in _get(client, "/api/weeks?before=2027-W01&limit=1")] == [
        "2026-W53"]


@pytest.mark.parametrize("path", [
    "/api/weeks/2025-W53", "/api/weeks/2026-W54", "/api/weeks/2026-W00", "/api/weeks/2026-48",
    "/api/weeks/abc", "/api/weeks/2026-w48", "/api/weeks/2025-W53/export.md",
    "/api/weeks?before=2026-W99", "/api/weeks?limit=0",
])
def test_bad_week_is_422(client, path):
    assert client.get(path).status_code == 422


def test_bad_week_is_422_without_a_database(settings, dist):
    assert _client(settings, dist).get("/api/weeks/2025-W53").status_code == 422
    assert _client(settings, dist).get("/api/weeks/2026-W48").status_code == 503


def test_detail_without_digest_shows_the_live_set(client, conn, run):
    top = _story(conn, run, "2026-11-23", bucket="top", score=80.0)
    rel = _story(conn, run, "2026-11-29", bucket="relevant", score=60.0)
    _story(conn, run, "2026-11-25", bucket="side", score=30.0)
    _story(conn, run, "2026-11-30", bucket="top", score=90.0)  # next week
    got = _get(client, "/api/weeks/2026-W48")
    assert (got["week"], got["label"], got["start_day"], got["end_day"]) == (
        "2026-W48", "Week 48 · 23.11.2026 – 29.11.2026", "2026-11-23", "2026-11-29")
    assert (got["overview"], got["headline"], got["updated_at"]) == (None, None, None)
    assert [s["id"] for s in got["sections"]["top"]] == [top]
    assert [s["id"] for s in got["sections"]["relevant"]] == [rel]
    assert got["sections"]["side"] == got["sections"]["drop"] == []
    assert got["counts"] == {"top": 1, "relevant": 1, "side": 0, "drop": 0}


def test_detail_with_digest_and_hidden_story_left_out(client, conn, run):
    keep = _story(conn, run, "2026-11-24", bucket="top", score=80.0)
    hidden = _story(conn, run, "2026-11-24", bucket="top", score=85.0)
    _digest(conn, "2026-W48", run, ids=(keep, hidden), overview="Para one.\n\nPara two.")
    set_hidden(conn, hidden, True, at=AT)
    got = _get(client, "/api/weeks/2026-W48")
    assert (got["overview"], got["headline"]) == ("Para one.\n\nPara two.", "Headline")
    assert [s["id"] for s in got["sections"]["top"]] == [keep]
    assert got["sections"]["top"][0]["hidden"] is False
    assert hidden not in [s["id"] for s in got["sections"]["relevant"]]


def test_week_uses_local_days(client, conn, run):
    # Sunday 29.11.2026 23:30 UTC is still Sunday in London (GMT): W48.
    sid = _story(conn, run, "2026-11-29", hour=23, bucket="top", score=80.0)
    assert [s["id"] for s in _get(client, "/api/weeks/2026-W48")["sections"]["top"]] == [sid]


def test_export_is_escaped_markdown(client, conn, run):
    _story(conn, run, "2026-11-24", bucket="top", score=80.0,
           title="Exploit <script>alert(1)</script> [click](javascript:x) **bold**",
           summary="See www.evil.example and https://evil.example/x # not a heading",
           sources=("bleepingcomputer",), urls=("https://www.bleepingcomputer.com/a/b",))
    _story(conn, run, "2026-11-25", bucket="relevant", score=60.0, title="Plain relevant",
           urls=("javascript:alert(1)",))
    _digest(conn, "2026-W48", run, overview="# Heading?\n\n1. list? <b>x</b>",
            headline="Week _of_ `code`")
    r = client.get("/api/weeks/2026-W48/export.md")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="sidereal-2026-W48.md"'
    md = r.text
    assert md.startswith("# Sidereal: Week 48 · 23\\.11\\.2026 – 29\\.11\\.2026\n")
    assert "**Week \\_of\\_ \\`code\\`**" in md
    assert "\\# Heading?\n\n1\\. list? \\<b\\>x\\</b\\>" in md
    assert ("**Exploit \\<script\\>alert\\(1\\)\\</script\\> \\[click\\]\\(javascript\\:x\\)"
            " \\*\\*bold\\*\\***") in md
    assert "www\\.evil\\.example" in md and "https\\://evil\\.example/x \\# not" in md
    assert "<https://www.bleepingcomputer.com/a/b>" in md
    assert "javascript:alert" not in md
    assert "## TOP" in md and "## Relevant" in md and "Plain relevant" in md
    for raw in ("<script>", "<b>", "](", "](javascript"):
        assert raw not in md


def test_export_of_an_empty_week(client):
    md = client.get("/api/weeks/2027-W01/export.md").text
    assert md.count("Nothing this week.") == 2


def test_md_helpers():
    assert md_text("a\x00b c\n\nd") == "a b c d"
    assert md_link("https://x.example/a b") is None
    assert md_link("https://x.example/a>b") is None
    assert md_link("ftp://x.example/") is None
    assert md_link(None) is None
    assert md_link("https://x.example/a?b=1") == "<https://x.example/a?b=1>"

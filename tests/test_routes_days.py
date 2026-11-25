"""GET /api/days and /api/days/{day} (plan §10.1): list, counts, runs per local day, detail."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from sidereal.api.app import create_app
from sidereal.api.routes_days import day_bounds
from sidereal.bootstrap import migrate
from sidereal.config import ScoringSettings
from sidereal.db.connect import connect
from sidereal.db.digests_repo import save_day_digest
from sidereal.db.items_repo import items_for_story, set_content
from tests.factories import make_run, make_story, seed_demo

EMPTY = {"top": [], "relevant": [], "side": [], "drop": []}
ZERO = {"top": 0, "relevant": 0, "side": 0, "drop": 0}


def _t(day, hour, minute=0):
    """UTC datetime on July ``day`` 2026."""
    return datetime(2026, 7, day, hour, minute, tzinfo=UTC)


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
    return make_run(conn, at=_t(1, 0))  # 1 July: outside every day the tests look at


def _get(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(stories):
    return [s["id"] for s in stories]


def _digest(conn, day, run_id, headline="H", overview="O"):
    save_day_digest(conn, day, overview=overview, headline=headline, story_ids=[], model="m",
                    run_id=run_id, at=_t(14, 0))


def test_days_empty(client):
    assert _get(client, "/api/days") == []


@pytest.mark.parametrize("path", ["/api/days", "/api/days/2026-07-14"])
def test_no_database_is_503(settings, dist, path):
    assert _client(settings, dist).get(path).status_code == 503
    assert not settings.db_path.exists()


def test_days_list_shape(client, conn, run):
    make_run(conn, at=_t(13, 8))
    make_run(conn, at=_t(13, 12))
    make_run(conn, at=_t(14, 8))
    make_story(conn, run_id=run, first_seen=_t(13, 8, 10), bucket="top", score=80.0)
    make_story(conn, run_id=run, first_seen=_t(13, 8, 20))
    make_story(conn, run_id=run, first_seen=_t(13, 8, 20))
    make_story(conn, run_id=run, first_seen=_t(13, 9), state="assess_failed", bucket="side",
               score=None)
    make_story(conn, run_id=run, first_seen=_t(14, 9), bucket="side", score=30.0)
    _digest(conn, "2026-07-13", run, headline="H13")
    assert _get(client, "/api/days") == [
        {"day": "2026-07-14", "label": "Tuesday - 14.07.2026",
         "counts": {"top": 0, "relevant": 0, "side": 1}, "run_count": 1, "headline": None},
        {"day": "2026-07-13", "label": "Monday - 13.07.2026",
         "counts": {"top": 1, "relevant": 2, "side": 1}, "run_count": 2, "headline": "H13"}]


def test_days_counts_apply_caps(settings, dist, conn, run):
    for s in (90.0, 80.0, 70.0):
        make_story(conn, run_id=run, first_seen=_t(14, 9), bucket="top", score=s)
    capped = settings.model_copy(update={"scoring": ScoringSettings(top_cap=1)})
    assert _get(_client(capped, dist), "/api/days")[0]["counts"] == {
        "top": 1, "relevant": 2, "side": 0}


def test_run_count_uses_local_day(client, conn, run):
    make_run(conn, at=_t(13, 23, 30))
    make_story(conn, run_id=run, first_seen=_t(14, 8))
    make_story(conn, run_id=run, first_seen=_t(13, 8))
    assert [(d["day"], d["run_count"]) for d in _get(client, "/api/days")] == [
        ("2026-07-14", 1), ("2026-07-13", 0)]


def test_run_count_on_dst_day(client, conn, run):
    """25 Oct 2026 in London: 24 Oct 23:00 UTC to 26 Oct 00:00 UTC (25 hours)."""
    make_run(conn, at=datetime(2026, 10, 24, 23, 30, tzinfo=UTC))
    make_run(conn, at=datetime(2026, 10, 25, 23, 30, tzinfo=UTC))
    make_run(conn, at=datetime(2026, 10, 26, 0, 30, tzinfo=UTC))
    make_story(conn, run_id=run, first_seen=datetime(2026, 10, 25, 12, 0, tzinfo=UTC))
    assert _get(client, "/api/days")[0]["run_count"] == 2
    assert len(_get(client, "/api/days/2026-10-25")["runs"]) == 2


def test_runs_on_spring_dst_day(client, conn, run):
    """29 Mar 2026 in London: 29 Mar 00:00 UTC to 29 Mar 23:00 UTC (23 hours)."""
    inside = make_run(conn, at=datetime(2026, 3, 29, 22, 30, tzinfo=UTC))  # 23:30 BST
    make_run(conn, at=datetime(2026, 3, 29, 23, 30, tzinfo=UTC))  # 00:30 BST on the 30th
    make_run(conn, at=datetime(2026, 3, 28, 23, 30, tzinfo=UTC))  # 23:30 GMT on the 28th
    make_story(conn, run_id=run, first_seen=datetime(2026, 3, 29, 12, 0, tzinfo=UTC))
    assert [r["id"] for r in _get(client, "/api/days/2026-03-29")["runs"]] == [inside]
    assert _get(client, "/api/days")[0]["run_count"] == 1


def test_day_bounds_dst():
    assert day_bounds("2026-10-25", "Europe/London") == (
        datetime(2026, 10, 24, 23, 0, tzinfo=UTC), datetime(2026, 10, 26, 0, 0, tzinfo=UTC))
    assert day_bounds("2026-03-29", "Europe/London") == (
        datetime(2026, 3, 29, 0, 0, tzinfo=UTC), datetime(2026, 3, 29, 23, 0, tzinfo=UTC))


def test_days_limit_and_before(client, conn, run):
    for d in (11, 12, 13):
        make_story(conn, run_id=run, first_seen=_t(d, 9))
    assert [x["day"] for x in _get(client, "/api/days?limit=2")] == ["2026-07-13", "2026-07-12"]
    assert [x["day"] for x in _get(client, "/api/days?before=2026-07-13")] == [
        "2026-07-12", "2026-07-11"]
    assert _get(client, "/api/days?before=2026-07-11") == []


@pytest.mark.parametrize("query", ["?before=2026-7-1", "?before=2026-13-01", "?before=x",
                                   "?limit=0", "?limit=366"])
def test_days_bad_query(client, query):
    assert client.get("/api/days" + query).status_code == 422


def test_day_detail(client, conn, run):
    r1 = make_run(conn, at=_t(13, 4))
    r2 = make_run(conn, at=_t(13, 8), status="partial")
    make_run(conn, at=_t(12, 8))
    _digest(conn, "2026-07-13", r2, headline="H13", overview="O13")
    a = make_story(conn, run_id=r1, first_seen=_t(13, 4, 10), bucket="top", score=70.0)
    b = make_story(conn, run_id=r2, first_seen=_t(13, 8, 10), bucket="top", score=80.0)
    c = make_story(conn, run_id=r2, first_seen=_t(13, 8, 20), bucket="top", score=75.0)
    body = _get(client, "/api/days/2026-07-13")
    assert (body["day"], body["label"], body["overview"], body["headline"]) == (
        "2026-07-13", "Monday - 13.07.2026", "O13", "H13")
    assert body["runs"] == [
        {"id": r1, "started_at": "2026-07-13T04:00:00Z", "finished_at": "2026-07-13T04:05:00Z",
         "trigger": "timer", "status": "ok"},
        {"id": r2, "started_at": "2026-07-13T08:00:00Z", "finished_at": "2026-07-13T08:05:00Z",
         "trigger": "timer", "status": "partial"}]
    assert _ids(body["sections"]["top"]) == [b, c, a]
    assert body["counts"] == {"top": 3, "relevant": 0, "side": 0, "drop": 0}


def test_day_detail_empty_day(client):
    assert _get(client, "/api/days/2026-07-20") == {
        "day": "2026-07-20", "label": "Monday - 20.07.2026", "overview": None, "headline": None,
        "runs": [], "sections": EMPTY, "counts": ZERO}


def test_day_detail_uses_day_column(client, conn, run):
    late = make_story(conn, run_id=run, first_seen=_t(13, 23, 30))
    assert _ids(_get(client, "/api/days/2026-07-14")["sections"]["relevant"]) == [late]
    assert _get(client, "/api/days/2026-07-13")["sections"]["relevant"] == []


def test_day_detail_side_and_drop(client, conn, run):
    s = make_story(conn, run_id=run, first_seen=_t(13, 9), bucket="side", score=30.0)
    f = make_story(conn, run_id=run, first_seen=_t(13, 9), state="assess_failed", bucket="side",
                   score=None)
    d = make_story(conn, run_id=run, first_seen=_t(13, 9), bucket="drop", score=10.0)
    body = _get(client, "/api/days/2026-07-13")
    assert _ids(body["sections"]["side"]) == [s, f]
    assert body["sections"]["drop"] == []
    assert body["counts"] == {"top": 0, "relevant": 0, "side": 2, "drop": 1}
    assert _ids(_get(client, "/api/days/2026-07-13?include_drop=true")["sections"]["drop"]) == [d]


@pytest.mark.parametrize("day", ["2026-13-01", "2026-02-30", "2026-W29-1", "20260713", "x"])
def test_day_detail_bad_day(client, day):
    assert client.get(f"/api/days/{day}").status_code == 422


def test_bad_day_checked_before_db(settings, dist):
    assert _client(settings, dist).get("/api/days/2026-02-30").status_code == 422
    assert not settings.db_path.exists()


def test_day_detail_links_and_content(client, conn, run):
    sid = make_story(conn, run_id=run, first_seen=_t(13, 9), urls=("javascript:alert(1)",))
    set_content(conn, items_for_story(conn, sid)[0].id, text="FULL ARTICLE BODY", status="ok")
    r = client.get("/api/days/2026-07-13")
    story = r.json()["sections"]["relevant"][0]
    assert story["lead_url"] is None
    assert story["sources"][0]["url"] is None
    assert "FULL ARTICLE BODY" not in r.text
    assert "javascript:" not in r.text


def test_no_store_and_openapi(client):
    assert client.get("/api/days").headers["cache-control"] == "no-store"
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/days" in paths
    assert "/api/days/{day}" in paths


def test_demo_seed(client, conn):
    seed_demo(conn)
    days = _get(client, "/api/days")
    assert [(d["day"], d["run_count"], d["headline"]) for d in days] == [
        ("2026-07-14", 4, None), ("2026-07-13", 6, "Demo headline for 2026-07-13"),
        ("2026-07-12", 6, "Demo headline for 2026-07-12")]
    assert [d["counts"] for d in days] == [
        {"top": 1, "relevant": 2, "side": 3}, {"top": 2, "relevant": 4, "side": 4},
        {"top": 2, "relevant": 4, "side": 3}]
    assert len(_get(client, "/api/days/2026-07-12")["runs"]) == 6

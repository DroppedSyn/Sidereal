"""api/routes_settings.py (M27): effective config, overrides, notify status/test, focus CRUD.
Secrets never appear in a response; writes need the write guard and (auth on) a session."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sidereal.api import routes_settings
from sidereal.api.app import create_app
from sidereal.bootstrap import init
from sidereal.config import load_settings
from sidereal.db import settings_repo
from sidereal.db.connect import connect
from sidereal.notify.base import NotifyError
from tests.auth_helpers import add_user, auth_settings, fast_hasher, login, make_client  # noqa: F401
from tests.notify_helpers import PASSWORD, TOKEN, WEBHOOK, FakeSMTP, Recorder

ORIGIN = "http://testserver:8470"
WRITE = {"X-Sidereal": "1", "Origin": ORIGIN}
SECRETS = (WEBHOOK, TOKEN, PASSWORD)
AREA = {"key": "cloud-cost", "name": "Cloud cost", "tier": "side",
        "description": "Azure cost management, reservations, savings plans and FinOps news.",
        "keywords": [" FinOps ", "savings plan", "finops"], "enabled": True}


def client_for(settings, tmp_path):
    init(settings)
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    return TestClient(create_app(settings, dist_dir=dist), base_url=ORIGIN)


@pytest.fixture
def client(settings, tmp_path):
    return client_for(settings, tmp_path)


@pytest.fixture
def notify_client(config_file, tmp_path, monkeypatch):
    """Both channels configured, both secrets in the environment."""
    monkeypatch.setenv("SIDEREAL_DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setenv("SIDEREAL_SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("SIDEREAL_NOTIFY__CHANNELS", '["discord"]')
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_USER", "me")
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_FROM", "me@example.com")
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_TO", '["me@example.com"]')
    return client_for(load_settings(), tmp_path)


def no_secrets(text: str) -> None:
    for s in SECRETS:
        assert s not in text


# --- effective config, overrides ----------------------------------------------------------


def test_get_settings_shape(client):
    r = client.get("/api/settings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["config"]["scoring"]["top_cap"] == 8
    assert body["config"]["web"]["port"] == 8470
    assert body["overrides"] == {"scoring": {}, "budget": {}, "triage": {}}
    assert "top_threshold" in body["editable"]["scoring"]
    assert body["editable"]["triage"] == ["keep_min"]
    assert [c["name"] for c in body["notify"]] == ["email", "discord"]
    assert r.headers["cache-control"] == "no-store"


def test_put_overrides_round_trip(client, settings):
    r = client.put("/api/settings/overrides", headers=WRITE,
                   json={"scoring": {"top_cap": 4, "top_threshold": 75},
                         "budget": {"max_assess_per_run": 12}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overrides"]["scoring"] == {"top_cap": 4, "top_threshold": 75.0}
    assert body["config"]["scoring"]["top_cap"] == 4
    assert body["config"]["budget"]["max_assess_per_run"] == 12
    conn = connect(settings.db_path)
    try:
        assert settings_repo.get_overrides(conn) == {
            "scoring": {"top_cap": 4, "top_threshold": 75.0},
            "budget": {"max_assess_per_run": 12}}
    finally:
        conn.close()
    # replacing with an empty body resets everything to the file
    r = client.put("/api/settings/overrides", headers=WRITE, json={})
    assert r.json()["overrides"] == {"scoring": {}, "budget": {}, "triage": {}}
    assert client.get("/api/settings").json()["config"]["scoring"]["top_cap"] == 8


@pytest.mark.parametrize("body, detail", [
    ({"scoring": {"top_cap": 0}}, "scoring.top_cap"),
    ({"scoring": {"top_threshold": 101}}, "scoring.top_threshold"),
    ({"scoring": {"relevant_threshold": 80}}, "top > relevant > side"),
    ({"scoring": {"bogus": 1}}, "scoring.bogus"),
    ({"budget": {"max_run_minutes": 600}}, "budget.max_run_minutes"),
    ({"triage": {"keep_min": "2"}}, "triage.keep_min"),
])
def test_put_overrides_422(client, body, detail):
    r = client.put("/api/settings/overrides", headers=WRITE, json=body)
    assert r.status_code == 422 and detail in r.json()["detail"]
    assert client.get("/api/settings").json()["overrides"]["scoring"] == {}


def test_put_overrides_unknown_section_422(client):
    r = client.put("/api/settings/overrides", headers=WRITE, json={"web": {"port": 1}})
    assert r.status_code == 422


def test_overrides_reach_the_gazette(client, settings):
    """Views place with the effective caps (top_cap 1 → only one TOP story)."""
    from datetime import timedelta

    from sidereal.api.deps import get_now
    from sidereal.timeutil import utc_now
    from tests.factories import make_run, make_story

    now = utc_now()
    conn = connect(settings.db_path)
    try:
        run = make_run(conn, at=now - timedelta(hours=1))
        for i in range(3):
            make_story(conn, run_id=run, first_seen=now - timedelta(minutes=10 + i),
                       title=f"Top {i}", bucket="top", score=90.0 - i, tz="UTC")
    finally:
        conn.close()
    client.app.dependency_overrides[get_now] = lambda: now
    assert client.get("/api/gazette").json()["counts"]["top"] == 3
    client.put("/api/settings/overrides", headers=WRITE, json={"scoring": {"top_cap": 1}})
    assert client.get("/api/gazette").json()["counts"]["top"] == 1


# --- notify ------------------------------------------------------------------------------


def test_notify_not_configured(client):
    channels = client.get("/api/settings").json()["notify"]
    assert [(c["name"], c["enabled"], c["configured"]) for c in channels] == [
        ("email", False, False), ("discord", False, False)]
    assert "smtp_host" in channels[0]["problem"]
    assert "SIDEREAL_DISCORD_WEBHOOK_URL" in channels[1]["problem"]


def test_notify_configured_without_secrets(notify_client):
    r = notify_client.get("/api/settings")
    channels = r.json()["notify"]
    assert [(c["name"], c["enabled"], c["configured"], c["problem"]) for c in channels] == [
        ("email", False, True, None), ("discord", True, True, None)]
    no_secrets(r.text)


def test_secret_pasted_into_config_is_redacted(notify_client, config_file, tmp_path,
                                               monkeypatch):
    """Defence in depth: a secret that ended up in a config value is still not returned."""
    monkeypatch.setenv("SIDEREAL_MODELS__TRIAGE", PASSWORD)
    monkeypatch.setenv("SIDEREAL_NOTIFY__SMTP_FROM", f"x <{TOKEN}@example.com>")
    c = client_for(load_settings(), tmp_path)
    r = c.get("/api/settings")
    assert r.status_code == 200
    no_secrets(r.text)
    assert r.json()["config"]["models"]["triage"] == "[redacted]"


def test_notify_test_discord_sends(notify_client, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(routes_settings, "make_fetcher", rec.fetcher)
    r = notify_client.post("/api/settings/notify/test", headers=WRITE,
                           json={"channel": "discord"})
    assert r.json() == {"channel": "discord", "ok": True, "error": None}
    (payload,) = rec.payloads()
    assert payload["embeds"][0]["title"] == "Sidereal test notification"
    no_secrets(r.text)


def test_notify_test_email_sends(notify_client, monkeypatch):
    FakeSMTP.reset()
    monkeypatch.setattr("sidereal.notify.email.smtplib.SMTP", FakeSMTP)
    r = notify_client.post("/api/settings/notify/test", headers=WRITE, json={"channel": "email"})
    assert r.json()["ok"] is True
    assert FakeSMTP.instances[0].host == "smtp.example.com"
    no_secrets(r.text)


def test_notify_test_failure_hides_secret(notify_client, monkeypatch):
    rec = Recorder(lambda req: __import__("httpx").Response(404, text=str(req.url)))
    monkeypatch.setattr(routes_settings, "make_fetcher", rec.fetcher)
    r = notify_client.post("/api/settings/notify/test", headers=WRITE,
                           json={"channel": "discord"})
    body = r.json()
    assert r.status_code == 200 and body["ok"] is False and "404" in body["error"]
    no_secrets(r.text)


def test_notify_test_error_with_secret_is_redacted(notify_client, monkeypatch):
    """Even an error text that carries the secret (a channel bug) is redacted here."""
    async def leaky(*args, **kwargs):
        raise NotifyError(f"failed posting to {WEBHOOK} with {PASSWORD}")

    monkeypatch.setattr(routes_settings, "send_test", leaky)
    r = notify_client.post("/api/settings/notify/test", headers=WRITE,
                           json={"channel": "discord"})
    assert r.json()["ok"] is False and "[redacted]" in r.json()["error"]
    no_secrets(r.text)


def test_notify_test_not_configured(client):
    r = client.post("/api/settings/notify/test", headers=WRITE, json={"channel": "discord"})
    assert r.json()["ok"] is False and "not set" in r.json()["error"]


def test_notify_test_bad_channel_422(client):
    r = client.post("/api/settings/notify/test", headers=WRITE, json={"channel": "sms"})
    assert r.status_code == 422


def test_settings_responses_never_hold_secrets(notify_client, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(routes_settings, "make_fetcher", rec.fetcher)
    texts = [
        notify_client.get("/api/settings").text,
        notify_client.put("/api/settings/overrides", headers=WRITE,
                          json={"scoring": {"top_cap": 5}}).text,
        notify_client.get("/api/settings/focus").text,
        notify_client.get("/api/settings/sources").text,
        notify_client.post("/api/settings/notify/test", headers=WRITE,
                           json={"channel": "discord"}).text,
        notify_client.get("/api/openapi.json").text,
    ]
    for t in texts:
        no_secrets(t)


# --- focus areas -------------------------------------------------------------------------


def test_focus_list_is_the_seed(client):
    rows = client.get("/api/settings/focus").json()
    assert rows[0]["key"] == "azure-networking" and rows[0]["tier"] == "primary"
    assert all(len(r["description"]) >= 40 for r in rows)


def test_focus_create_edit_delete(client, settings):
    r = client.post("/api/settings/focus", headers=WRITE, json=AREA)
    assert r.status_code == 201, r.text
    assert r.json()["keywords"] == ["finops", "savings plan"]
    assert client.post("/api/settings/focus", headers=WRITE, json=AREA).status_code == 409
    edit = {k: v for k, v in AREA.items() if k != "key"} | {"tier": "secondary",
                                                            "enabled": False}
    r = client.put("/api/settings/focus/cloud-cost", headers=WRITE, json=edit)
    assert r.status_code == 200 and r.json()["tier"] == "secondary"
    assert r.json()["enabled"] is False
    from sidereal.db.focus_repo import list_focus_areas

    conn = connect(settings.db_path)
    try:
        (row,) = [f for f in list_focus_areas(conn, enabled_only=False) if f.key == "cloud-cost"]
        assert row.tier == "secondary" and row.enabled is False
        assert "cloud-cost" not in [f.key for f in list_focus_areas(conn)]
    finally:
        conn.close()
    assert client.delete("/api/settings/focus/cloud-cost", headers=WRITE).status_code == 204
    assert client.delete("/api/settings/focus/cloud-cost", headers=WRITE).status_code == 404
    assert client.put("/api/settings/focus/cloud-cost", headers=WRITE,
                      json=edit).status_code == 404


@pytest.mark.parametrize("change", [
    {"key": "Bad Key"}, {"key": "none"}, {"key": "-x"}, {"key": "k" * 41},
    {"tier": "urgent"}, {"name": ""}, {"name": "two\nlines"},
    {"description": "too short"}, {"description": "x" * 2001},
    {"description": "ok but has a control char \x07 " + "y" * 40},
    {"keywords": [""]}, {"keywords": ["   "]}, {"keywords": [3]}, {"keywords": "vnet"},
    {"keywords": ["a\tb"]}, {"keywords": ["k" * 61]}, {"keywords": [f"k{i}" for i in range(61)]},
    {"enabled": "yes"}, {"extra": 1},
])
def test_focus_422(client, change):
    r = client.post("/api/settings/focus", headers=WRITE, json=AREA | change)
    assert r.status_code == 422, (change, r.text)


def test_focus_path_key_checked(client):
    edit = {k: v for k, v in AREA.items() if k != "key"}
    assert client.put("/api/settings/focus/BAD%20KEY", headers=WRITE,
                      json=edit).status_code == 422


# --- write guard and auth ----------------------------------------------------------------


@pytest.mark.parametrize("method, path, body", [
    ("put", "/api/settings/overrides", {}),
    ("post", "/api/settings/focus", AREA),
    ("delete", "/api/settings/focus/azure-networking", None),
    ("post", "/api/settings/notify/test", {"channel": "discord"}),
])
@pytest.mark.parametrize("headers", [{"Origin": ORIGIN}, {"X-Sidereal": "1"},
                                     {"X-Sidereal": "1", "Origin": "http://evil.example"}])
def test_writes_need_the_guard(client, method, path, body, headers):
    kw = {"json": body} if body is not None else {}
    r = getattr(client, method)(path, headers=headers, **kw)
    assert r.status_code == 403
    assert client.get("/api/settings/focus").json()[0]["key"] == "azure-networking"


def test_auth_required(config_file, monkeypatch, tmp_path, fast_hasher):  # noqa: F811
    s = auth_settings(config_file, monkeypatch)
    init(s)
    c = make_client(s, tmp_path)
    for path in ("/api/settings", "/api/settings/focus", "/api/settings/sources"):
        assert c.get(path).status_code == 401
    assert c.put("/api/settings/overrides", headers=WRITE, json={}).status_code == 401
    assert c.post("/api/settings/focus", headers=WRITE, json=AREA).status_code == 401
    conn = connect(s.db_path)
    try:
        add_user(conn)
    finally:
        conn.close()
    assert login(c).status_code == 200
    assert c.get("/api/settings").status_code == 200
    assert c.post("/api/settings/focus", headers=WRITE, json=AREA).status_code == 201

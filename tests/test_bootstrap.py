"""`sidereal init`: dirs, migrations, idempotent seeding (covers defaults.py and db/seed.py)."""

import json
import shutil
from pathlib import Path

import pytest

from sidereal import paths
from sidereal.bootstrap import init
from sidereal.config import ConfigError
from sidereal.db.connect import connect
from sidereal.defaults import load_focus_areas, load_sources

FOCUS_KEYS = {"azure-networking", "network-architecture", "entra-identity", "ms-security",
              "network-security", "security-news", "industry"}


def test_seed_files_are_valid():
    sources = load_sources(paths.defaults_dir() / "sources.toml")
    focus = load_focus_areas(paths.defaults_dir() / "focus.toml")
    assert len(sources) == 21
    assert {f.key for f in focus} == FOCUS_KEYS
    msrc = next(s for s in sources if s.key == "msrc-update-guide")
    assert (msrc.kind, msrc.max_items, msrc.weight) == ("msrc", 300, 1.3)


def test_init_creates_db_and_seeds(settings):
    report = init(settings)
    assert report.migrations_applied == [1]
    assert report.sources_added == 21
    assert report.focus_areas_added == 7
    conn = connect(settings.db_path)
    row = conn.execute("SELECT * FROM sources WHERE key = 'tc-azure-architecture'").fetchone()
    assert row["kind"] == "rss" and row["weight"] == 1.2
    assert json.loads(row["options_json"])["max_bytes"] == 4_000_000
    tiers = dict(conn.execute("SELECT key, tier FROM focus_areas").fetchall())
    assert tiers["azure-networking"] == "primary" and tiers["industry"] == "side"


def test_reinit_is_idempotent_and_keeps_user_edits(settings, tmp_path: Path):
    init(settings)
    conn = connect(settings.db_path)
    with conn:
        conn.execute("UPDATE sources SET weight = 0.5, enabled = 0 WHERE key = 'krebs'")
        conn.execute("DELETE FROM sources WHERE key = 'schneier'")
        conn.execute("UPDATE focus_areas SET description = 'mine' WHERE key = 'industry'")
    second = init(settings)
    assert (second.migrations_applied, second.sources_added, second.focus_areas_added) == ([], 1, 0)
    krebs = conn.execute("SELECT weight, enabled FROM sources WHERE key = 'krebs'").fetchone()
    assert tuple(krebs) == (0.5, 0)
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == 21
    desc = conn.execute("SELECT description FROM focus_areas WHERE key = 'industry'").fetchone()
    assert desc[0] == "mine"


def test_new_seed_key_is_added_on_reinit(settings, tmp_path: Path):
    defaults = tmp_path / "defaults"
    shutil.copytree(paths.defaults_dir(), defaults)
    init(settings, defaults)
    with (defaults / "sources.toml").open("a") as f:
        f.write('\n[[source]]\nkey = "new-one"\nname = "New"\nkind = "rss"\n'
                'url = "https://example.org/feed"\n')
    assert init(settings, defaults).sources_added == 1


@pytest.mark.parametrize(
    "extra",
    [
        '[[source]]\nkey = "krebs"\nname = "dupe"\nkind = "rss"\nurl = "https://x.org/"\n',
        '[[source]]\nkey = "bad"\nname = "b"\nkind = "ftp"\nurl = "https://x.org/"\n',
        '[[source]]\nkey = "bad"\nname = "b"\nkind = "rss"\nurl = "http://x.org/"\n',
        '[[source]]\nkey = "bad"\nname = "b"\nkind = "rss"\nurl = "https://x.org/"\nweight = 3\n',
    ],
)
def test_invalid_seed_sources_rejected(tmp_path: Path, extra: str):
    path = tmp_path / "sources.toml"
    path.write_text((paths.defaults_dir() / "sources.toml").read_text() + "\n" + extra)
    with pytest.raises(ConfigError):
        load_sources(path)


def test_init_creates_private_state_dir(settings):
    init(settings)
    assert settings.state_dir.is_dir()
    assert (settings.state_dir / "backups").is_dir()
    assert settings.state_dir.stat().st_mode & 0o077 == 0

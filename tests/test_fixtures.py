"""Recorded fixtures (plan §6.6) stay parseable and non-empty."""

import json
from pathlib import Path

import feedparser
import pytest

from sidereal import paths
from sidereal.defaults import load_sources

FEEDS = Path(__file__).parent / "fixtures" / "feeds"
PAGES = Path(__file__).parent / "fixtures" / "pages"
XML = sorted(p for p in FEEDS.glob("*.xml") if p.stem != "tc-dead-board")


@pytest.mark.parametrize("path", XML, ids=lambda p: p.stem)
def test_xml_feed_fixture_parses(path: Path):
    data = path.read_bytes()
    assert len(data) <= 100_000
    parsed = feedparser.parse(data)
    assert not parsed.bozo, parsed.get("bozo_exception")
    assert 1 <= len(parsed.entries) <= (40 if path.stem == "msrc-update-guide" else 20)
    assert all(e.get("title") for e in parsed.entries)


def test_every_seed_source_has_a_fixture():
    keys = {s.key for s in load_sources(paths.defaults_dir() / "sources.toml")}
    have = {p.stem for p in FEEDS.iterdir()}
    assert keys <= have


def test_cisa_kev_fixture():
    data = json.loads((FEEDS / "cisa-kev.json").read_text())
    vulns = data["vulnerabilities"]
    assert data["count"] == len(vulns) == 20
    assert sum(v["vendorProject"] == "Microsoft" for v in vulns) >= 3
    assert {"cveID", "vendorProject", "product", "vulnerabilityName", "dateAdded"} <= set(vulns[0])


def test_hn_algolia_fixture():
    data = json.loads((FEEDS / "hn-cloud-sec.json").read_text())
    assert 1 <= len(data["hits"]) <= 20
    assert {"objectID", "title", "created_at_i", "points"} <= set(data["hits"][0])


def test_dead_board_fixture_is_an_empty_error_channel():
    parsed = feedparser.parse((FEEDS / "tc-dead-board.xml").read_bytes())
    assert parsed.feed.title == "Resource Not Found"
    assert parsed.entries == []


def test_html_fixture_is_not_a_feed():
    data = (FEEDS / "msrc-blog-html.html").read_bytes()
    assert len(data) <= 30_000
    assert feedparser.parse(data).entries == []


@pytest.mark.parametrize("path", sorted(PAGES.glob("*.html")), ids=lambda p: p.stem)
def test_article_page_fixtures(path: Path):
    assert 10_000 < len(path.read_bytes()) <= 200_000

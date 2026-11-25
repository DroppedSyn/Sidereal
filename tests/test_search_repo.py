"""db/search_repo.py + migration 0004_search (M26): sanitiser, sync triggers, backfill,
hidden stories, paging, snippets."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sidereal.db import search_repo
from sidereal.db.assessments_repo import save_assessment
from sidereal.db.connect import connect
from sidereal.db.feedback_repo import set_hidden
from sidereal.db.items_repo import insert_item
from sidereal.db.migrations import SQL_DIR, apply_migrations
from sidereal.db.search_repo import (
    HIT_END,
    HIT_START,
    MAX_TERMS,
    SearchQueryError,
    fts_query,
    search,
)
from sidereal.db.stories_repo import attach_item, delete_dropped_before
from tests.factories import ensure_source, make_run, make_story

NOW = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "s.db")
    apply_migrations(c)
    yield c
    c.close()


def story(conn, title="Demo story", **kw) -> int:
    run = make_run(conn, at=NOW - timedelta(hours=2))
    return make_story(conn, run_id=run, first_seen=NOW - timedelta(hours=1), tz="UTC",
                      title=title, **kw)


def ids(conn, q, **kw) -> list[int]:
    return [h.story_id for h in search(conn, q, **kw)]


def reassess(conn, sid, *, summary="AI summary.", why="Why it matters.", tags=("azure",)):
    save_assessment(conn, sid, model="m", prompt_version="assess.v1", relevance=2, urgency=2,
                    actionability=2, novelty=2, tags=tags, summary=summary, why=why,
                    raw={"focus": "none"}, duration_ms=1, at=NOW)


# --- sanitiser ---

@pytest.mark.parametrize(("text", "expected"), [
    ("entra flaw", '"entra" "flaw"'),
    ('"entra', '"entra"'),
    ('en"tra', '"entra"'),
    ("ent*", '"ent"*'),
    ("e*", '"e"'),
    ("*", None),
    ('"', None),
    ("", None),
    ("   \t\n ", None),
    ("OR", '"OR"'),
    ("a OR b", '"a" "OR" "b"'),
    ("NEAR(a b)", '"NEAR(a" "b)"'),
    ("title:entra", '"title:entra"'),
    ("-entra ^x", '"-entra" "^x"'),
    ("( ) : - + ^ .", None),
    ("a\x00b", '"a" "b"'),
])
def test_fts_query(text, expected):
    assert fts_query(text) == expected


def test_fts_query_caps_terms_and_length():
    q = fts_query(" ".join(f"w{i}" for i in range(40)))
    assert q is not None and q.count('"') == 2 * MAX_TERMS
    long = fts_query("x" * 1000)
    assert long == '"' + "x" * search_repo.MAX_TERM_CHARS + '"'


@pytest.mark.parametrize("text", [
    '"', '""', '"entra', "*", "**", "entra*", "OR", "AND", "NOT", "a OR", "OR b", "NEAR(",
    "NEAR(a b, 2)", "col:", "title:entra", "summary : x", "{title why}: x", "^entra",
    "-entra", "+", "(", ")", "a AND (b", "x" * 1000, ("ab " * 500)[:1000], "\x00", "é*",
    "'; DROP TABLE stories; --",
])
def test_injection_like_queries_never_raise(conn, text):
    story(conn, "Exploited Entra flaw")
    assert isinstance(search(conn, text), list)
    assert conn.execute("SELECT count(*) FROM stories").fetchone()[0] == 1


def test_operators_are_plain_words(conn):
    a = story(conn, "Entra flaw")
    story(conn, "Azure outage")
    # FTS syntax would make this "entra OR azure" (both); quoted it needs the word "or".
    assert ids(conn, "entra OR azure") == []
    assert ids(conn, "entra") == [a]
    # A column filter would search only titles; quoted it is the phrase "title entra".
    assert ids(conn, "title:entra") == []


def test_prefix_and_stemming(conn):
    a = story(conn, "Exploited Entra flaw")
    assert ids(conn, "ent*") == [a]
    assert ids(conn, "exploit") == [a]  # porter stemmer
    assert ids(conn, "ent") == []


def test_unknown_syntax_error_becomes_search_query_error(conn, monkeypatch):
    story(conn, "Entra flaw")
    monkeypatch.setattr(search_repo, "fts_query", lambda text: 'NEAR("a"')
    with pytest.raises(SearchQueryError):
        search(conn, "a")


def test_bad_limit(conn):
    with pytest.raises(ValueError):
        search(conn, "x", limit=0)


# --- what is indexed and kept in sync ---

def test_fields_indexed(conn):
    sid = story(conn, "Plain title", summary="Gateway summary", why="Bastion matters",
                tags=("firewall",), excerpt="Original peering excerpt")
    for word in ("plain", "gateway", "bastion", "firewall", "peering"):
        assert ids(conn, word) == [sid], word


def test_content_text_not_indexed(conn):
    sid = story(conn, "Plain title")
    conn.execute("UPDATE items SET content_text = 'secretword' WHERE story_id = ?", (sid,))
    conn.commit()
    assert ids(conn, "secretword") == []


def test_sync_after_assessment_update(conn):
    sid = story(conn, "Plain title", summary="Old gateway summary")
    assert ids(conn, "gateway") == [sid]
    reassess(conn, sid, summary="New bastion summary", why="Changed reason", tags=("dns",))
    assert ids(conn, "gateway") == []
    assert ids(conn, "bastion") == [sid]
    assert ids(conn, "dns") == [sid]
    assert ids(conn, "changed") == [sid]
    assert conn.execute("SELECT count(*) FROM story_search").fetchone()[0] == 1


def test_sync_first_assessment(conn):
    sid = story(conn, "Plain title", state="assess_failed", bucket=None)
    assert ids(conn, "gateway") == []
    reassess(conn, sid, summary="Gateway summary")
    assert ids(conn, "gateway") == [sid]


def test_sync_title_item_and_delete(conn):
    sid = story(conn, "Plain title", bucket="drop")
    conn.execute("UPDATE stories SET title = 'Renamed resolver' WHERE id = ?", (sid,))
    conn.commit()
    assert ids(conn, "resolver") == [sid] and ids(conn, "plain") == []
    conn.execute("UPDATE items SET excerpt = 'fresh peering text' WHERE story_id = ?", (sid,))
    conn.commit()
    assert ids(conn, "peering") == [sid]
    delete_dropped_before(conn, before=NOW + timedelta(days=1))
    assert conn.execute("SELECT count(*) FROM story_search").fetchone()[0] == 0


def test_second_item_excerpt_indexed(conn):
    sid = story(conn, "Plain title", sources=("bleepingcomputer", "krebs"),
                excerpt="shared words")
    assert ids(conn, "shared") == [sid]
    rows = conn.execute("SELECT excerpt FROM story_search WHERE rowid = ?", (sid,)).fetchone()
    assert rows[0].count("shared words") == 2


def test_sync_item_added_later(conn):
    sid = story(conn, "Plain title")
    run = make_run(conn, at=NOW)
    iid = insert_item(conn, source_id=ensure_source(conn, "krebs"), story_id=sid, guid="k:1",
                      url="https://krebs.example/1", canonical_url="https://krebs.example/1",
                      title="Other", title_norm="other", author=None, published_at=None,
                      first_seen_at=NOW, run_id=run, excerpt="late resolver report")
    assert iid is not None
    assert ids(conn, "resolver") == [sid]
    attach_item(conn, sid, item_id=iid, seen_at=NOW)
    assert ids(conn, "resolver") == [sid]


def test_backfill_existing_stories(tmp_path: Path):
    old = tmp_path / "old"
    old.mkdir()
    for path in sorted(SQL_DIR.glob("000[123]_*.sql")):
        shutil.copy(path, old / path.name)
    c = connect(tmp_path / "b.db")
    assert apply_migrations(c, old) == [1, 2, 3]
    a = story(c, "Exploited Entra flaw", summary="Gateway summary")
    b = story(c, "Azure outage", tags=("resolver",))
    shutil.copy(SQL_DIR / "0004_search.sql", old / "0004_search.sql")
    assert apply_migrations(c, old) == [4]
    assert ids(c, "entra") == [a]
    assert ids(c, "gateway") == [a]
    assert ids(c, "resolver") == [b]
    c.close()


# --- visibility, ordering, paging, snippets ---

def test_hidden_stories_excluded(conn):
    a = story(conn, "Entra flaw one")
    b = story(conn, "Entra flaw two")
    set_hidden(conn, a, True, at=NOW)
    assert ids(conn, "entra") == [b]
    set_hidden(conn, a, False, at=NOW)
    assert ids(conn, "entra") == [b, a]


def test_invisible_states_excluded(conn):
    story(conn, "Entra new", state="new", bucket=None)
    story(conn, "Entra filtered", state="filtered", bucket=None)
    f = story(conn, "Entra failed", state="assess_failed", bucket=None)
    d = story(conn, "Entra dropped", bucket="drop")
    assert ids(conn, "entra") == [d, f]


def test_newest_first_and_paging(conn):
    made = [story(conn, f"Entra flaw {i}") for i in range(5)]
    assert ids(conn, "entra") == made[::-1]
    assert ids(conn, "entra", limit=2) == [made[4], made[3]]
    assert ids(conn, "entra", limit=2, before=made[3]) == [made[2], made[1]]
    assert ids(conn, "entra", before=made[0]) == []


def test_rank_and_snippet_markers(conn):
    title_hit = story(conn, "Entra flaw", excerpt="nothing")
    excerpt_hit = story(conn, "Other news", excerpt="mentions <b>entra</b> once")
    hits = {h.story_id: h for h in search(conn, "entra")}
    assert hits[title_hit].rank < hits[excerpt_hit].rank  # title weighs more (lower = better)
    snip = hits[excerpt_hit].snippet
    assert f"{HIT_START}entra{HIT_END}" in snip
    assert "<b>" in snip and "<mark>" not in snip  # stored text as is; markers are not HTML

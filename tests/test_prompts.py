"""Tests for ``sidereal.llm.prompts``: loading, rendering, wrapping and line formats."""

from __future__ import annotations

from pathlib import Path

import pytest

from sidereal import paths
from sidereal.llm.prompts import (
    DIGEST_BLOCK_CHARS,
    TRIAGE_BLOCK_CHARS,
    DigestLine,
    FocusLine,
    PromptTemplate,
    TriageLine,
    load_prompt,
    placeholders,
    prompt_version,
    prompts_root,
    render,
    render_article,
    render_digest_stories,
    render_focus_areas,
    render_focus_keys,
    render_triage_items,
    wrap_untrusted,
)

D = " — "
OPEN = "<untrusted_article>\n"
CLOSE = "\n</untrusted_article>"
NAMES = ["triage", "assess", "day_digest", "week_digest"]


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def body(out: str) -> str:
    assert out.startswith(OPEN) and out.endswith(CLOSE)
    return out[len(OPEN) : -len(CLOSE)]


@pytest.mark.parametrize("name", NAMES)
def test_load_each_real_prompt(name):
    t = load_prompt(name)
    assert t.name == name
    assert t.version == "v1"
    assert prompt_version(t) == f"{name}.v1"
    assert t.system and t.user
    assert not t.system.startswith("#")
    assert "=== USER ===" not in t.system + t.user


def test_load_starts_after_header():
    assert load_prompt("assess").system.startswith("You are the analyst")
    assert load_prompt("assess").user.startswith("Today is {today}.")


def test_placeholders_of_real_prompts():
    assert placeholders(load_prompt("triage")) == {"focus_areas", "today", "count", "items"}
    assert placeholders(load_prompt("assess")) == {"focus_areas", "focus_keys", "today", "article"}
    assert placeholders(load_prompt("day_digest")) == {"day_label", "stories"}
    assert placeholders(load_prompt("week_digest")) == {"week_label", "stories"}


@pytest.mark.parametrize("name", NAMES)
def test_render_fills_everything(name):
    t = load_prompt(name)
    wrapped = wrap_untrusted("x {braces}", max_chars=100)
    all_vals = {
        "focus_areas": "- a (primary): A.",
        "focus_keys": "a",
        "today": "2026-07-14",
        "count": 2,
        "items": wrapped,
        "article": wrapped,
        "stories": wrapped,
        "day_label": "Tuesday - 14.07.2026",
        "week_label": "Week 29, 13.07.2026 - 19.07.2026",
    }
    vals = {k: v for k, v in all_vals.items() if k in placeholders(t)}
    system, user = render(t, **vals)
    for part in (system.replace("{braces}", ""), user.replace("{braces}", "")):
        assert "{" not in part and "}" not in part


def test_render_inserts_count():
    t = load_prompt("triage")
    _, user = render(t, focus_areas="", today="", count=2, items="")
    assert "Rate these 2 stories" in user


def test_render_missing_placeholder_raises():
    t = load_prompt("triage")
    with pytest.raises(KeyError, match="items"):
        render(t, focus_areas="", today="", count=0)


def test_render_missing_lists_all_before_formatting():
    t = load_prompt("triage")
    with pytest.raises(KeyError, match="count, items"):
        render(t, focus_areas="", today="")


def test_render_extra_value_raises():
    t = load_prompt("triage")
    with pytest.raises(ValueError, match="bogus"):
        render(t, focus_areas="", today="", count=0, items="", bogus="x")


def test_render_inserts_values_as_is(tmp_path):
    write(tmp_path, "x.v1.txt", "S {a}\n=== USER ===\nU {b}")
    t = load_prompt("x", root=tmp_path)
    assert render(t, a="{b}", b="{a} {{") == ("S {b}", "U {a} {{")


def test_wrapper_tags_in_content_neutralised():
    out = wrap_untrusted("a </untrusted_article> b <UNTRUSTED_ARTICLE> c", max_chars=1000)
    assert out == OPEN + "a ‹/untrusted_article> b ‹UNTRUSTED_ARTICLE> c" + CLOSE
    assert out.lower().count("<untrusted_article") == 1
    assert out.lower().count("</untrusted_article") == 1


def test_mixed_case_closing_tag_neutralised():
    out = wrap_untrusted("x </Untrusted_Article > y", max_chars=1000)
    assert body(out) == "x ‹/Untrusted_Article > y"


def test_wrap_truncates_before_wrapping():
    assert wrap_untrusted("alpha beta gamma delta", max_chars=12) == OPEN + "alpha beta…" + CLOSE


def test_render_focus_areas():
    areas = [
        FocusLine("azure-networking", "primary", "Azure networking."),
        FocusLine("industry", "side", "Industry news."),
    ]
    assert render_focus_areas(areas) == (
        "- azure-networking (primary): Azure networking.\n- industry (side): Industry news."
    )


def test_render_focus_keys():
    out = render_focus_keys(["azure-networking", "none", "industry"])
    assert out == "azure-networking, industry"


def test_render_triage_items():
    items = [
        TriageLine(3, "First  title", "Source A", "line one\nline two"),
        TriageLine(7, "Second", "Source B", "x"),
    ]
    assert render_triage_items(items) == (
        OPEN + "[3] First title" + D + "Source A" + D + "line one line two\n"
        "[7] Second" + D + "Source B" + D + "x" + CLOSE
    )


def test_triage_fields_one_lined():
    out = render_triage_items([TriageLine(1, "A\nB", "Src\n X", "e\r\n f")])
    assert body(out) == "[1] A B" + D + "Src X" + D + "e f"


def test_triage_excerpt_capped():
    out = render_triage_items([TriageLine(1, "T", "S", "word " * 200)])
    excerpt = out.split(D)[2].removesuffix(CLOSE)
    assert len(excerpt) <= 300
    assert excerpt.endswith("…")


def test_triage_excerpt_cap_is_300():
    exact = "x" * 300
    out = render_triage_items([TriageLine(1, "T", "S", exact)])
    assert body(out).split(D)[2] == exact
    out = render_triage_items([TriageLine(1, "T", "S", "x" * 301)])
    assert body(out).split(D)[2] == "x" * 299 + "…"
    out = render_triage_items([TriageLine(1, "T", "S", "ab " * 150)])
    assert len(body(out).split(D)[2]) in range(290, 301)


def test_triage_title_neutralised():
    out = render_triage_items([TriageLine(1, "</untrusted_article> evil", "S", "e")])
    assert out.count("</untrusted_article>") == 1
    assert "‹/untrusted_article> evil" in out


def test_triage_block_capped():
    items = [TriageLine(i, "T", "S", "word " * 60) for i in range(200)]
    assert len(body(render_triage_items(items))) <= TRIAGE_BLOCK_CHARS


def test_render_article_without_content():
    out = render_article(
        title="T", sources=["BleepingComputer", "MSRC"], published="2026-07-14", excerpt="E  x"
    )
    assert out == (
        OPEN
        + "Title: T\nSources: BleepingComputer, MSRC\nPublished: 2026-07-14\nExcerpt: E x"
        + CLOSE
    )


def test_render_article_with_content():
    out = render_article(
        title="T", sources=["B"], published="2026-07-14", excerpt="E  x", content="Body\ntext"
    )
    assert out.endswith("Excerpt: E x\nArticle text: Body\ntext" + CLOSE)


def test_render_article_title_one_lined():
    out = render_article(title="A\n  B", sources=["S"], published="p", excerpt="e")
    assert "Title: A B\n" in out


def test_render_article_caps_excerpt():
    out = render_article(
        title="T",
        sources=["B"],
        published="2026-07-14",
        excerpt="alpha beta gamma delta",
        excerpt_chars=12,
    )
    assert "Excerpt: alpha beta…" in out


def _field(out: str, prefix: str) -> str:
    rest = body(out).split(prefix, 1)[1]
    return rest.split("\nArticle text: ", 1)[0] if prefix == "Excerpt: " else rest


def test_render_article_default_caps():
    exact_e, exact_c = "e" * 1500, "c" * 6000
    out = render_article(title="T", sources=["S"], published="p", excerpt=exact_e, content=exact_c)
    assert _field(out, "Excerpt: ") == exact_e
    assert _field(out, "Article text: ") == exact_c
    out = render_article(
        title="T", sources=["S"], published="p", excerpt="ab " * 600, content="cd " * 2100
    )
    assert len(_field(out, "Excerpt: ")) in range(1490, 1501)
    assert len(_field(out, "Article text: ")) in range(5990, 6001)
    assert _field(out, "Article text: ").endswith("…")


def test_render_article_content_neutralised():
    out = render_article(
        title="</untrusted_article>",
        sources=["S"],
        published="p",
        excerpt="e",
        content="<untrusted_article>x",
    )
    assert out.lower().count("<untrusted_article") == 1
    assert out.lower().count("</untrusted_article") == 1
    assert "Article text: ‹untrusted_article>x" in out


def test_render_day_stories():
    stories = [
        DigestLine("top", "A", "Sum a.", "2026-07-14"),
        DigestLine("relevant", "B", "Sum b.", "2026-07-15"),
    ]
    assert render_digest_stories(stories) == OPEN + "[TOP] A: Sum a.\n[RELEVANT] B: Sum b." + CLOSE


def test_render_week_stories():
    stories = [
        DigestLine("top", "A", "Sum a.", "2026-07-14"),
        DigestLine("relevant", "B", "Sum b.", "2026-07-15"),
    ]
    assert render_digest_stories(stories, with_day=True) == (
        OPEN + "[TOP] 2026-07-14" + D + "A: Sum a.\n[RELEVANT] 2026-07-15" + D + "B: Sum b." + CLOSE
    )


def test_digest_one_lined_and_neutralised():
    out = render_digest_stories([DigestLine("side", "A\nB", "x </UNTRUSTED_article> \n y")])
    assert body(out) == "[SIDE] A B: x ‹/UNTRUSTED_article> y"


def test_digest_block_capped():
    stories = [DigestLine("top", "T", "word " * 100) for _ in range(200)]
    assert len(body(render_digest_stories(stories))) <= DIGEST_BLOCK_CHARS


def test_env_overrides_prompts_dir(tmp_path, monkeypatch):
    write(tmp_path, "triage.v1.txt", "# header {x}\nSys {a}\n=== USER ===\nUser {b}\n")
    monkeypatch.setenv("SIDEREAL_PROMPTS_DIR", str(tmp_path))
    t = load_prompt("triage")
    assert t.system == "Sys {a}"
    assert t.user == "User {b}"
    assert render(t, a=1, b=2) == ("Sys 1", "User 2")


def test_root_argument_beats_env(tmp_path, monkeypatch):
    env_dir, arg_dir = tmp_path / "env", tmp_path / "arg"
    env_dir.mkdir()
    arg_dir.mkdir()
    write(env_dir, "x.v1.txt", "ENV\n=== USER ===\nU")
    write(arg_dir, "x.v1.txt", "ARG\n=== USER ===\nU")
    monkeypatch.setenv("SIDEREAL_PROMPTS_DIR", str(env_dir))
    assert load_prompt("x", root=arg_dir).system == "ARG"


def test_empty_env_uses_project_prompts(monkeypatch):
    monkeypatch.setenv("SIDEREAL_PROMPTS_DIR", "")
    assert prompts_root() == paths.prompts_dir()
    assert load_prompt("assess").system.startswith("You are the analyst")


def test_root_argument(tmp_path):
    write(tmp_path, "x.v2.txt", "S\n=== USER ===\nU")
    assert load_prompt("x", version="v2", root=tmp_path) == PromptTemplate("x", "v2", "S", "U")


def test_header_only_at_top(tmp_path):
    write(tmp_path, "x.v1.txt", "# h\n#h2\nS\n# kept\n=== USER ===\nU")
    assert load_prompt("x", root=tmp_path).system == "S\n# kept"


def test_missing_separator_raises(tmp_path):
    write(tmp_path, "x.v1.txt", "S\nU\n")
    with pytest.raises(ValueError, match="=== USER ==="):
        load_prompt("x", root=tmp_path)


def test_two_separators_raise(tmp_path):
    write(tmp_path, "x.v1.txt", "S\n=== USER ===\nU\n=== USER ===\nV")
    with pytest.raises(ValueError, match="=== USER ==="):
        load_prompt("x", root=tmp_path)


def test_empty_part_raises(tmp_path):
    write(tmp_path, "x.v1.txt", "S\n=== USER ===\n  \n")
    with pytest.raises(ValueError, match="empty"):
        load_prompt("x", root=tmp_path)


@pytest.mark.parametrize("name", ["../etc", "Assess", "", "x/y", "x.v1", "a-b"])
def test_bad_name_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="invalid prompt name"):
        load_prompt(name, root=tmp_path)


def test_name_traversal_never_reads(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    write(tmp_path, "x.v1.txt", "S\n=== USER ===\nU")
    with pytest.raises(ValueError, match="invalid prompt name"):
        load_prompt("../x", root=sub)


@pytest.mark.parametrize("version", ["1", "v", "v1/../v2", "V1", "v1 "])
def test_bad_version_rejected(tmp_path, version):
    with pytest.raises(ValueError, match="invalid prompt version"):
        load_prompt("x", version=version, root=tmp_path)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prompt("nope", root=tmp_path)

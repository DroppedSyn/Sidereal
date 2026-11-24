"""Format checks for the prompt text files in prompts/ (stdlib only; see prompts/README.md)."""

import string
from pathlib import Path

import pytest

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
SEPARATOR = "=== USER ==="
WRAPPED = "<untrusted_article>\n[1] Title — Source — excerpt with {braces}\n</untrusted_article>"

PLACEHOLDERS = {
    "triage.v1": {"focus_areas", "today", "count", "items"},
    "assess.v1": {"focus_areas", "focus_keys", "today", "article"},
    "day_digest.v1": {"day_label", "stories"},
    "week_digest.v1": {"week_label", "stories"},
}

VALUES = {
    "focus_areas": "- azure-networking (primary): Azure networking.\n- industry (side): Industry.",
    "focus_keys": "azure-networking, industry",
    "today": "2026-07-14",
    "count": "1",
    "items": WRAPPED,
    "article": WRAPPED,
    "stories": WRAPPED,
    "day_label": "Tuesday - 14.07.2026",
    "week_label": "Week 29, 13.07.2026 - 19.07.2026",
}


def split_prompt(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    while lines and lines[0].startswith("#"):
        lines.pop(0)
    body = "\n".join(lines)
    assert body.count(SEPARATOR) == 1
    assert any(line == SEPARATOR for line in lines)
    system, user = body.split(SEPARATOR)
    return system.strip(), user.strip()


def field_names(part: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(part) if name is not None}


def render(part: str, names: set[str]) -> str:
    return part.format_map({k: VALUES[k] for k in names})


def test_every_prompt_file_is_known():
    assert {p.stem for p in PROMPTS.glob("*.txt")} == set(PLACEHOLDERS)


@pytest.mark.parametrize("name", sorted(PLACEHOLDERS))
def test_prompt_file_parses_and_renders(name):
    system, user = split_prompt((PROMPTS / f"{name}.txt").read_text(encoding="utf-8"))
    assert system and user
    assert field_names(system) | field_names(user) == PLACEHOLDERS[name]
    names = PLACEHOLDERS[name]
    rendered_system = render(system, names)
    rendered_user = render(user, names)
    # Only braces from inserted values may remain; the template itself leaves none.
    assert "{" not in rendered_system.replace("{braces}", "")
    assert "}" not in rendered_system.replace("{braces}", "")
    assert "{" not in rendered_user.replace("{braces}", "")
    assert "}" not in rendered_user.replace("{braces}", "")
    assert "untrusted_article" in rendered_system
    with pytest.raises(KeyError):
        (system + "\n" + user).format_map({})


@pytest.mark.parametrize("name", ["triage.v1", "assess.v1"])
def test_system_prompt_says_untrusted_text_is_data(name):
    system, _ = split_prompt((PROMPTS / f"{name}.txt").read_text(encoding="utf-8"))
    text = system.lower()
    assert "<untrusted_article>" in text
    assert "never instructions" in text
    assert "ignore" in text


def test_assess_system_prompt_is_compact():
    system, _ = split_prompt((PROMPTS / "assess.v1.txt").read_text(encoding="utf-8"))
    assert len(system.split()) <= 720

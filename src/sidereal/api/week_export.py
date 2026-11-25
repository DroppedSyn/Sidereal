"""Markdown export of a week (plan §16 M29: "export is plain Markdown with escaped content").

Pure. Every stored text (titles, summaries, the LLM overview, source names) is one-lined per
paragraph and backslash-escapes every character Markdown or GFM could read as syntax,
including ``.`` and ``:`` so GFM's bare-URL autolinks never fire on stored text. The only links
are the stories' ``lead_url`` values, http(s) only (rule 2), written as ``<url>`` autolinks and
left out when they hold a character that could end or break one.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sidereal.api.schemas import Story
from sidereal.timeutil import day_label
from sidereal.urls import is_http_url

_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~&=:])")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")
_SPACES = re.compile(r"\s+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_URL_BAD = re.compile(r"[\s<>\x00-\x1f\x7f]")


def md_text(text: str) -> str:
    """One line of escaped text: control characters → space, whitespace collapsed."""
    one = _SPACES.sub(" ", _CONTROL.sub(" ", text)).strip()
    return _SPECIAL.sub(r"\\\1", one)


def md_paragraphs(text: str) -> str:
    """Escaped paragraphs (blank-line separated in the input) joined by one blank line."""
    parts = (md_text(p) for p in _PARAGRAPH_BREAK.split(text))
    return "\n\n".join(p for p in parts if p)


def md_link(url: str | None) -> str | None:
    if url is None or not is_http_url(url) or _URL_BAD.search(url):
        return None
    return f"<{url}>"


def _story(s: Story) -> list[str]:
    sources = ", ".join(src.name for src in s.sources)
    meta = md_text(day_label(s.day) + (f" · {sources}" if sources else ""))
    lines = [f"- **{md_text(s.title)}** ({meta})"]
    if s.summary:
        lines.append(f"  {md_text(s.summary)}")
    if s.why:
        lines.append(f"  Why it matters: {md_text(s.why)}")
    link = md_link(s.lead_url)
    if link:
        lines.append(f"  {link}")
    return [line + "  " if i < len(lines) - 1 else line for i, line in enumerate(lines)]


def week_markdown(*, label: str, headline: str | None, overview: str | None,
                  top: Sequence[Story], relevant: Sequence[Story]) -> str:
    out = [f"# Sidereal: {md_text(label)}", ""]
    if headline:
        out += [f"**{md_text(headline)}**", ""]
    if overview:
        out += [md_paragraphs(overview), ""]
    for title, stories in (("TOP", top), ("Relevant", relevant)):
        out += [f"## {title}", ""]
        if not stories:
            out += ["Nothing this week.", ""]
        for s in stories:
            out += [*_story(s), ""]
    return "\n".join(out).rstrip("\n") + "\n"

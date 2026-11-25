"""Prompt loading, rendering and untrusted-text wrapping (plan §7.3, §7.4).

Prompt files live in ``prompts/<name>.<version>.txt`` (format in ``prompts/README.md``):
optional leading ``#`` header lines, the system part, a line ``=== USER ===``, the user part.
Parts are rendered with ``str.format_map``; values are inserted as is.

Every block carrying article-derived text (triage items, the assess article, digest stories)
is wrapped in ``<untrusted_article>`` tags, with any such tag inside the text neutralised
(``<`` → ``‹``) first. Focus areas and keys come from config and are not wrapped.
"""

from __future__ import annotations

import os
import re
import string
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sidereal import paths
from sidereal.textclean import truncate

ENV_DIR = "SIDEREAL_PROMPTS_DIR"
SEPARATOR = "=== USER ==="
TAG = "untrusted_article"
TRIAGE_EXCERPT_CHARS = 300
TRIAGE_BLOCK_CHARS = 20_000
DIGEST_BLOCK_CHARS = 40_000

_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
_VERSION_RE = re.compile(r"v[0-9]+")
_TAG_RE = re.compile(r"<(/?)(untrusted_article)", re.IGNORECASE)
_DASH = " — "


@dataclass(frozen=True)
class PromptTemplate:
    name: str      # "assess"
    version: str   # "v1"
    system: str
    user: str


@dataclass(frozen=True)
class FocusLine:
    key: str
    tier: str
    description: str


@dataclass(frozen=True)
class TriageLine:
    id: int
    title: str
    source: str
    excerpt: str


@dataclass(frozen=True)
class DigestLine:
    bucket: str
    title: str
    summary: str
    day: str = ""


def prompts_root() -> Path:
    """``$SIDEREAL_PROMPTS_DIR`` if set and non-empty (read at call time), else ``prompts/``."""
    env = os.environ.get(ENV_DIR, "")
    return Path(env) if env else paths.prompts_dir()


def load_prompt(name: str, *, version: str = "v1", root: Path | None = None) -> PromptTemplate:
    """Load and split ``<root>/<name>.<version>.txt``; ValueError on a bad name or format."""
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"invalid prompt name: {name!r}")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(f"invalid prompt version: {version!r}")
    path = (root if root is not None else prompts_root()) / f"{name}.{version}.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    start = 0
    while start < len(lines) and lines[start].startswith("#"):
        start += 1
    lines = lines[start:]
    seps = [i for i, line in enumerate(lines) if line == SEPARATOR]
    if len(seps) != 1:
        raise ValueError(f"{path.name}: needs exactly one line {SEPARATOR!r}, found {len(seps)}")
    system = "\n".join(lines[: seps[0]]).strip()
    user = "\n".join(lines[seps[0] + 1 :]).strip()
    if not system or not user:
        raise ValueError(f"{path.name}: empty system or user part")
    return PromptTemplate(name=name, version=version, system=system, user=user)


def placeholders(t: PromptTemplate) -> frozenset[str]:
    """Placeholder names used in the system and user parts."""
    names: set[str] = set()
    for part in (t.system, t.user):
        for _, field, _, _ in string.Formatter().parse(part):
            if field is not None:
                names.add(field)
    return frozenset(names)


def render(t: PromptTemplate, **values: object) -> tuple[str, str]:
    """Return ``(system, user)``; a missing value → KeyError, an unused value → ValueError."""
    wanted = placeholders(t)
    missing = wanted - values.keys()
    if missing:
        raise KeyError(", ".join(sorted(missing)))
    extra = values.keys() - wanted
    if extra:
        raise ValueError(f"unused values: {', '.join(sorted(extra))}")
    mapping = {k: str(v) for k, v in values.items()}
    return t.system.format_map(mapping), t.user.format_map(mapping)


def prompt_version(t: PromptTemplate) -> str:
    """The file stem, e.g. ``assess.v1``."""
    return f"{t.name}.{t.version}"


def neutralise(text: str) -> str:
    """``<untrusted_article`` / ``</untrusted_article`` (any case) → ``‹…``."""
    return _TAG_RE.sub(r"‹\1\2", text)


def wrap_untrusted(text: str, *, max_chars: int) -> str:
    """Truncate, neutralise wrapper tags, then wrap in ``<untrusted_article>`` tags."""
    body = neutralise(truncate(text, max_chars))
    return f"<{TAG}>\n{body}\n</{TAG}>"


def _one_line(s: str) -> str:
    return " ".join(s.split())


def render_focus_areas(areas: Iterable[FocusLine]) -> str:
    """``- key (tier): description`` per line, description verbatim; not wrapped."""
    return "\n".join(f"- {a.key} ({a.tier}): {a.description}" for a in areas)


def render_focus_keys(keys: Iterable[str]) -> str:
    """Comma-separated keys without ``none``."""
    return ", ".join(k for k in keys if k != "none")


def render_triage_items(items: Iterable[TriageLine]) -> str:
    """Wrapped block, ``[id] title — source — excerpt`` per line (excerpt ≤ 300, one line)."""
    lines = [
        f"[{i.id}] {_one_line(i.title)}{_DASH}{_one_line(i.source)}{_DASH}"
        f"{truncate(_one_line(i.excerpt), TRIAGE_EXCERPT_CHARS)}"
        for i in items
    ]
    return wrap_untrusted("\n".join(lines), max_chars=TRIAGE_BLOCK_CHARS)


def render_article(
    *,
    title: str,
    sources: Sequence[str],
    published: str,
    excerpt: str,
    content: str | None = None,
    excerpt_chars: int = 1500,
    content_chars: int = 6000,
) -> str:
    """Wrapped block: Title, Sources, Published, Excerpt lines and, with content, Article text."""
    lines = [
        f"Title: {_one_line(title)}",
        f"Sources: {', '.join(sources)}",
        f"Published: {published}",
        f"Excerpt: {truncate(_one_line(excerpt), excerpt_chars)}",
    ]
    if content:
        lines.append(f"Article text: {truncate(content.strip(), content_chars)}")
    return wrap_untrusted("\n".join(lines), max_chars=excerpt_chars + content_chars + 1000)


def render_digest_stories(stories: Iterable[DigestLine], *, with_day: bool = False) -> str:
    """Wrapped block, ``[TOP] title: summary`` (or ``[TOP] day — title: summary``) per line."""
    lines = []
    for s in stories:
        day = f"{s.day}{_DASH}" if with_day else ""
        lines.append(f"[{s.bucket.upper()}] {day}{_one_line(s.title)}: {_one_line(s.summary)}")
    return wrap_untrusted("\n".join(lines), max_chars=DIGEST_BLOCK_CHARS)

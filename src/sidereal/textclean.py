"""Untrusted HTML/text → clean plain text (plan §1 rule 2, §6.3). Pure, stdlib only.

Public API:
- ``to_text(html_or_text)``: HTML or plain text → plain text. Paragraphs are separated by a blank
  line, ``<br>`` is a line break, list items start with ``• ``. Entities are decoded exactly once
  (``&amp;lt;b&amp;gt;`` → the literal text ``&lt;b&gt;``).
- ``clean_title(s, max_len=300)``: ``to_text`` on one line, truncated at a word boundary.
- ``truncate(text, max_chars)``: cut at a word boundary, append ``…``; never longer than max_chars.
- ``excerpt(html, max_chars=1500)``: ``truncate(to_text(html), max_chars)``.

Guarantees: never raises on malformed markup; linear-ish in the input size; the output has no
control characters except ``\\n``, no zero-width or bidi-override characters, NFC normalised.
Markup is never passed through: a ``<`` left in raw text that could start a tag (``<`` + letter,
``/``, ``!``, ``?``, or at the end of a chunk) becomes ``‹``. A ``<`` that came from an entity
(``&lt;``) is decoded text and stays ``<``; the front end renders all of this as text anyway.

Input with no tag-like ``<`` is treated as plain text: its line breaks are kept and entities are
decoded once with ``html.unescape``. Otherwise it is parsed as HTML: whitespace in text collapses
(except inside ``<pre>``) and only block elements make line breaks.
"""

from __future__ import annotations

import html
import re
import unicodedata
from html.entities import html5
from html.parser import HTMLParser

__all__ = ["clean_title", "excerpt", "to_text", "truncate"]

# Contents dropped entirely (with everything nested inside).
_SKIP = frozenset(
    {"script", "style", "iframe", "noscript", "svg", "template", "head", "title", "object",
     "math", "select", "textarea"}
)
# Elements that start/end a paragraph (blank line around them).
_BLOCK = frozenset(
    {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "section", "article",
     "header", "footer", "aside", "nav", "main", "ul", "ol", "dl", "table", "figure",
     "figcaption", "address", "form", "fieldset", "details", "summary", "center", "hr"}
)
# Elements that end a line (single break).
_LINE = frozenset({"tr", "dt", "dd", "caption"})  # <li> starts its own line
_CELL = frozenset({"td", "th"})

_PARA = "\x00P"  # paragraph-break marker (NUL never survives cleaning, so it can't be forged)
_TAGLIKE = re.compile(r"<[A-Za-z!/?]")
_RAW_LT = re.compile(r"<(?=[A-Za-z!/?]|$)")
_WS = re.compile(r"\s+")
# Zero-width, bidi marks/embeddings/overrides/isolates, BOM, soft hyphen: removed.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00ad]")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_HSPACE = re.compile(r"[^\S\n]+")
_MANY_NL = re.compile(r"\n{3,}")


def _decode_entity(name: str) -> str:
    """Decode one named entity, once. Unknown names stay literal."""
    if name + ";" in html5:
        return html5[name + ";"]
    return html.unescape("&" + name)  # legacy forms like "&ampx" → "&x"; unknown → unchanged


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)  # we decode entities ourselves, exactly once
        self.out: list[str] = []
        self.skip: list[str] = []
        self.pre = 0

    def _text(self, text: str) -> None:
        if self.skip:
            return
        if not self.pre:
            text = _WS.sub(" ", text)
        self.out.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip.append(tag)
        elif self.skip:
            return
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            self.out.append("\n• ")
        elif tag in _BLOCK:
            self.pre += tag == "pre"
            self.out.append(_PARA)
        elif tag in _LINE:
            self.out.append("\n")
        elif tag in _CELL:
            self.out.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _SKIP:  # <svg/> has no content to skip
            self.handle_starttag(tag, attrs)
            if tag in _BLOCK and tag != "hr":
                self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag in self.skip:  # close the innermost matching skipped element
                del self.skip[len(self.skip) - 1 - self.skip[::-1].index(tag):]
            return
        if tag in _BLOCK:
            if tag == "pre" and self.pre:
                self.pre -= 1
            self.out.append(_PARA)
        elif tag in _LINE:
            self.out.append("\n")
        elif tag == "br":  # "</br>" is treated as <br> by browsers
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        self._text(_RAW_LT.sub("‹", data))

    def handle_entityref(self, name: str) -> None:
        self._text(_decode_entity(name))

    def handle_charref(self, name: str) -> None:
        self._text(html.unescape(f"&#{name};"))

    # Comments, declarations, processing instructions and CDATA are dropped (base class no-ops).


def _finish(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " "))
    text = _HSPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return _MANY_NL.sub("\n\n", text).strip()


def to_text(html_or_text: str) -> str:
    """Convert untrusted HTML (or plain text) to clean plain text. Never raises on bad markup."""
    if not html_or_text:
        return ""
    if not _TAGLIKE.search(html_or_text):
        return _finish(html.unescape(html_or_text.replace("\x00", "")))
    parser = _TextExtractor()
    try:
        parser.feed(html_or_text.replace("\x00", ""))
        parser.close()
    except Exception:  # defensive: html.parser is lenient, but malformed input must never raise
        pass
    joined = "".join(parser.out).replace(_PARA, "\n\n")
    return _finish(joined)


def truncate(text: str, max_chars: int) -> str:
    """Shorten ``text`` to at most ``max_chars`` characters, cutting at a word boundary + ``…``."""
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return "…"[:max(max_chars, 0)]
    cut = text[: max_chars - 1]
    if not text[max_chars - 1].isspace():
        space = max(cut.rfind(" "), cut.rfind("\n"))
        if space > (max_chars - 1) // 2:  # don't throw away more than half for one long word
            cut = cut[:space]
    return cut.rstrip() + "…"


def clean_title(s: str, max_len: int = 300) -> str:
    """Plain-text, single-line title (all whitespace runs → one space), at most ``max_len``."""
    return truncate(" ".join(to_text(s).split()), max_len)


def excerpt(html_text: str, max_chars: int = 1500) -> str:
    """Plain-text excerpt of untrusted HTML, at most ``max_chars`` characters."""
    return truncate(to_text(html_text), max_chars)

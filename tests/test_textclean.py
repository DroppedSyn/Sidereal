"""Tests for ``sidereal.textclean`` (plan §6.3, rule 2). Written by Claude (security module)."""

from __future__ import annotations

import re
import time

import feedparser
import pytest

from sidereal.textclean import clean_title, excerpt, to_text, truncate
from tests.conftest import FIXTURES

# `<` followed by something that could start a tag.
TAG_START = re.compile(r"<[A-Za-z/!?]")
REAL_TAG = re.compile(r"</?(p|a|div|span|img|br|li|ul|ol|h[1-6]|strong|em|b|i|pre|code|table)\b")


def test_entities_decoded_once() -> None:
    assert to_text("<p>&amp;lt;script&amp;gt;</p>") == "&lt;script&gt;"
    assert to_text("&amp;lt;script&amp;gt;") == "&lt;script&gt;"  # plain-text path too
    assert to_text("&amp;amp;") == "&amp;"
    assert to_text("<b>&#38;lt;i&#38;gt;</b>") == "&lt;i&gt;"
    assert clean_title("Fish &amp;amp; chips") == "Fish &amp; chips"


def test_entities_decoded() -> None:
    assert to_text("<p>a &lt;b&gt; &#60;i&#x3e; &eacute; &hellip; &nbsp;x</p>") == "a <b> <i> é … x"
    assert to_text("AT&T &unknown; & co") == "AT&T &unknown; & co"
    assert to_text("<p>bad &#0; &#xFFFFFFFF; ref</p>") == "bad � � ref"


def test_paragraphs_breaks_and_lists() -> None:
    src = "<h2>Title</h2><p>One\n  two</p><p>Three<br>four</p><ul><li>a</li><li>b</li></ul>end"
    assert to_text(src) == "Title\n\nOne two\n\nThree\nfour\n\n• a\n• b\n\nend"


def test_dropped_elements() -> None:
    src = (
        "<head><title>t</title><style>p{}</style></head><p>keep</p><script>alert(1)</script>"
        "<iframe src=x>frame</iframe><noscript>ns</noscript><svg><text>s</text></svg>"
        "<template><b>tpl</b></template><!-- comment --><![CDATA[cdata]]><?php echo 1 ?>tail"
    )
    assert to_text(src) == "keep\n\ntail"


def test_whitespace_normalised() -> None:
    assert to_text("<p>  a \t b  </p>\n\n\n\n<p>c</p>") == "a b\n\nc"
    assert to_text("plain\r\n\r\n\r\n\r\ntext   with\tspaces \n next") == (
        "plain\n\ntext with spaces\nnext"
    )
    assert to_text("<pre>a\n  b</pre>") == "a\nb"
    assert to_text("") == ""
    assert to_text("   ") == ""


def test_control_and_invisible_chars_removed() -> None:
    src = "a‮evil‬ b​ c⁦d⁩ ﻿e\x07f\x1b[31m g­h"
    out = to_text(src)
    assert out == "aevil b cd e f [31m gh"  # controls become spaces, invisibles vanish
    for ch in "​‎‏‪‮⁦⁩﻿\x00\x07\x1b":
        assert ch not in to_text(f"<p>x{ch}y</p>")
    assert to_text("<p>&#x202E;rtl&#8203;</p>") == "rtl"  # also when it came from an entity


def test_nfc_normalised() -> None:
    assert to_text("é") == "é"


XSS_CORPUS = [
    "<img src=x onerror=alert(1)>",
    "x <img src=x onerror=alert(1)",
    "<scr<script>ipt>alert(1)</script>",
    "<svg/onload=alert(1)>",
    "<svg><script>alert(1)</script></svg>after",
    "<!-- <script>alert(1)</script> -->ok",
    "<a href='javascript:alert(1)'>click</a>",
    "<iframe src=javascript:alert(1)></iframe>",
    "<<script>script>alert(1)<</script>/script>",
    "<div><p>unclosed <b>bold <i>it",
    "<a href=\"x>y",
    "</",
    "<div>x</div><",
    "<!--<img src=x onerror=alert(1)>",
    "<style><img src=x onerror=alert(1)></style>",
    "<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>",
    "<details open ontoggle=alert(1)>",
    "<body onload=alert(1)>text",
    "<IMG SRC=JaVaScRiPt:alert('XSS')>",
    "<<<a>>>",
    "<p>a</p\n><b>c</b >",
]


@pytest.mark.parametrize("src", XSS_CORPUS)
def test_xss_corpus_leaves_no_markup(src: str) -> None:
    out = to_text(src)
    assert not TAG_START.search(out), out
    assert "onerror" not in out and "onload" not in out


def test_entity_markup_is_text_not_removed() -> None:
    # Escaped markup is content: it is decoded once into literal text (rendered as text by the UI).
    assert to_text("<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>") == "<script>alert(1)</script>"


def test_plain_text_passes_through() -> None:
    assert to_text("Just a title: 5 < 6 & 7 > 3") == "Just a title: 5 < 6 & 7 > 3"


def test_malformed_never_raises() -> None:
    for src in ["<", "<a", "<a b='", "&", "&#", "&#x", "<!", "<!--", "<?", "</a", "<![CDATA[",
                "<p>" * 1000, "</p>" * 1000, "\x00<p>\x00</p>", "<\x00script>"]:
        assert isinstance(to_text(src), str)


def test_large_input_is_fast() -> None:
    inputs = [
        "<p>Some <b>bold</b> text &amp; an entity.</p>\n" * 50_000,
        "<a " * 600_000,
        "<div>" * 400_000,
        "&" * 2_000_000,
        "<a b=\"x" * 300_000,
    ]
    for src in inputs:
        assert len(src) >= 1_800_000
        start = time.perf_counter()
        to_text(src)
        assert time.perf_counter() - start < 2.0


@pytest.mark.parametrize("name", ["tc-azure-architecture.xml", "krebs.xml", "sans-isc.xml",
                                  "ms-security-blog.xml"])
def test_real_feed_descriptions(name: str) -> None:
    feed = feedparser.parse((FIXTURES / "feeds" / name).read_bytes())
    bodies = []
    for entry in feed.entries:
        bodies.append(entry.get("summary", ""))
        bodies += [c.get("value", "") for c in entry.get("content", [])]
    assert any("<p" in b or "<a " in b for b in bodies)  # the fixture really has markup
    for body in bodies:
        out = to_text(body)
        # Escaped code in articles (`&lt;sensor-ip&gt;`) legitimately decodes to `<sensor-ip>`,
        # so check for the real tags the fixtures use.
        assert not REAL_TAG.search(out), REAL_TAG.search(out)
        assert "\n\n\n" not in out and out == out.strip()


def test_truncate() -> None:
    assert truncate("short", 10) == "short"
    assert truncate("exactly10!", 10) == "exactly10!"
    assert truncate("hello world foo", 8) == "hello…"
    assert truncate("hello world foo", 12) == "hello world…"
    assert truncate("hello world", 7) == "hello…"
    assert truncate("supercalifragilistic", 8) == "superca…"  # one long word: hard cut
    assert truncate("ab cdefghijklmnop", 10) == "ab cdefgh…"  # boundary too early: hard cut
    assert truncate("hello", 1) == "…"
    assert truncate("hello", 0) == ""
    for n in range(0, 40):
        assert len(truncate("the quick brown fox jumps over the lazy dog", n)) <= max(n, 0)


def test_clean_title() -> None:
    assert clean_title("  <b>Big</b>\n\n news &amp; <i>more</i>  ") == "Big news & more"
    assert clean_title("<p>a</p><p>b</p><ul><li>c</li></ul>") == "a b • c"
    long = clean_title("word " * 100)
    assert len(long) <= 300 and long.endswith("word…")
    assert clean_title("abc def", max_len=5) == "abc…"


def test_excerpt() -> None:
    out = excerpt("<p>" + "lorem ipsum " * 300 + "</p>")
    assert len(out) <= 1500 and out.endswith("…") and "<" not in out
    assert excerpt("<p>a</p><p>b</p>") == "a\n\nb"
    assert excerpt("<p>hello world</p>", max_chars=8) == "hello…"

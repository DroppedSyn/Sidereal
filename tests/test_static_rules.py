"""Static rules over ``src/sidereal`` and ``web/src`` (plan §1, §10.4, §14).

Each rule is an AST check in ``check_python`` (or a grep for the front end), run over the real
tree and also over small snippets so the checks themselves can't silently go hollow.

A line may opt out of the SQL-formatting rule with a trailing ``# sql-ok: <reason>`` comment, used
only where an identifier comes from a fixed whitelist and a brief says so.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "sidereal"
WEB_SRC = ROOT / "web" / "src"

# module prefix -> files (relative to src/sidereal) allowed to import it; empty = nowhere.
IMPORT_ALLOW: dict[str, set[str]] = {
    "httpx": {"net/fetch.py", "llm/ollama.py"},
    "socket": {"net/fetch.py", "net/guard.py"},
    "requests": set(),
    "urllib.request": set(),
    "urllib3": set(),
    "http.client": set(),
    "aiohttp": set(),
    "subprocess": {"api/routes_runs.py"},
}
SUBPROCESS_ALLOWED = {"api/routes_runs.py"}
SUBPROCESS_CALLS = re.compile(
    r"^(os\.(system|popen|exec\w*|spawn\w*|posix_spawn\w*)|asyncio\.create_subprocess_\w+)$"
)
SQL_ALLOWED_PREFIX = "db/"
SQL = re.compile(
    r"\b(SELECT\b[\s\S]*\bFROM|INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM"
    r"|CREATE\s+(TABLE|INDEX|UNIQUE|VIRTUAL|TRIGGER|VIEW)|DROP\s+(TABLE|INDEX|TRIGGER|VIEW)"
    r"|ALTER\s+TABLE|PRAGMA\s+\w+)\b",
    re.IGNORECASE,
)
DB_CALLS = {"execute", "executemany", "executescript"}
FRONTEND_BANNED = re.compile(
    r"dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML|document\.write"
    r"|\beval\s*\(|new\s+Function\s*\("
)


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _imported(tree: ast.AST) -> list[tuple[str, int]]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append((node.module, node.lineno))
            names += [(f"{node.module}.{a.name}", node.lineno) for a in node.names]
    return names


def _docstring_ids(tree: ast.AST) -> set[int]:
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }


def _const_text(node: ast.AST) -> str | None:
    """Literal text of a str constant or f-string (placeholders become ``x``)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "x" for v in node.values)
    return None


def _formatted_sql(node: ast.AST) -> bool:
    """f-string, ``%`` or ``.format`` / ``+`` building a SQL string from values."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values) and bool(
            SQL.search(_const_text(node) or "")
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        sides = [_const_text(node.left), _const_text(node.right)]
        return any(t is not None and SQL.search(t) for t in sides) and None in sides
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        text = _const_text(node.func.value)
        return node.func.attr == "format" and text is not None and bool(SQL.search(text))
    return False


def check_python(source: str, rel: str) -> list[str]:
    """Rule violations in one module (``rel`` is its path relative to src/sidereal)."""
    tree = ast.parse(source)
    lines = source.splitlines()
    found: list[str] = []
    for name, line in _imported(tree):
        for banned, allowed in IMPORT_ALLOW.items():
            if (name == banned or name.startswith(banned + ".")) and rel not in allowed:
                found.append(f"{rel}:{line}: import {name} not allowed here")
        if name.split(".")[0] == "sqlite3" and not rel.startswith(SQL_ALLOWED_PREFIX):
            found.append(f"{rel}:{line}: sqlite3 only in db/")
    docstrings = _docstring_ids(tree)
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        where = f"{rel}:{line}"
        if isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name == "print":
                found.append(f"{where}: print() in src (use logging, or cli.out)")
            if SUBPROCESS_CALLS.match(name) and rel not in SUBPROCESS_ALLOWED:
                found.append(f"{where}: {name}() only in api/routes_runs.py")
            attr = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if attr in DB_CALLS and not rel.startswith(SQL_ALLOWED_PREFIX):
                found.append(f"{where}: .{attr}() outside db/")
        if _formatted_sql(node) and "# sql-ok:" not in lines[line - 1]:
            found.append(f"{where}: SQL built with f-string/%/+/.format (use ? parameters)")
        text = _const_text(node)
        if (
            text is not None
            and id(node) not in docstrings
            and not rel.startswith(SQL_ALLOWED_PREFIX)
            and SQL.search(text)
        ):
            found.append(f"{where}: SQL text outside db/")
    return sorted(set(found))


def _src_modules() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


@pytest.mark.parametrize("path", _src_modules(), ids=lambda p: p.relative_to(SRC).as_posix())
def test_source_module_follows_static_rules(path: Path):
    rel = path.relative_to(SRC).as_posix()
    assert check_python(path.read_text(encoding="utf-8"), rel) == []


def test_frontend_has_no_banned_apis():
    found = []
    for path in sorted(WEB_SRC.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"} or path.name == "schema.d.ts":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FRONTEND_BANNED.search(line):
                found.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    assert found == []


# --- the checks themselves -------------------------------------------------------------------

@pytest.mark.parametrize(
    ("snippet", "rel", "fragment"),
    [
        ("import requests", "x.py", "import requests"),
        ("from urllib import request", "x.py", "import urllib.request"),
        ("import urllib.request", "x.py", "import urllib.request"),
        ("from http.client import HTTPConnection", "x.py", "import http.client"),
        ("import socket", "pipeline/runner.py", "import socket"),
        ("import httpx", "notify/discord.py", "import httpx"),
        ("import aiohttp", "net/fetch.py", "import aiohttp"),
        ("import subprocess", "pipeline/runner.py", "import subprocess"),
        ("import os\nos.system('ls')", "cli.py", "os.system()"),
        ("import asyncio\nasyncio.create_subprocess_exec('x')", "x.py", "create_subprocess"),
        ("import sqlite3", "api/app.py", "sqlite3 only in db/"),
        ("conn.execute(q)", "pipeline/runner.py", ".execute() outside db/"),
        ("Q = 'SELECT id FROM items WHERE x = ?'", "api/routes_days.py", "SQL text outside db/"),
        ("q = f'SELECT * FROM t WHERE id = {i}'", "db/items_repo.py", "f-string"),
        ("q = 'DELETE FROM t WHERE id = %s' % i", "db/items_repo.py", "f-string"),
        ("q = 'UPDATE t SET a = 1 WHERE id = ' + i", "db/items_repo.py", "f-string"),
        ("q = 'INSERT INTO t VALUES ({})'.format(v)", "db/items_repo.py", "f-string"),
        ("print('hi')", "cli.py", "print()"),
    ],
)
def test_checker_flags(snippet: str, rel: str, fragment: str):
    assert any(fragment in v for v in check_python(snippet, rel)), check_python(snippet, rel)


@pytest.mark.parametrize(
    ("snippet", "rel"),
    [
        ("import httpx", "net/fetch.py"),
        ("import socket", "net/guard.py"),
        ("import subprocess\nsubprocess.run(['systemctl'])", "api/routes_runs.py"),
        ("from urllib.parse import urlsplit", "urls.py"),
        ("import sqlite3\nconn.execute('SELECT 1 FROM t WHERE a = ?', (a,))", "db/x_repo.py"),
        ('"""Run SELECT ... FROM items in db/ only."""', "pipeline/runner.py"),
        ("msg = f'Selected {n} stories from the feed'", "pipeline/runner.py"),
        ("q = f'SELECT {col} FROM t'  # sql-ok: col from COLUMNS whitelist", "db/x_repo.py"),
        ("label = 'Update available: set a reminder'", "api/x.py"),
    ],
)
def test_checker_allows(snippet: str, rel: str):
    assert check_python(snippet, rel) == []


def test_frontend_pattern():
    for bad in ("<div dangerouslySetInnerHTML={x} />", "el.innerHTML = s", "eval(code)",
                "new Function('a', b)", "document.write(x)"):
        assert FRONTEND_BANNED.search(bad), bad
    assert not FRONTEND_BANNED.search("const evaluation = evaluate(x)")


def test_built_index_has_no_inline_scripts():
    """CSP is ``script-src 'self'``: the Vite build must not emit inline <script> bodies."""
    index = ROOT / "web" / "dist" / "index.html"
    if not index.exists():
        pytest.skip("web/dist not built")
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", index.read_text(), re.S)
    assert scripts, "no script tags in the built index.html"
    assert all("src=" in attrs and not body.strip() for attrs, body in scripts)

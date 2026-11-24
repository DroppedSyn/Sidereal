# Sidereal: agent notes

Spec: `Sidereal_implementation_plan.md` (authoritative; follow it literally). Owner brief:
`prototype.md`. Decision and run history: `PROJECT_LOG.md`.

## Commands
- Setup (a pi copy has no `.venv/` or `node_modules/`: run these first):
  `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'` and
  `(cd web && ~/.local/node/bin/npm ci)` (needs the network)
- Back-end tests: `.venv/bin/pytest -q` (expect the last line `N passed`, no failures)
- Lint: `.venv/bin/ruff check src tests` (expect `All checks passed!`)
- Static rules only: `.venv/bin/pytest -q tests/test_static_rules.py`
- Front-end tests: `(cd web && ~/.local/node/bin/npm test -- --run)`
- Type check: `(cd web && ~/.local/node/bin/npx tsc --noEmit)` (exit 0, no output)
- Front-end lint: `(cd web && ~/.local/node/bin/npx eslint src)` (no output)
- Regenerate API types: `.venv/bin/sidereal openapi > web/openapi.json && (cd web && ~/.local/node/bin/npm run gen:api)`
- Build the UI: `(cd web && ~/.local/node/bin/npm run build)` → `web/dist`, served by `sidereal serve`
- Init (temp home for experiments): `SIDEREAL_CONFIG=<tmp>/sidereal.toml SIDEREAL_PATHS__STATE_DIR=<tmp>/state .venv/bin/sidereal init`
- Serve: `.venv/bin/sidereal serve [--host 127.0.0.1] [--port 8470] [--reload]`
- Dev UI: `.venv/bin/sidereal serve --reload` + `(cd web && ~/.local/node/bin/npm run dev)` (Vite on 5173 proxies `/api` to 8470)
- Never `source .venv/bin/activate`; call `.venv/bin/...` directly. npm is not on PATH: use `~/.local/node/bin/npm` / `npx`.

## Layout
- `pyproject.toml` — package `sidereal` (src layout), deps, console script `sidereal`, pytest + ruff config
- `config/defaults/sources.toml` — seed sources (plan §6.6), `[[source]]` tables
- `config/defaults/focus.toml` — seed focus areas (plan §5), descriptions go into prompts verbatim (Claude's text)
- `config/sidereal.example.toml` — every setting with its default
- `prompts/` — prompt files (M10, Claude only); `README.md` placeholder now
- `deploy/` — systemd units, install.sh (M22), Caddyfile.example (M30); placeholder README now
- `src/sidereal/__init__.py` — `__version__`
- `src/sidereal/__main__.py` — `python -m sidereal`
- `src/sidereal/cli.py` — argparse: `init`, `serve`, `openapi`; `run` `doctor` `rescore` `reassess` (M13), `eval` (M16), `backup` (M22), `user` (M25) are stubs that exit 2; `out()`/`err()` are the only console output
- `src/sidereal/config.py` — `Settings` (pydantic) from TOML + `SIDEREAL_<SECTION>__<KEY>` env, `load_settings()`, `ConfigError`
- `src/sidereal/paths.py` — XDG config/state dirs, `config_file()`, project folders (`defaults_dir`, `prompts_dir`, `web_dist_dir`)
- `src/sidereal/defaults.py` — load + validate the seed TOMLs (`SourceSeed`, `FocusSeed`)
- `src/sidereal/bootstrap.py` — `init()`, `migrate()`, `ensure_dirs()` (used by `init`, `serve`, later `run`)
- `src/sidereal/db/connect.py` — `connect()` with the §4 pragmas, `ping()` (read-only, never creates)
- `src/sidereal/db/migrations.py` — `apply_migrations()`, one transaction per file, `split_statements()`
- `src/sidereal/db/sql/0001_init.sql` — the §4 schema; later `0002_feedback` (M24), `0003_search` (M26), `0004_auth` (M25), `0005_notify` (M28), `0006_weekly` (M29)
- `src/sidereal/db/seed.py` — insert-only seeding of `sources` / `focus_areas`
- `src/sidereal/db/sources_repo.py`, `runs_repo.py` (M6a), `items_repo.py`, `stories_repo.py` (M6b), `digests_repo.py` (M12), `feedback_repo.py` (M24), `users_repo.py` (M25), `search_repo.py` (M26)
- `src/sidereal/timeutil.py`, `urls.py` (M1); `textclean.py` (M2, Claude); `models.py` (when first needed)
- `src/sidereal/net/guard.py` (M3, Claude), `net/fetch.py` (M3)
- `src/sidereal/sources/base.py`, `rss.py`, `msrc.py` (M4); `cisa_kev.py`, `hn_algolia.py` (M5); `websearch.py` (interface only)
- `src/sidereal/pipeline/dedupe.py`, `prefilter.py` (M7); `scoring.py` (M11a); `enrich.py` (M12a); `lock.py`, `runner.py` (M13)
- `src/sidereal/llm/ollama.py` (M8), `gate.py` (M9), `prompts.py`, `triage.py` (M10), `assess.py` (M11b), `digest.py` (M12b)
- `src/sidereal/api/app.py` — `create_app(settings, dist_dir=None)`: wires routers + middleware, no logic
- `src/sidereal/api/security.py` — write guard (`X-Sidereal: 1` + allowed Origin/Referer), CSP + security headers, `no-store` on `/api`
- `src/sidereal/api/bind.py` — `check_bind()`: rule 9 refusal (non-loopback needs auth on + a user)
- `src/sidereal/api/static.py` — `web/dist` serving, SPA fallback, "UI not built" page (503)
- `src/sidereal/api/routes_health.py` — `GET /api/health`
- `src/sidereal/api/asgi.py` — module-level `app` for `serve --reload`
- `src/sidereal/api/schemas.py`, `deps.py`, `routes_gazette.py`, `routes_days.py` (M15a), `routes_stories.py`, `routes_runs.py`, `routes_sources.py` (M15b), `routes_feedback.py` (M24), `routes_auth.py` (M25), `routes_search.py` (M26), `routes_settings.py` (M27)
- `src/sidereal/auth/` (M25, Claude), `notify/` (M28), `evals/` (M16)
- `tests/conftest.py` — autouse `isolated_env` (tmp HOME/XDG, clears `SIDEREAL_*`) and `no_network`; fixtures `config_file`, `settings`, `db`
- `tests/fake_ollama.py` — `FakeOllama`: MockTransport handler, scripted `/api/chat` replies, records requests (full version M8)
- `tests/factories.py` — demo data builder (M15)
- `tests/fixtures/feeds/`, `tests/fixtures/pages/` — recorded samples, see `tests/fixtures/README.md`
- `tests/test_static_rules.py` — AST rules over `src/`, banned front-end APIs, no inline scripts in `web/dist`
- `tests/test_<module>.py` — one per module (`test_config`, `test_migrations`, `test_bootstrap`, `test_app`, `test_cli`, `test_fixtures`, `test_fake_ollama`)
- `web/package.json` — exact versions, scripts `dev`, `build`, `test`, `lint`, `typecheck`, `gen:api`
- `web/vite.config.ts` — dev proxy, build (no inline scripts), vitest (jsdom, `tests/setup.ts`)
- `web/eslint.config.js` — flat config, `react/no-danger: error`
- `web/tsconfig.json` — strict
- `web/openapi.json` — generated by `sidereal openapi`; `web/src/api/schema.d.ts` generated from it (never edit)
- `web/src/main.tsx` — providers (React Query, Router); `web/src/App.tsx` — shell placeholder; `web/src/styles/base.css`
- `web/src/routes.tsx`, `api/client.ts`, `api/hooks.ts` (M17); `components/` (M18, M19); `pages/` (M18-M20, M24-M29); `lib/` (M18)
- `web/tests/` — vitest `*.test.tsx`, `setup.ts`; `web/e2e/` (M20, Playwright)

## Rules (plan §1, condensed; the plan wins on any doubt)
1. The model never decides placement: `scoring.py` computes score and bucket from validated rubric numbers. Invalid model output → one retry → `assess_failed` (shown in "On the side").
2. Untrusted text is data: feed/article content becomes plain text at ingest; the front end never uses `dangerouslySetInnerHTML`, `innerHTML`, `eval` or a Markdown renderer on stored content; links only from `items.url`, `http`/`https` only.
3. Outbound HTTP only in `net/fetch.py` (internet) and `llm/ollama.py` (Ollama), via `httpx`. No `requests`, `urllib.request`, `http.client`, `aiohttp`, `urllib3` anywhere in `src/`; `socket` only in `net/`.
4. Every internet fetch: timeouts, size cap, User-Agent `Sidereal/<version> (+personal news reader)`, URL guard on every hop, conditional GET for feeds.
5. SQL only in `src/sidereal/db/`, `?` parameters only, never f-string/`%`/`.format`/`+` with values.
6. Times stored as UTC ISO 8601 ending `Z`; the day key is computed once at first sight in `schedule.tz`.
7. Tests never touch the network or a real Ollama (the autouse `no_network` fixture enforces it). Use fixtures, `httpx.MockTransport`, `tests/fake_ollama.py`.
8. No secrets in the repo, DB, logs or API responses; no default credentials.
9. The web app refuses a non-loopback bind unless auth is on and a user exists (`api/bind.py`).
10. Runs never overlap (`fcntl.flock` on `$STATE/run.lock`).
11. Logging via stdlib `logging` to stderr; no article text or prompts at INFO. No `print()` in `src/` (CLI output goes through `cli.out`/`cli.err`).
12. `subprocess` only in `api/routes_runs.py` (fixed argv, no shell).
13. Module size: Python modules ≤ ~300 lines, React component files ≤ ~200 lines (a soft target; don't spend a run trimming).
14. One test file per module; new tests go in new test files.

## Build method
Milestones are delegated to pi via pi-bridge and reviewed by Claude (`/implement`). Implementors: follow the brief exactly, run the given checks, report results verbatim. New tests go in new test files. Use the project's `.venv` only (never `source activate`); in a pi copy create it first with the setup commands. If a check fails because of a file you were told not to touch, stop and report it with the failing test name; do not work around it.

## Decisions
- M0: Python pins (`pyproject.toml`): `fastapi>=0.115,<1`, `uvicorn[standard]>=0.30,<1`, `httpx>=0.27,<1`, `pydantic>=2.7,<3`, `feedparser>=6.0.11,<7`, `trafilatura>=1.12,<3`, `argon2-cffi>=23,<26`; dev `pytest>=8,<10`, `pytest-asyncio>=0.23,<2`, `ruff>=0.6,<1`. Installed 2026-11-24: fastapi 0.165.0, uvicorn 0.54.0, httpx 0.28.1, pydantic 2.14.4, feedparser 6.0.14, trafilatura 2.4.0 (lxml 6.1.3), argon2-cffi 25.1.0, pytest 9.2.0, pytest-asyncio 1.5.0, ruff 0.17.6. trafilatura and argon2-cffi install cleanly on aarch64.
- M0: Front-end pins (exact, `web/.npmrc` `save-exact=true`, lock committed), chosen on the plan's majors and at least a month old: react/react-dom 18.3.1, react-router-dom 6.30.6, @tanstack/react-query 5.104.5, vite 5.4.21, @vitejs/plugin-react 4.7.0, typescript 5.9.3, vitest 2.1.9, jsdom 25.0.1, @testing-library/react 16.3.3, /dom 10.4.2, /user-event 14.6.8, /jest-dom 6.9.1 (6.10.0 is deprecated), eslint + @eslint/js 9.39.5, typescript-eslint 8.72.0, eslint-plugin-react 7.37.5, eslint-plugin-react-hooks 5.2.0, globals 15.15.0, openapi-typescript 7.13.0, @types/react 18.3.31, @types/react-dom 18.3.7.
- M0: Settings are plain pydantic models (no `pydantic-settings` dependency); `config.py` merges TOML and env itself. Env values parse as JSON when possible (lists, numbers, booleans), else strings. Unknown sections/keys are a `ConfigError` (exit 2).
- M0: Path overrides: `SIDEREAL_CONFIG` = settings file path; state dir = `[paths] state_dir` / `SIDEREAL_PATHS__STATE_DIR`, default `$XDG_DATA_HOME/sidereal`. Tests get both via the autouse `isolated_env` fixture (tmp HOME and XDG dirs) and `config_file`.
- M0: Config sections beyond plan §12.2: `[ingest]` (`max_age_hours` 96, `backfill_hours` 72, `dedupe_window_hours` 72, plan §6.3/§6.7), `[triage]` (`keep_min` 2, §7.3), `[paths]`. `[scoring]` spells every §8 number as a key (`w_relevance` … `recency_floor`). `[notify]` holds non-secret SMTP fields and `channels`.
- M0: Seed TOMLs, prompts and `web/dist` are found relative to the source checkout (`paths.project_root()`), which works because the app runs from an editable install in `~/Projects/Sidereal` (the systemd units point there).
- M0: Seeds: `options.article_hosts` is set per source now (enrichment allowlist, §6.2); empty for MSRC, KEV and HN (no enrichment). `tc-azure-architecture` has `options.max_bytes = 4000000`. MSRC's product regex default stays in code (M4), not in the seed.
- M0: Host allowlist in tests: the `config_file` fixture writes `allowed_hosts = ["127.0.0.1", "localhost", "testserver"]`; the default stays loopback-only (`test_default_allowed_hosts_exclude_testserver`).
- M0: Write guard: a POST/PUT/PATCH/DELETE needs `X-Sidereal: 1` and an `Origin` (else `Referer`) whose host is in `web.allowed_hosts` with port `web.port`, or listed exactly in `web.allowed_origins`. Writes from the Vite dev server need `SIDEREAL_WEB__ALLOWED_ORIGINS='["http://localhost:5173"]'` (the proxy keeps the browser's Origin; we don't rewrite it). Refusal is 403 JSON; a bad Host is 400 (Starlette's TrustedHostMiddleware, outermost).
- M0: Static serving, the SPA fallback, CSP/security headers and `no-store` on `/api` are already in M0 (`api/static.py`, `api/security.py`); M21 adds asset cache headers, `tests/test_static_serving.py` and the Playwright check. The "UI not built" page is 503 text/plain. OpenAPI lives at `/api/openapi.json`; Swagger/ReDoc pages are off.
- M0: `sidereal serve` checks rule 9 with `user_count=0` until M25 adds users, so any non-loopback bind is refused now. A hostname that isn't `localhost` counts as non-loopback.
- M0: Unimplemented CLI commands exist as stubs that print `not implemented yet (Mxx)` to stderr and exit 2 (unknown options are tolerated for them only).
- M0: Print policy: no `print()` anywhere in `src/` (static rule); CLI output uses `cli.out()`/`cli.err()` (sys.stdout/stderr).
- M0: Static rules: AST-based; `socket` is allowed in `net/fetch.py` and `net/guard.py` (guard needs `socket` constants/errors), `httpx` only in `net/fetch.py` and `llm/ollama.py`, `sqlite3` and `.execute*()` only in `db/`, SQL-looking string literals (docstrings excepted) only in `db/`. A line building SQL from a whitelisted identifier may carry `# sql-ok: <reason>`; only use it when a brief allows it.
- M0: Extra modules not in plan §3: `defaults.py`, `bootstrap.py`, `db/seed.py`, `api/security.py`, `api/bind.py`, `api/static.py`, `api/routes_health.py`, `api/asgi.py` (keeps `app.py` and `cli.py` thin).
- M0: Tests import helpers as `tests.fake_ollama` (`tests/__init__.py` exists). pytest-asyncio runs in `auto` mode, so `async def test_…` needs no marker. Starlette's "use httpx2" TestClient deprecation warning is filtered in `pyproject.toml`.
- M0: Migrations are split with `sqlite3.complete_statement` (trigger bodies and `;` in literals stay whole) and run between explicit `BEGIN`/`COMMIT` with `isolation_level=None`; a file must end each statement with `;`.
- M0: Fixtures recorded 2026-11-24 (see `tests/fixtures/README.md`). Krebs now answers `application/rss+xml`; `test_html_page_is_broken_not_empty` (M4) uses `msrc-blog-html.html`.
- M2 (Claude): `textclean.to_text(s)` HTML or plain text → plain text (drops script/style/iframe/noscript/svg/template/head/title/object/math/select/textarea, comments, CDATA, PIs; blocks → `\n\n`, `<br>` → `\n`, `<li>` → `\n• `; entities decoded exactly once via `HTMLParser(convert_charrefs=False)`; a raw tag-like `<` left in text becomes `‹`; control chars → space, zero-width/bidi/BOM/soft hyphen removed, NFC). Input without a tag-like `<` is plain text: line breaks kept, `html.unescape` once. `clean_title(s, max_len=300)` one line; `truncate(text, max_chars)` word boundary + `…`, `len <= max_chars`; `excerpt(html, max_chars=1500)`. Never raises; 2 MB in about 1 s (test limit 2 s). Decoded entity text like `&lt;x&gt;` → `<x>` is data, rendered as text.
- M3a (Claude): `net/guard.py`: `UrlGuard(*, resolver=None, allowed_ports=(80, 443), allow_private=False)`; `await guard.check(url, *, allow_hosts=None) -> CheckedUrl(url, host, port, addresses)` or raises `UrlBlocked` (`.reason`, safe to log; also raised for DNS failure / no addresses). `resolver` is `async (host, port) -> Sequence[str]` (default `default_resolver`, loop `getaddrinfo`); tests pass a fake. `allow_hosts=[]` allows nothing (sources with empty `article_hosts` get no enrichment). **M3b: the fetcher must call `guard.check` on the first URL and on every redirect `Location` (resolved against the current URL) before requesting it**, passing the same `allow_hosts`; the plan's `test_redirect_to_private_blocked` lives in `test_guard.py` at guard level, so `test_fetch.py` needs its own test that a 302 to `http://127.0.0.1/` raises `UrlBlocked` without requesting it. `UrlBlocked` is not retried.

## Status
- [x] M0 scaffolding, fixtures, seeds, app skeleton (Claude, 2026-11-24)
- [ ] M1 `timeutil.py`, `urls.py`
- [x] M2 `textclean.py` (Claude, 2026-11-24; tests by Claude, not pi: security module)
- [ ] M3 `net/guard.py` (Claude) + `net/fetch.py` (pi) — M3a guard.py done (Claude)
- [ ] M4 `sources/base.py`, `rss.py`, `msrc.py`
- [ ] M5 `cisa_kev.py`, `hn_algolia.py`
- [ ] M6 repos (M6a sources + runs, M6b items + stories)
- [ ] M7 `dedupe.py`, `prefilter.py`
- [ ] M8 `llm/ollama.py` + full `fake_ollama.py`
- [ ] M9 `llm/gate.py`
- [ ] M10 prompts (Claude) + `llm/prompts.py`, `llm/triage.py`
- [ ] M11 M11a `scoring.py`, M11b `assess.py`
- [ ] M12 M12a `enrich.py`, M12b `digest.py` + `digests_repo`
- [ ] M13 `lock.py`, `runner.py`, CLI `run`/`rescore`/`doctor`
- [ ] M14 first real run (Claude)
- [ ] M15 API (M15a gazette + days, M15b the rest) + `tests/factories.py`
- [ ] M16 golden set + `sidereal eval` (Claude + owner)
- [ ] M17 app shell, router, tabs, API client
- [ ] M18 StoryCard, BucketSection, SourceBadges, GazettePage, safeHref
- [ ] M19 DayList, DailyPage, mobile layout
- [ ] M20 RunsPage, SourcesPage (M20a), Playwright E2E + CSP check (M20b)
- [ ] M21 static serving finish (asset cache headers, tests; most of it landed in M0)
- [ ] M22 deploy units, backup, retention, doctor (Claude) — v1
- [ ] M23 soak: 3 days unattended (Claude + owner)
- [ ] M24 feedback (M24a back end, M24b UI)
- [ ] M25 auth (Claude)
- [ ] M26 search (FTS5)
- [ ] M27 settings UI (M27a API, M27b UI)
- [ ] M28 notifications: email + Discord webhook
- [ ] M29 weekly digest
- [ ] M30 LAN deployment (Claude)

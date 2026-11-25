# Sidereal: decisions and status log

`AGENTS.md` keeps commands, layout, rules, current Decisions and the milestone checklist. This file
keeps the history: every milestone's record (who, run ids, fixes, mutation checks, real-model
results) and decisions as they were made. Claude appends; implementors don't need to read it unless
a brief says so.

## Decisions
- 2026-11-24 (M0): see `AGENTS.md` `## Decisions` (M0 entries): pins, config overrides, write
  guard and host allowlist in tests, print policy, static-rule scope, extra modules.

## Status
- 2026-11-24 **M0** (Claude, no pi run). Scaffolding per plan §16: package skeleton, config,
  paths, DB connect/migrations/0001 schema, seeding, `init`/`serve`/`openapi`, API skeleton
  (health, TrustedHost, write guard, CSP, SPA serving, "UI not built"), rule-9 bind check, static
  rules, fake Ollama skeleton, Vite/React/TS scaffold, 23 feed fixtures + 2 page fixtures.
  Mutation checks: removing TrustedHostMiddleware turns `test_unknown_host_rejected` and
  `test_default_allowed_hosts_exclude_testserver` red; a `dangerouslySetInnerHTML` file makes
  `eslint src` fail on `react/no-danger`; static-rule checker self-tests cover each rule both
  ways.
- 2026-11-24 **M2 + M3a** (Claude, no pi run; security modules, so Claude also wrote the tests
  instead of pi). `textclean.py` (+ `tests/test_textclean.py`, 39 tests incl.
  `test_entities_decoded_once`, an XSS corpus, real fixture bodies, 2 MB timing) and
  `net/guard.py` (+ `tests/test_guard.py`, 59 tests incl. the four §6.2 named SSRF tests, fake
  resolver only). Mutation checks, each turned tests red and was restored: second `html.unescape`
  on the output (`test_entities_decoded_once`); `convert_charrefs=True` (2 red); no raw-`<`
  neutralising (2 XSS corpus cases); checking only the first resolved address
  (`test_any_bad_address_blocks`); no embedded-IPv4 unwrap (2 red, via the reason text: Python
  3.13's `ipaddress` already treats `::ffff:127.0.0.1` as loopback, the unwrap is for 3.12 and
  NAT64/6to4/compat forms); no numeric-host check (10 red); subdomain match without the dot
  (`test_allow_hosts`).
- 2026-11-25 **M1** (pi run r48, `qwen3.6:35b-a3b-coding`, 9m16s, 15 tool calls / 3 failed:
  first verify run 3 failures fixed by pi, then the full suite and ruff failed on M2 files that
  were stale in pi's copy, not on its own; 234k tokens in / 9.0k out). Files: `timeutil.py` 103
  lines, `urls.py` 113, `tests/test_timeutil.py` 267 (22 tests), `tests/test_urls.py` 204
  (19 tests). Outcome: landed; pi followed the brief closely (tests verbatim). Review fixes:
  `TRACKING_PARAMS` made public as briefed, `_split` return annotation, `to_utc` simplified;
  `entry_published` falls through to the next key when a value is >1 day in the future (pi's
  reading of "treated as missing", kept and pinned by
  `test_entry_future_published_falls_back_to_updated`); added `//` root-path and bare-host
  idempotence cases. Mutation checks (each red): day_key in UTC, `utm_*` kept, case-sensitive
  `wt.mc_id`, `drop_future` disabled / `>=`, `.get` instead of `key in entry` (the warning
  test), fragment kept, no query sort, subdomain match without the dot, no port validation,
  default ports kept; the root-path `or "/"` mutation survived until the added test. Full suite
  279 passed, ruff clean.
- 2026-11-25 **M3b** (pi run r49, `qwen3.6:35b-a3b-coding`, 48m20s of a 50 min limit, 25 tool
  calls / 1 failed, 2 stall resumes, 199k tokens in / 56.9k out, largest reply 16.4k near the
  cap). pi wrote both files in one go, ran the fetch tests once (3 failed: no backoff sleep on
  5xx, redirect test calling `get` twice) and stopped there. Files as landed:
  `net/fetch.py` 223 lines, `tests/test_fetch.py` 597 (35 tests). Outcome: landed after review
  rewrote the `Fetcher` body (security-relevant): `per_host_concurrency` was ignored, the 429
  allowance lived on `self` (once per Fetcher, not per call), the host slot was held during
  backoff, non-2xx bodies were read, read timeouts escaped as raw httpx errors; dead code
  removed. 13 tests added (see Status). Mutation checks, all red: guard / `allow_hosts` only on
  the first hop, `follow_redirects=True`, no stream cap, no Content-Length cap, `>=` cap,
  Retry-After uncapped, UrlBlocked / FetchTooLarge / ReadTimeout retried, redirect limit off by
  one, semaphore hard-coded or held while sleeping, second 429 honoured, no backoff sleep, no
  UA, raw Location. Full suite 315 passed, ruff clean.
- 2026-11-25 **M6a** (pi run r50, `qwen3.6:35b-a3b-coding`, 21m24s, 35 tool calls / 6 failed:
  3 test runs fixed by pi (unknown-source test, precedence test twice), 1 edit mismatch, 2 ruff
  runs (unused import, unused local; fixed with `--fix --unsafe-fixes`); 1022k tokens in / 18.1k
  out). pi's copy predated M3b (306 tests there). Files as landed: `db/sources_repo.py` 151
  lines, `db/runs_repo.py` 130, `tests/test_sources_repo.py` 220 (19 tests),
  `tests/test_runs_repo.py` 170 (11 tests). Outcome: landed; signatures and SQL as briefed, all
  fixed strings with `?`. Review fixes: no write committed (the brief's `with conn:` rule ignored
  everywhere) → wrapped, plus `test_writes_commit` in both files; pi's health-test helper dropped
  unknown kwargs and the seeded `created_at` was real now (after T0), so the `created_at` stale
  fallback was untested → health tests rebuilt with `created_at` 30 d before T0 and a recent
  `last_new_item_at` by default, `created_at` 6d23h/7d boundary added; tests added for None
  overwriting validators and an error keeping ok state; `record_fetch_ok` three near-identical
  UPDATEs → one with `CASE`, `record_broken` delegates to `record_fetch_error`. Mutation checks
  (30, all red): thresholds off by one / `>` (3, 6, 7 d, both stale paths), `created_at`
  fallback always applied, broken without failures, failing/empty swapped, 304 resetting or
  counting, >0 not resetting, failures not reset, `enabled_only` ignored, broken prefix lost,
  `recover_stale` touching non-running rows, `list_runs` ASC or `<=`, bad/`running` status
  accepted, `last_ok_run` without partial or ASC, stats dropped, trigger unchecked, unknown run
  silent, writes without `with conn:`. Full suite 347 passed, ruff clean.
- 2026-11-25 **M4** (pi run r51, `qwen3.6:35b-a3b-coding`, 38m30s, 25 tool calls / 2 failed
  (a test run with 2 failures, a probe script using `read_bytes` on a file object); 377k tokens
  in / 60.7k out, one 16.4k reply near the output cap, resumed after stalling 2×). pi wrote all
  eight files in one pass, ran the tests once, probed feedparser and stopped mid-investigation
  with 2 tests failing and 38 ruff errors. Files as landed: `sources/base.py` 104 lines,
  `rss.py` 149, `msrc.py` 66, `__init__.py` 8, `tests/adapter_helpers.py` 54,
  `tests/test_sources_base.py` 129 (10 tests), `tests/test_rss.py` 366 (51), `tests/test_msrc.py`
  131 (11). Outcome: landed; review rewrote the three modules (same API) and fixed the tests:
  `pytest.raises(Exception)` everywhere instead of `SourceBroken`, `test_age_cap` never passed
  `max_age_hours` and left three unused fetches, the undated-keeps test had no cap, excerpt
  content-first against the brief. MSRC order changed to filter first, then cap (orchestrator
  request; plan §6.3 updated). 13 tests added. Mutation checks (45, all red; title `.strip()`
  equivalent). Full suite 423 passed, ruff clean.
- 2026-11-25 **M8** (pi run r52, `qwen3.6:35b-a3b-coding`, builtin edit tools, 38m00s, 12 tool
  calls / 0 failed, 181k tokens in / 52.3k out, 1 file changed, resumed after stalling 2×).
  pi read the context files, then replied with 16,384 tokens of thinking and no tool call
  (stopReason `length`) twice. After the second resume it wrote an extended `tests/fake_ollama.py`
  (248 lines, all briefed features except `created_at` in chat replies), announced "I'll write
  all four files now" and hit the cap a third time. Both resumes were used up, so the run ended
  `done` with 1 of 4 files. Outcome: pi's diff discarded; Claude wrote all four files from the brief:
  `tests/fake_ollama.py` 125 lines, `src/sidereal/llm/__init__.py`, `src/sidereal/llm/ollama.py`
  190, `tests/test_ollama.py` 278 (31 tests: the 22 briefed plus edge cases: stats from the
  successful reply, missing `message`, no reply text in LLMOutputInvalid, HTTP error on the retry,
  non-JSON 200, per-request timeout on a passed client, errored requests recorded). Mutation
  checks (17, all red; "per-request timeout" survived the briefed tests and got its own test).
  Cause: over-thinking at the output cap (pi-bridge failure table r13/r52). A brief of this size
  (4 files, 22 tests) needs a `:low` thinking model or a split (fake + tests, then module).
  Full suite 455 passed, ruff clean.
- 2026-11-25 **M6b** (pi run r53, `qwen3.6:35b-a3b-coding`, builtin edit tools, **timeout at
  50m00s**, 30 tool calls / 5 failed (two test runs with failures, one edit `oldText` miss, two
  whole-file test rewrites not executed because the reply hit the output token limit); 592k
  tokens in / 52.9k out, largest reply 12.7k). pi wrote all six files by step 19 (modules 154 /
  256 / 98 lines, tests 391 / 473 / 196), first run 22 failures, rewrote the test files, second
  run 6 failures, then timed out while re-reading its modules. Cause: its stories tests
  contradicted the brief (assumed `insert_item` also attaches the item and sets lead /
  `last_seen_at`; rebound `st` to a `StoryRow` and passed it as an id), and 1568 lines of
  inline-repeated calls made every fix a whole-file rewrite near the output cap (new row in the
  pi-bridge failure table). Outcome: pi's diff applied as base; modules kept and tidied:
  `recent_stories` returned dicts instead of `RecentStory`, `delete_dropped_before` built SQL
  with `+` (the static rule misses a Name operand), `pending_stories` → one `LIMIT ?` query,
  items row construction deduplicated, `attach_item` simplified. All three test files rewritten
  to the brief with helpers (31 → 37 tests). Files as landed: `items_repo.py` 118 lines,
  `stories_repo.py` 237, `assessments_repo.py` 98, tests 182 / 275 / 94. Mutation checks (30,
  all red): duplicate via `lastrowid`, prune `<=`, NULL-guid exists, attach resetting lead,
  `last_seen_at` backwards, CVE merge duplicating, pending order / tie / limit, delete at cutoff /
  `new` / `side`, recent and since exclusive, title_norm order, triage 4, reason not cleared,
  rubric -1, novelty unchecked, upsert keeping `created_at`, each of the 10 `with conn:` removed.
  Full suite 495 passed, ruff clean.
- 2026-11-25 **M5** (pi run r54, `qwen3.6:35b-a3b-coding`, builtin edit tools, done in **42m43s**,
  37 tool calls / 1 failed (a ruff E501 it then fixed by hand); 831k tokens in / 28.6k out,
  largest reply 16.4k (near the output cap), resumed once after stalling). pi followed the brief
  closely: both modules match it line for line, 27 tests green, full suite 452, ruff clean.
  Review: `test_invalid_options` dropped the briefed `match=` on all six `raises(ValueError)`
  (a min_points check raising the queries message passed; restored), the two URL asserts compared
  `httpx.URL` to a str instead of `str(...)` (restored), `hit_item`'s `if ...: pass / else` int
  fallbacks → `_int_or_zero`. Added `test_first_query_wins_on_duplicate_object_id`: the briefed
  dedupe test serves one fixture for every query, so last-wins survived. Files as landed:
  `cisa_kev.py` 125 lines, `hn_algolia.py` 134, `test_cisa_kev.py` 193 (14 tests),
  `test_hn_algolia.py` 219 (14 tests). Mutation checks (22, all red after the fixes): KEV age cap
  off, dateAdded at 23:59 / −1 s, guid without `kev:`, SourceBroken → `[]` (4 sites), empty-cveID
  guard off, etag not sent, HN dedupe off / last-wins, non-http url accepted, story url dropped,
  min_points hard-coded, age cap off, window ignoring `max_age_hours`, bool min_points accepted,
  min_points message, only the first query fetched. Full suite 547 passed, ruff clean.
- 2026-11-25 **M7a** (pi run r55, `qwen3.6:35b-a3b-coding`, builtin edit tools, done in **43m01s**,
  6 tool calls / 1 failed, 2 stall resumes, largest reply 16.4k tokens (near the cap), 146k in /
  56.6k out). pi wrote tests, module and `__init__.py` in one write each, ran the tests once
  (2 failed: a crashing leftover loop in the roll-up test, a tie-break test on a 3-token title that
  can never title-match) and stopped there; ruff had 25 errors. pi's module (271 lines) renamed
  `Assignment.item_key` → `key`, numbered the roll-up group on a separate counter (collides with
  ordinary group 0), took the first CVE story in `known` order (not lowest id) and the first title
  ≥ 0.6 (not the best score). Review: module rewritten (174 lines, one `_match` for known stories
  and batch groups), tests rewritten to the brief and extended (389 lines, 38 tests; pi's
  `test_deterministic` used 3-token titles, so nothing it checked could match). Mutation checks
  (28, all red after adding a short-item-title test and a group-growth test whose 4th/5th items
  match only via a joined item's title/CVE). Full suite 587 passed, ruff clean.
- 2026-11-25 **M7b** (pi run r56, `qwen3.6:35b-a3b-coding`, builtin edit tools, done in **29m28s**,
  29 tool calls / 4 failed (an import error, a test-module construction error, 4 red tests, one
  ruff F401; all fixed by pi), 1 stall resume, 871k tokens in / 30.8k out, largest reply 16.4k
  (near the cap)). pi delivered a module that matched the brief (165 lines) and 39 green tests;
  full suite and ruff clean in its copy. Patch conflicted only on the already-existing empty
  `pipeline/__init__.py` (applied without it). Review: removed a dead `if ...: pass` mute block
  and a redundant helper, `FocusArea.keywords` made required as briefed, duplicate keywords
  counted once, shared `_age_hours`; pi's "dropped decision carries hint" test used a muted
  keyword instead of the briefed muted source. Added 22 tests (boundaries, all adjacent
  precedence pairs, kev case, empty sources, published over first_seen, future band, tie-break by
  first_seen, max_age passthrough). Files as landed: `prefilter.py` 155 lines, `test_prefilter.py`
  481 (61 tests); `focus.toml` header comment updated (it still said "substring matches").
  Mutation checks (27, all red after the additions; 4↔5 and 5↔6 precedence swaps and the empty-
  sources guard survived pi's tests). Seed keywords over fixture titles behave as intended;
  false positives found: `entra`→"Entrance", `sentinel`→"SentinelOne", `azure ad`→"Azure
  Advisor" (all primary → always-kept), and primary `cve-`/`exploited` always-keep every CVE or
  "exploited" title from any source. Left for the user. Full suite 649 passed, ruff clean.
- 2026-11-25 **M9** (pi run r57, `qwen3.6:35b-a3b-coding`, builtin edit tools, done in **21m30s**,
  47 tool calls / 9 failed (7 malformed `todo` calls, one red test run on an un-awaited
  `busy_reason`, one ruff UP037; all fixed by pi), 914k tokens in / 10.9k out, largest reply 3.6k).
  pi's `gate.py` (130 lines) and the `ollama.py` hunk (`ProbeResult`, `probe`, `_request(timeout=)`)
  matched the brief; `test_ollama.py` unchanged and green; patch applied cleanly. Review fixes: the
  probe-error warning logged `type(LLMError).__name__` (the metaclass name) instead of the caught
  exception's type; `tests/test_gate.py` rewritten onto `tmp_path` (pi hand-rolled temp dirs inside
  `tests/` with try/finally rmtree) and extended 18 → 28 tests (every state word incl. `timeout`,
  load excluded both sides, configurable threshold, slow-then-fast probe, timeout with probe always
  slow, log contents, `from_settings` asserts all four settings and drives a wait). Files as
  landed: `gate.py` 130, `ollama.py` 211, `test_gate.py` 255 (28 tests), `test_ollama_probe.py` 87
  (6). Mutation checks (19, all red; dropping the `is_dir()` guard is equivalent). Full suite 684
  passed, ruff clean.

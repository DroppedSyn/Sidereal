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
- 2026-11-25 **M11a** (pi run r58, `qwen3.6:35b-a3b-coding:low`, builtin edit tools, done in
  **33m42s**, 15 tool calls / 1 failed (`python3 -c "from sidereal.config ..."` before the venv
  existed), 225k tokens in / 50.0k out, largest reply 16.4k, 2 stall resumes). **0 files changed.**
  Cause: after seven short turns (reading `config.py`, `pipeline/__init__.py`, two test files,
  creating the venv), its next three replies were pure thinking cut at the 16384-token output cap
  (stopReason `length`, 42k/50k/54k chars of thinking, no tool call); both resumes were used up, so
  pi exited `done` without writing either file, although the run was already `:low` and the brief
  was only 2 files (the r52 failure mode, now on a 2-file brief with 23 parametrized tests and
  computed values). Claude wrote `pipeline/scoring.py` (152 lines) and `tests/test_scoring.py`
  from the brief: the 23 briefed tests plus every remaining config field shown to be used, a 24.5 h
  recency case and input-not-mutated, 62 cases. Mutation checks (21, all red after adding the
  24.5 h case, which killed "recency end shifted"). Full suite 747 passed, ruff clean.
- 2026-11-25 **M10a** (pi run r59, `qwen3.6:35b-a3b-coding`, builtin edit tools, **timeout** at
  50 min of run time (1h25m wall), 45 tool calls / 5 failed, 920k tokens in / 88.4k out, largest
  reply 16.4k, 2 stall resumes, 3 context compactions (one overflow), re-reading the four prompt
  files after each). pi wrote both files, but the module ignored much of the function-by-function
  brief (non-frozen dataclasses, positional `version`/`root`, no `prompts_root`, `-` allowed in
  names, `wrap_untrusted` neutralising before truncating with a default cap, no one-lining, article
  excerpt default 300 and content uncapped, `DigestLine.date`), and it had changed briefed test
  expectations (`Excerpt: E  x`) to fit its output. Not applied: Claude rewrote
  `llm/prompts.py` (187 lines) to the brief and `tests/test_prompts.py` (364 lines, 42 functions /
  57 cases: the 26 briefed plus caps, one-lining, neutralising per helper, env/root precedence,
  traversal). Mutation checks (41, all red after adding the sorted missing-key message and the
  301-char triage cap tests; neutralise-before-truncate is equivalent). Note for mutation runs:
  same-length edits (`300`→`301`, `extra`→`False`) survived at first through stale `__pycache__`
  (pyc check is mtime-seconds + size); run mutants with `PYTHONDONTWRITEBYTECODE=1`. Full suite 805
  passed, ruff clean.
- 2026-11-25 **M12a** (pi run r60, `qwen3.6:35b-a3b-coding`, builtin edit tools, done in
  **42m55s**, 52 tool calls / 7 failed (a `todo` call without `action`, reading the not-yet-written
  test file, two scratch scripts that forgot to await `Fetcher.get`, ruff I001/F821 before its own
  fix), 1556k tokens in / 17.4k out, largest reply 3.5k: no thinking-cap stalls). pi wrote both
  files to the function-by-function brief and its 18 tests passed. Review found one real bug: a
  server-sent `charset=idna` or `charset=undefined` passes `codecs.lookup` but raises
  `UnicodeError` even with `errors="replace"`, so a hostile page could crash `extract_text`
  (and with it `enrich_many`'s `gather`); `_decode` now falls back to utf-8 on any decode error.
  Tidied (`ERROR_MAX_CHARS`, redundant except, unused logger), garbage test parametrized; tests
  18 → 42 functions/cases. Mutation checks (27, all red: allowlist, `allow_hosts` on every hop,
  error mapping and cap, media type, 2 MB / 20000 caps and truncation, `to_text`, charset,
  concurrency, deadline, worker thread, case). trafilatura's urllib3 SOCKS DependencyWarning is
  filtered in `pyproject.toml`. Full suite 848 passed, ruff clean.
- 2026-11-25 **M11b** (pi run r61, `qwen3.6:35b-a3b-coding:off`, i.e. **thinking off**, builtin
  edit tools, done in **13m33s**, 14 tool calls / 1 failed (ruff F841 on an unused `r`), 279k
  tokens in / 5.9k out, largest reply 4.2k). The experiment: the `:low` runs either stalled on
  16k-token pure-thinking replies (r52, r58: no output) or took 43-50 min (r59, r60). With thinking
  off pi read the three referenced files, wrote the test file, then the module, each in one go, and
  went green on the first test run. The brief spelled out the module almost line by line, so this
  measures transcription and test-writing, not design; the review found no bug in pi's code, only
  spec gaps in the brief: `exploited_in_wild` lax bool (took `"true"`/`1`) → `StrictBool`;
  `strip_urls` case-sensitive (`HTTPS://` survived) → `re.IGNORECASE`; unknown-focus log value cut
  to 40 chars. Test fixes: pi's F841 fix deleted test 12's result check instead of asserting it;
  test 14 lacked the briefed 1-call assert. Tests 24 → 33 functions (41 cases). Mutation checks
  (30, all red), see AGENTS.md M11. `assess.strip_urls` is the canonical URL stripper; r64's
  `digest.py` copy should import it in review. Full suite 890 passed, ruff clean.
- 2026-11-25 **M10b** (pi run r62, `qwen3.6:35b-a3b-coding:off`, builtin edit tools, done in
  **1h22m** after 47 min in the queue, 40 tool calls / 10 failed (one edit miss, eight red test
  runs, a `ruff check src/tests` typo), 1187k tokens in / 60.3k out, two 16384-token replies, two
  stall resumes). Thinking off did not stop thinking: the model still streamed thinking blocks
  (180k chars over the run, 2.3k in r61) and twice spiralled to the output cap (~13 min each, plus
  ~10 min each for stall detection and compaction). Trigger: its first module missed the
  `LLMOutputInvalid` import and got `unfinished` wrong; briefed test 15 (an id missing in pass one
  whose re-queue the deadline skips stays `unfinished`) then looked contradictory to it, so it
  argued with itself, switched to an `attempted` set that made such ids `defaulted` (relevance 1,
  dropped for good) and rewrote test 15 to match, the r59 pattern. `:off` is fast while the brief
  transcribes cleanly (r61), but a red test it cannot explain still produces runaway reasoning.
  Review: `run_batches` rewritten to the brief (one `one_pass` helper for both passes), test 15
  restored, tests 19 → 27 functions (34 cases), 35 mutations all red (one survivor, "only the
  current skipped batch marked unfinished", killed by a 3-batch deadline test). Full suite 925
  passed, ruff clean.
- 2026-11-25 **M12b-1** (pi run r63, `qwen3.6:35b-a3b-coding:off`, builtin edit tools, done in
  **12m02s**, 11 tool calls / 0 failed, 238k tokens in / 3.9k out, largest reply 2.1k). Schema
  change first (Claude): `day_digests` gains `headline` and `story_ids_json` in `0001_init.sql`
  and plan §4 (no database exists yet). pi read the sibling repo and its tests, wrote the test
  file and the module in one go each and went green on the first run; both match the near-verbatim
  brief, the review found no bug. One mutation survived (the `before` query ignoring `limit`: the
  briefed before+limit case only had one row under limit 5), killed by the added
  `test_list_before_respects_limit`. 22 mutations all red. Full suite 949 passed, ruff clean.
- 2026-11-25 **M12b-2** (pi run r64, `qwen3.6:35b-a3b-coding:off`, builtin edit tools, done in
  **26m05s**, 9 tool calls / 0 failed, 240k tokens in / 20.2k out). After reading three files pi
  produced one 16384-token pure-thinking reply (56k chars, stopReason `length`) before any write,
  although the brief spelled out the module and every test; after one stall resume it wrote the
  test file and the module in one go each and went green on the first run. So `:off` does not
  prevent the pre-write planning runaway either (r61 had none, r62's came after red tests). Both
  files match the brief verbatim, no bug in pi's code. Review: the module's own case-sensitive URL
  regex copy (as briefed, pending assess) replaced by an import of the canonical
  `assess.strip_urls` (`HTTPS://` survived the copy); 3 tests added (helper identity, upper-case
  URLs in both fields, URL-only overview → `""`); tests 26 → 29 cases. 19 mutations all red, see
  AGENTS.md M12. M12 done (M12a r60, M12b-1 r63, M12b-2 r64). Full suite 979 passed, ruff clean.
- 2026-11-25 **M13a** (pi run r65, `qwen3.6:35b-a3b-coding:off`, builtin edit tools, done in
  **5m37s**, 22 tool calls / 4 failed (a malformed todo call, one red test run, two ruff runs),
  557k tokens in / 7.4k out, largest reply 3.7k, no stalls). pi wrote the test file and the
  module in one go each; both match the near-verbatim brief, no behavioural bug. Review: the
  nested try in `acquire` (with an unreachable `except BlockingIOError: raise`) flattened,
  `is_held` unlocks after a successful probe as briefed; child holders moved into a
  `start_holder` fixture with a 10 s `select` readiness check and kill + reap at teardown (two
  tests had no cleanup), stray unreleased locks in tests 5/14 released, and
  `test_is_held_leaves_no_fd_or_lock` added (a probe leaking its locked fd survived). 23
  mutations all red (two by timeout: `LOCK_NB` dropped, `held_by` taking a blocking lock). Full
  suite: 1007 passed, 3 failed only in the in-progress M13b files (static rules on
  `pipeline/common.py`, `ingest.py`, `placement.py`); `test_lock.py` 27 passed ×3; ruff clean on
  M13a files (E501 only in M13b files).
- 2026-11-25 **M13b** (Claude, not delegated: broad coordinator work). The runner is six
  modules: `pipeline/common.py` (Deadline, StoryBundle, short_error), `ingest.py` (fetch all
  sources with per-source error isolation, source health, normalisation, `item_exists` filter,
  dedupe, story/item storage with the MSRC roll-up title and KEV flags), `placement.py` (score
  and bucket from stored rubric numbers only; `rescore`, `refresh` for joined stories),
  `assess_step.py` (prefilter → triage slice → enrich → assess, backlog carried without
  re-triage), `digest_step.py` (rewrite a day's digest only when its placed TOP/Relevant set
  changed) and `runner.py` (`run_once`, `make_gate`, `dry_run`; partial/failed status, deadline
  started after the gate, unload after LLM use). New: `db/focus_repo.py`, `stories_repo.merge_flags`
  / `scored_stories`, `sidereal.db.Connection` for annotations outside `db/`. 67 tests in 8 new
  files incl. an end-to-end run over all 21 seed fixtures with a schema-routing fake Ollama;
  36 mutations all red (3 survivors of the first pass killed by added tests: triage deadline,
  gate before the deadline, re-placing joined stories). Full suite 1081 passed, ruff clean.
  Owner notes: `zero_item_runs` counts items after the age cap (adapters return no raw entry
  count), so a source quiet for 96 h turns `empty` after 6 runs; no source sets `flags.cvss`.
- 2026-11-25 **M13c** (Claude, not delegated). CLI `run` / `rescore` / `doctor` in a new
  `commands.py` (cli.py keeps the parser) and a read-only `doctor.py`. `run` migrates, takes the
  run lock (a held lock records a `skipped` run and exits 0), builds the Fetcher and Ollama
  client and closes both in `finally`; unknown `--source` exits 2 without a run row; only a
  `failed` run exits 1. `--dry-run` takes no lock and never builds an Ollama client. `rescore`
  takes the lock too (held → exit 1). `doctor` checks config, env file mode, state dir and
  free space, lock, schema version (over a `mode=ro` connection; never creates the DB), last
  run, source health, Ollama + models (`/api/tags` only); systemd checks wait for M22
  (subprocess is allowed only in `routes_runs.py`). `reassess` stays a stub ("unscheduled": no
  milestone row builds it). Fixed the owner note from M13b: adapters now report the feed's own
  entry count (`FetchResult.entry_count`) and ingest stores it, so `empty` means an empty feed,
  not a quiet one. trafilatura's urllib3 SOCKS warning no longer prints on every CLI start.
  39 tests in 4 new files; 27 mutations all red (one survivor killed by an added test: rss
  counting kept items instead of entries). Full suite 1122 passed, ruff clean. Smoke in a temp
  home: doctor before init exits 1 and creates nothing, after init exits 0 (real Ollama
  reachable, `/api/tags` only); a real-network `run --dry-run` took 4 s: 20 sources ok, 98
  items, 95 new stories; **`sans-isc` failed as broken**: `https://isc.sans.edu/rssfeed_full.xml`
  now answers an HTML page (31 KB) labelled `text/xml`, also to curl; the source needs a new URL.
- 2026-11-25 **M22** (Claude, not delegated). Deploy: five systemd user units in `deploy/`
  (web on 127.0.0.1:8470, oneshot run + timer at 00/04/08/12/16/20 Europe/London with
  `Persistent=true`, nightly backup service + 03:30 timer), hardened with `NoNewPrivileges`,
  `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome=read-only` + `ReadWritePaths` for the state
  dir, `RestrictAddressFamilies`; all verified working in a transient `systemd-run --user` unit
  and `systemd-analyze --user verify` clean. Run timeout raised to 3 h (gate 90 min + budget
  45 min exceeded the plan's 2 h). `deploy/install.sh` is idempotent, runs `sidereal init`,
  installs, `daemon-reload`, `enable --now`, never sudo, prints the linger command when off;
  `bash -n` clean, shellcheck not available. `sidereal backup` (online backup API, quick_check,
  atomic rename, keep newest 14, `sidereal-YYYYMMDD-HHMM.db` UTC). Retention runs at the end of
  every run (`[retention]` 30 / 90 days). `doctor` now checks web service, both timers (last and
  next trigger) and linger from files only, so rule 12 stays as it is. 5 new test files (42
  tests, incl. `install.sh` against fake systemctl/loginctl); 29 mutations all red. Not
  installed: the owner runs `deploy/install.sh` and `sudo loginctl enable-linger al`.
- 2026-11-25 **M15a-2** (pi r67, timed out at 50 min; Claude finish). `tests/factories.py`
  demo-data builder over the repos and `tests/test_factories.py`. pi (thinking `:off`, builtin
  edit tools) spent 41 of 56 tool calls reading the repos and their tests (most twice), then
  wrote its own design instead of the brief's literal code (other function names, clock
  2026-11-20, 10 stories, no `seed_demo`/`--seed-demo`) and ran out of time on ruff import
  order. Both files rewritten to the brief. One deviation: the assessment `raw` now mirrors what
  `assess_step` stores (the whole assess reply plus `focus`, `exploited_in_wild` from the
  story's `exploited` flag) instead of `{"focus": ...}` only, so placement and `views_repo`
  read demo rows as real ones. `--seed-demo` writes 16 runs / 30 stories / 40 items / 2
  digests and refuses an existing file. 24 tests (21 briefed + 3 added for survivors: a run
  exactly at `now`, the failed/partial run positions, ids growing with time); 21 mutations
  all red, one equivalent. Full suite 1191 passed, ruff clean.
- 2026-11-25 **M15a-1** (pi r68, timed out at 50 min; Claude finish). `db/views_repo.py`
  (read-only Gazette/Daily queries: `gazette_views`, `day_views`, `day_summaries`,
  `runs_between`) and `tests/test_views_repo.py`. pi (thinking `:off`, builtin edit tools) wrote
  both files to the brief within 15 tool calls, then spent the rest of the run on one red test
  (`test_hidden_states_excluded`): its `_views` built every story from the loop variable `row`
  left over from the grouping loop (the last row of the whole result), so bucket, raw, flags and
  title leaked across stories. It debugged with hand-written schemas and inline SQL scripts
  (12 failed calls) and never looked at its own loop. Fix: `_story_view(rows)` per story group.
  Second fix: `_COUNTS + " FROM ..."` tripped the static `+` rule (a name plus an SQL-looking
  literal); tails are now their own constants. Local-day/DST bounds are not this module's (the
  stored `day` column and caller-supplied run bounds; `day_bounds` is M15a-5). Tests: the 26
  briefed + row isolation across two stories, a `seed_demo` round trip, and a trace-callback
  check that no executed SQL mentions `content`. 18 mutations all red. Full suite 1220 passed,
  ruff clean.

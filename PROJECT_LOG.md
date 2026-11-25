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

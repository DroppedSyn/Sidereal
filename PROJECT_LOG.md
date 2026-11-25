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

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

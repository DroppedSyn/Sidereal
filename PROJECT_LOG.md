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

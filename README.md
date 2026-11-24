# Sidereal

A personal intelligence feed. Every 4 hours it collects news from curated sources (Azure and
Microsoft feeds, MSRC, CISA, security press, Hacker News), has a local Ollama model judge what
matters to a cloud network architect with security duties, and publishes the result as a web
"gazette": **TOP / Relevant / On the side** for the last 24 hours, plus a per-day archive.

Status: early build (milestone M0, scaffolding). The full design is in
`Sidereal_implementation_plan.md`; progress is tracked in `AGENTS.md`.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
(cd web && ~/.local/node/bin/npm ci)
.venv/bin/sidereal init          # creates ~/.local/share/sidereal/sidereal.db and seeds it
```

Settings: copy `config/sidereal.example.toml` to `~/.config/sidereal/sidereal.toml` (optional;
every key has a default). Environment overrides use `SIDEREAL_<SECTION>__<KEY>`.

## Run

```sh
(cd web && ~/.local/node/bin/npm run build)   # UI → web/dist, served by the API
.venv/bin/sidereal serve                      # http://127.0.0.1:8470
```

From another machine, tunnel instead of exposing the port:
`ssh -L 8470:127.0.0.1:8470 al@<vm>`. The app refuses to bind a non-loopback address until
authentication exists (M25).

## Test

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests
(cd web && ~/.local/node/bin/npm test -- --run && ~/.local/node/bin/npx tsc --noEmit && ~/.local/node/bin/npx eslint src)
```

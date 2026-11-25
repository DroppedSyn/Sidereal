#!/usr/bin/env bash
# E2E smoke (M20b/M21): serve the built UI from a temp demo DB on port 8472 and run smoke.mjs
# (headless Firefox over WebDriver BiDi). Needs `npm run build` first and /usr/bin/firefox.
# Usage (from the repo root): web/e2e/run-smoke.sh   Env: SMOKE_PORT (8472), FIREFOX, BIDI_PORT.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
port="${SMOKE_PORT:-8472}"
node="${NODE:-$HOME/.local/node/bin/node}"
[ -f "$root/web/dist/index.html" ] || { echo "web/dist not built: run npm run build in web/" >&2; exit 2; }
tmp="$(mktemp -d)"
server=""
cleanup() {
  if [ -n "$server" ]; then kill "$server" 2>/dev/null || true; wait "$server" 2>/dev/null || true; fi
  rm -rf "$tmp"
}
trap cleanup EXIT
export SIDEREAL_CONFIG="$tmp/sidereal.toml" SIDEREAL_PATHS__STATE_DIR="$tmp/state"
cd "$root"
.venv/bin/sidereal init >/dev/null
.venv/bin/python - <<'PY'
from sidereal.config import load_settings
from sidereal.db.connect import connect
from sidereal.timeutil import utc_now
from tests.factories import seed_demo

conn = connect(load_settings().db_path)
seed_demo(conn, now=utc_now())
conn.close()
PY
.venv/bin/sidereal serve --host 127.0.0.1 --port "$port" >"$tmp/serve.log" 2>&1 &
server=$!
for _ in $(seq 50); do
  curl -fsS "http://127.0.0.1:$port/api/health" >/dev/null 2>&1 && break
  sleep 0.2
done
"$node" web/e2e/smoke.mjs "http://127.0.0.1:$port/"

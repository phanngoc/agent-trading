#!/usr/bin/env bash
# Smoke-test all dashboard endpoints. Starts the dev server if it isn't
# already listening on PORT, hits each route, and reports red/green.
#
# Exit non-zero on any failure so CI / make targets can gate on it.
#
# Usage:
#   ./scripts/smoke.sh                     # uses PORT=3210
#   PORT=3000 ./scripts/smoke.sh           # custom port
#   KEEP_SERVER=1 ./scripts/smoke.sh       # leave dev server running after
set -euo pipefail

PORT="${PORT:-3210}"
HOST="http://localhost:$PORT"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASHBOARD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEV_LOG="$(mktemp -t dashboard-smoke.XXXX.log)"

cd "$DASHBOARD_DIR"

cleanup() {
  if [[ -z "${KEEP_SERVER:-}" && -n "${DEV_PID:-}" ]]; then
    kill -9 "$DEV_PID" 2>/dev/null || true
    pkill -P "$DEV_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Start dev server if nothing is listening.
if ! curl -fs -o /dev/null --max-time 2 "$HOST/" 2>/dev/null; then
  echo "▶ starting dev server on $PORT (log: $DEV_LOG)"
  PORT="$PORT" node_modules/.bin/next dev -p "$PORT" > "$DEV_LOG" 2>&1 &
  DEV_PID=$!
  for i in {1..40}; do
    sleep 0.5
    if curl -fs -o /dev/null --max-time 2 "$HOST/" 2>/dev/null; then
      echo "▶ dev server ready (pid=$DEV_PID, ${i}× wait)"
      break
    fi
    if (( i == 40 )); then
      echo "✗ dev server failed to come up — log tail:"
      tail -30 "$DEV_LOG"
      exit 1
    fi
  done
fi

fail=0

check_page() {
  local path="$1"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$HOST$path")
  if [[ "$code" == "200" ]]; then
    printf "  \033[32m✓\033[0m %-30s %s\n" "$path" "$code"
  else
    printf "  \033[31m✗\033[0m %-30s %s\n" "$path" "$code"
    fail=1
  fi
}

check_json() {
  local path="$1"
  local probe="$2"  # jq path that must be non-null
  local body
  body=$(curl -s --max-time 120 "$HOST$path")
  if [[ -z "$body" ]]; then
    printf "  \033[31m✗\033[0m %-30s empty response\n" "$path"
    fail=1
    return
  fi
  if echo "$body" | python3 -c "import json, sys; d=json.load(sys.stdin); v=d; [v:=v[k] for k in $probe]; assert v is not None" 2>/dev/null; then
    printf "  \033[32m✓\033[0m %-30s %s\n" "$path" "$probe ok"
  else
    printf "  \033[31m✗\033[0m %-30s %s\n" "$path" "missing $probe"
    echo "    body preview: $(echo "$body" | head -c 200)"
    fail=1
  fi
}

echo "── pages ──"
check_page /
check_page /markets
check_page /vnindex
check_page /agent
check_page /settings

echo
echo "── API ──"
check_json /api/markets/vnindex          '["history", 0, "c"]'
check_json /api/markets/quotes           '["quotes", 0, "symbol"]'
check_json /api/agent/runs               '["runs"]'

if [[ "$fail" == "0" ]]; then
  echo
  echo -e "\033[32m✓ all checks passed\033[0m"
  exit 0
fi

echo
echo -e "\033[31m✗ some checks failed\033[0m"
exit 1

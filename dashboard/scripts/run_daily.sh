#!/usr/bin/env bash
# Daily trade-agent run for a configurable VN ticker watchlist.
#
# Designed to be scheduled via cron / launchd / systemd-timer. Writes results
# to eval_results/<TICKER>/TradingAgentsStrategy_logs/ which the dashboard's
# /api/agent/runs route serves.
#
# Auth: relies on the user's existing Claude Code OAuth keychain entry
# (see tradingagents/llm_clients/anthropic_client.py). No API key is plumbed
# through this script.
#
# Usage:
#   TICKERS="VIC.VN HPG.VN MWG.VN" ./scripts/run_daily.sh
#   ./scripts/run_daily.sh                # uses default watchlist

set -euo pipefail

# Resolve repo root from this script's location (works regardless of cwd).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PY="${TRADINGAGENTS_PYTHON:-$REPO_ROOT/venv/bin/python}"

# Default watchlist — override via TICKERS env var.
TICKERS="${TICKERS:-VIC.VN HPG.VN MWG.VN VCB.VN}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
PROVIDER="${PROVIDER:-anthropic}"
DEEP_MODEL="${DEEP_MODEL:-claude-haiku-4-5}"
QUICK_MODEL="${QUICK_MODEL:-claude-haiku-4-5}"
ANALYSTS="${ANALYSTS:-market,news}"

LOG_DIR="$REPO_ROOT/eval_results/_daily_runs"
mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/$(date +%Y%m%d-%H%M%S).log"

echo "[run_daily] $(date -u +%FT%TZ) starting watchlist run" | tee "$RUN_LOG"
echo "[run_daily] tickers=$TICKERS date=$DATE provider=$PROVIDER" | tee -a "$RUN_LOG"

cd "$REPO_ROOT"
for TICKER in $TICKERS; do
  echo "[run_daily] === $TICKER ===" | tee -a "$RUN_LOG"
  "$PY" main.py \
    --ticker "$TICKER" \
    --date "$DATE" \
    --provider "$PROVIDER" \
    --deep-model "$DEEP_MODEL" \
    --quick-model "$QUICK_MODEL" \
    --analysts "$ANALYSTS" \
    >> "$RUN_LOG" 2>&1 || echo "[run_daily] ❌ $TICKER failed (continuing)" | tee -a "$RUN_LOG"
done

echo "[run_daily] $(date -u +%FT%TZ) done, log: $RUN_LOG" | tee -a "$RUN_LOG"

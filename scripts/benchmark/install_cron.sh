#!/usr/bin/env bash
# Install / remove the daily benchmark cron entry on the local machine.
#
# Usage:
#   scripts/benchmark/install_cron.sh           # install (idempotent)
#   scripts/benchmark/install_cron.sh --remove  # remove
#   scripts/benchmark/install_cron.sh --status  # show what's registered
#
# The cron runs Mon-Fri at 17:00 ICT (10:00 UTC) — after HOSE close
# (15:00 ICT) with a 2-hour buffer so vnstock has time to serve final
# session closes. Output goes to ``benchmarks/daily/_cron.log`` with
# timestamped wrappers so a long log stays useful.
#
# The script edits the user's crontab via ``crontab -l | ... | crontab -``;
# nothing else writes to crontab, so the marker line below is the only
# thing it greps for when de-duplicating.

set -euo pipefail

# Resolve repo root from this script's location so the cron entry has
# absolute paths regardless of $PWD when invoked.
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." &> /dev/null && pwd)"
PY="${REPO_ROOT}/venv/bin/python"
LOG_DIR="${REPO_ROOT}/benchmarks/daily"
LOG_FILE="${LOG_DIR}/_cron.log"
MARKER="# tradingagents-daily-benchmark"   # de-dupe sentinel

# 10:00 UTC = 17:00 ICT (UTC+7). Mon-Fri (1-5 in cron, 0 = Sun).
# Wraps the command in a bash subshell so we can:
#   - timestamp each invocation
#   - cd into the repo root before running
#   - capture both stdout + stderr to the log
CRON_LINE="0 10 * * 1-5 cd \"${REPO_ROOT}\" && (echo \"=== \$(date -u +%FT%TZ) start ===\"; \"${PY}\" -m scripts.benchmark.run_daily; echo \"=== \$(date -u +%FT%TZ) end ===\") >> \"${LOG_FILE}\" 2>&1 ${MARKER}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--install|--remove|--status]

  --install   (default) Idempotently add the daily cron entry.
  --remove    Remove our marker line from crontab.
  --status    Print the current marker line (or note its absence).
EOF
}

mode="${1:---install}"

case "$mode" in
    --status|-s|status)
        if crontab -l 2>/dev/null | grep -F "$MARKER" >/dev/null; then
            crontab -l | grep -F "$MARKER"
        else
            echo "(no cron entry installed)"
        fi
        ;;

    --remove|-r|remove)
        if crontab -l 2>/dev/null | grep -F "$MARKER" >/dev/null; then
            crontab -l 2>/dev/null | grep -vF "$MARKER" | crontab -
            echo "Removed cron entry."
        else
            echo "Nothing to remove."
        fi
        ;;

    --install|-i|install|"")
        mkdir -p "$LOG_DIR"
        # Pull existing crontab, drop any previous marker line, append fresh.
        # `|| true` covers the "no existing crontab" exit code.
        ( crontab -l 2>/dev/null | grep -vF "$MARKER" || true; echo "$CRON_LINE" ) | crontab -
        echo "Installed cron entry:"
        echo "  $CRON_LINE"
        echo
        echo "Logs: $LOG_FILE"
        echo "Test now (without cron):"
        echo "  $PY -m scripts.benchmark.run_daily --skip-agent --date \$(date +%F)"
        ;;

    -h|--help|help)
        usage
        ;;

    *)
        usage
        exit 1
        ;;
esac

#!/usr/bin/env bash
# Install / remove the daily benchmark LaunchAgent on macOS.
#
# launchd is macOS's native scheduler and is significantly more reliable
# than cron for this use case: cron on macOS requires Full Disk Access
# entitlement to read most paths and silently drops scheduled jobs after
# the system sleeps. launchd handles sleep/wake transparently and is the
# Apple-supported way to schedule recurring background work on macOS.
#
# Schedule: 17:00 local time, Mon-Fri. The previous cron entry used
# ``0 10 * * 1-5`` interpreted by cron in *local* time, which on an
# ICT (+07) machine fires at 10:00 ICT — not 17:00 as the install
# comment claimed. launchd fixes that by using ``Hour=17`` against
# local TZ. (If your machine isn't on ICT and you want the agent to
# run at ICT 17:00, adjust ``Hour`` to the local equivalent.)
#
# Usage:
#   scripts/benchmark/install_launchd.sh                 # install (idempotent)
#   scripts/benchmark/install_launchd.sh --remove        # unload + delete plist
#   scripts/benchmark/install_launchd.sh --status        # show load state
#   scripts/benchmark/install_launchd.sh --run-now       # fire one-off
#
# State that gets written:
#   ~/Library/LaunchAgents/com.tradingagents.daily-benchmark.plist
#   benchmarks/daily/_launchd.log  (stdout)
#   benchmarks/daily/_launchd.err  (stderr)

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." &> /dev/null && pwd)"
PY="${REPO_ROOT}/venv/bin/python"
LABEL="com.tradingagents.daily-benchmark"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${REPO_ROOT}/benchmarks/daily"
STDOUT_LOG="${LOG_DIR}/_launchd.log"
STDERR_LOG="${LOG_DIR}/_launchd.err"

# Render the plist. We declare one ``dict`` per weekday inside
# StartCalendarInterval — launchd treats the array as "fire whenever the
# system clock matches any element", so we get Mon-Fri at 17:00 with no
# day-of-week wildcard support needed.
render_plist() {
    cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PY}</string>
        <string>-m</string>
        <string>scripts.benchmark.run_daily</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>17</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>${STDOUT_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${STDERR_LOG}</string>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLIST
}

# launchd's bootstrap/bootout API replaced load/unload in macOS 10.10+,
# but ``launchctl load -w`` still works on every supported version.
# We keep using ``load/unload`` for compatibility back to Catalina.
is_loaded() {
    launchctl list 2>/dev/null | awk '{print $3}' | grep -Fxq "$LABEL"
}

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
}

mode="${1:---install}"

case "$mode" in
    --status|-s|status)
        echo "Plist: $PLIST"
        if [[ ! -f "$PLIST" ]]; then
            echo "(plist not installed)"
            exit 0
        fi
        if is_loaded; then
            echo "loaded — next fire is the soonest StartCalendarInterval match"
            launchctl list "$LABEL" 2>/dev/null | head -20
        else
            echo "(plist exists but not loaded — run --install to load)"
        fi
        ;;

    --remove|-r|remove)
        if is_loaded; then
            launchctl unload -w "$PLIST" 2>/dev/null || true
            echo "Unloaded $LABEL."
        fi
        if [[ -f "$PLIST" ]]; then
            rm -f "$PLIST"
            echo "Removed $PLIST."
        else
            echo "Nothing to remove."
        fi
        ;;

    --run-now)
        if ! is_loaded; then
            echo "Not loaded. Run --install first."
            exit 1
        fi
        launchctl start "$LABEL"
        echo "Started $LABEL (one-off). Tail logs: tail -f \"$STDOUT_LOG\""
        ;;

    --install|-i|install|"")
        mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"
        # Unload first so a re-install replaces cleanly without leaking
        # the old in-memory plist.
        if is_loaded; then
            launchctl unload -w "$PLIST" 2>/dev/null || true
        fi
        render_plist > "$PLIST"
        launchctl load -w "$PLIST"
        echo "Installed:"
        echo "  Plist:   $PLIST"
        echo "  Stdout:  $STDOUT_LOG"
        echo "  Stderr:  $STDERR_LOG"
        echo "  Schedule: Mon-Fri 17:00 (local time)"
        echo
        echo "Test now without waiting for the schedule:"
        echo "  $0 --run-now"
        ;;

    -h|--help|help)
        usage
        ;;

    *)
        echo "Unknown mode: $mode" >&2
        usage
        exit 1
        ;;
esac

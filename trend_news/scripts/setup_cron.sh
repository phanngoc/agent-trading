#!/bin/bash
# Setup cron jobs for TrendRadar
# Usage: bash scripts/setup_cron.sh

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$PROJECT_DIR/venv/bin/python3"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "=== TrendRadar Cron Setup ==="
echo "Project: $PROJECT_DIR"
echo "Python:  $PYTHON"
echo ""

# Check env vars
MISSING=""
[ -z "$GROQ_API_KEY" ]         && MISSING="$MISSING GROQ_API_KEY"
[ -z "$TELEGRAM_BOT_TOKEN" ]   && MISSING="$MISSING TELEGRAM_BOT_TOKEN"
[ -z "$TELEGRAM_CHAT_ID" ]     && MISSING="$MISSING TELEGRAM_CHAT_ID"
if [ -n "$MISSING" ]; then
    echo "⚠️  Missing env vars (set in ~/.zshrc or .env):$MISSING"
    echo "   Morning brief will still run but Telegram delivery will be skipped."
fi

# Build cron entries
CRON_ENV="GROQ_API_KEY=${GROQ_API_KEY} TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN} TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID} PYTHONPATH=${PROJECT_DIR}"

MORNING_BRIEF="0 6 * * 1-5 $CRON_ENV $PYTHON $PROJECT_DIR/morning_brief.py >> $LOG_DIR/morning_brief.log 2>&1"
FULL_PIPELINE="0 7 * * 1-5 $CRON_ENV $PYTHON $PROJECT_DIR/pipeline.py >> $LOG_DIR/pipeline.log 2>&1"
WEEKEND_BRIEF="0 8 * * 6,0 $CRON_ENV $PYTHON $PROJECT_DIR/morning_brief.py --skip-fetch >> $LOG_DIR/morning_brief.log 2>&1"

echo "Cron entries to add:"
echo ""
echo "# TrendRadar — Morning brief (weekdays 6:00 AM)"
echo "$MORNING_BRIEF"
echo ""
echo "# TrendRadar — Full pipeline (weekdays 7:00 AM)"
echo "$FULL_PIPELINE"
echo ""
echo "# TrendRadar — Weekend brief (Sat/Sun 8:00 AM)"
echo "$WEEKEND_BRIEF"
echo ""

read -p "Add these to crontab? [y/N] " confirm
if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
    (crontab -l 2>/dev/null; echo "# TrendRadar"; echo "$MORNING_BRIEF"; echo "$FULL_PIPELINE"; echo "$WEEKEND_BRIEF") | crontab -
    echo "✅ Cron jobs installed. Run: crontab -l to verify"
else
    echo "ℹ️  Skipped. Copy the entries above to add manually."
fi

echo ""
echo "=== Manual test ==="
echo "Morning brief (skip fetch): $PYTHON $PROJECT_DIR/morning_brief.py --skip-fetch"
echo "Full pipeline:              $PYTHON $PROJECT_DIR/pipeline.py"
echo "Dashboard:                  streamlit run $PROJECT_DIR/intelligence_dashboard.py"
echo "API server:                 uvicorn server:app --host 0.0.0.0 --port 8000 --reload"

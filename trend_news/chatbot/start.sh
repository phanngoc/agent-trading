#!/usr/bin/env bash
# ============================================================
# Vietnamese Financial News Chatbot — startup script
#
# Usage:
#   bash trend_news/chatbot/start.sh
#
# Required env vars (at least one):
#   GEMINI_API_KEY  — from https://aistudio.google.com (free tier)
#   GROQ_API_KEY    — from https://console.groq.com   (free fallback)
#
# Optional:
#   LLM_PROVIDER    — "google" (default) | "groq"
#   CHAINLIT_PORT   — default 8001
# ============================================================

set -e

# SCRIPT_DIR = trend_news/chatbot/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# TREND_NEWS_DIR = trend_news/  (needed for src.core.* imports)
TREND_NEWS_DIR="$(dirname "$SCRIPT_DIR")"
# AGENTS_ROOT = TradingAgents/  (project root)
AGENTS_ROOT="$(dirname "$TREND_NEWS_DIR")"

echo "=== Vietnamese Financial News Chatbot ==="
echo "  Chatbot dir : $SCRIPT_DIR"
echo "  trend_news  : $TREND_NEWS_DIR"

# --- Load .env files (project root → trend_news/ → chatbot/ = highest priority) ---
_load_env() {
    local f="$1"
    if [[ -f "$f" ]]; then
        echo "Loading .env: $f"
        set -o allexport
        source <(grep -v '^\s*#' "$f" | sed 's/^export //')
        set +o allexport
    fi
}
_load_env "$AGENTS_ROOT/.env"
_load_env "$TREND_NEWS_DIR/.env"
_load_env "$SCRIPT_DIR/.env"

# --- Env checks ---
if [[ -z "$OPENAI_API_KEY" && -z "$GEMINI_API_KEY" && -z "$GROQ_API_KEY" ]]; then
    echo "ERROR: Set at least one of: OPENAI_API_KEY, GEMINI_API_KEY, GROQ_API_KEY"
    exit 1
fi

# Default to openai when key is present and LLM_PROVIDER not set
if [[ -z "$LLM_PROVIDER" ]]; then
    if [[ -n "$OPENAI_API_KEY" ]]; then
        export LLM_PROVIDER=openai
    elif [[ -n "$GEMINI_API_KEY" ]]; then
        export LLM_PROVIDER=google
    else
        export LLM_PROVIDER=groq
    fi
fi
echo "  LLM provider : $LLM_PROVIDER"

# --- Install / upgrade chatbot package (skip if already installed or offline) ---
echo ""
echo "Installing chatbot package dependencies..."
pip install -q -e "$SCRIPT_DIR" --no-build-isolation 2>/dev/null || \
    echo "  (pip install skipped — already installed or offline)"

# --- PYTHONPATH: trend_news/ must be on path so both of the following work:
#       from chatbot.agent import ...       (chatbot/ lives inside trend_news/)
#       from src.core.ticker_mapper import  (src/ lives inside trend_news/)
# ---
export PYTHONPATH="$TREND_NEWS_DIR:${PYTHONPATH:-}"

# NOTE: The indexer daemon is NOT started here to avoid SQLite lock contention
# with cognee's internal DB. Run the indexer separately before starting the chatbot:
#   python -m chatbot.indexer              # incremental sync
#   python -m chatbot.indexer --full-reindex  # full reset and re-index

# --- Start Chainlit UI ---
PORT=${CHAINLIT_PORT:-8001}
echo ""
echo "Chatbot UI → http://localhost:$PORT"
echo "Press Ctrl+C to stop."
echo ""

# cd to chatbot dir so Chainlit picks up .chainlit/ config automatically
cd "$SCRIPT_DIR"
chainlit run app.py \
    --host 0.0.0.0 \
    --port "$PORT"


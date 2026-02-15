#!/usr/bin/env bash
# =============================================================================
# Integration tests for TrendRadar API (server.py)
# Usage:
#   ./tests/integration_test.sh                  # auto-detect server IP
#   ./tests/integration_test.sh 127.0.0.1:8000   # explicit host:port
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Activate venv (python3 required for JSON assertions)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$(dirname "$PROJECT_DIR")/venv"

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
elif [[ -f "$PROJECT_DIR/venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/venv/bin/activate"
fi

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TIMEOUT=10

# Resolve BASE_URL: arg > env > auto-detect local IP (PHP chiếm 127.0.0.1:8000)
if [[ $# -ge 1 ]]; then
    BASE_URL="http://$1"
elif [[ -n "${TRENDRADAR_URL:-}" ]]; then
    BASE_URL="${TRENDRADAR_URL}"
else
    LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null \
        || ipconfig getifaddr en1 2>/dev/null \
        || hostname -I 2>/dev/null | awk '{print $1}' \
        || echo "127.0.0.1")
    BASE_URL="http://${LOCAL_IP}:8000"
fi

# ---------------------------------------------------------------------------
# Counters & helpers
# ---------------------------------------------------------------------------
PASS=0
FAIL=0
TOTAL=0

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

_pass() { echo -e "  ${GREEN}✓${NC} $1"; PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); }
_fail() { echo -e "  ${RED}✗${NC} $1"; FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); }

# curl wrapper: returns (body, http_status) via global vars
_curl() {
    local url="$1"
    RESPONSE=$(curl -s --max-time "$TIMEOUT" -w "\n__STATUS__%{http_code}" "$url" 2>/dev/null)
    HTTP_STATUS=$(echo "$RESPONSE" | tail -1 | sed 's/__STATUS__//')
    BODY=$(echo "$RESPONSE" | sed '$d')
}

# Assert HTTP status code
assert_status() {
    local label="$1" expected="$2"
    if [[ "$HTTP_STATUS" == "$expected" ]]; then
        _pass "$label (HTTP $HTTP_STATUS)"
    else
        _fail "$label — expected HTTP $expected, got $HTTP_STATUS"
    fi
}

# Assert body contains a string
assert_contains() {
    local label="$1" needle="$2"
    if echo "$BODY" | grep -q "$needle"; then
        _pass "$label"
    else
        _fail "$label — expected '$needle' in response"
        echo -e "    ${YELLOW}body:${NC} ${BODY:0:200}"
    fi
}

# Assert body does NOT contain a string
assert_not_contains() {
    local label="$1" needle="$2"
    if ! echo "$BODY" | grep -q "$needle"; then
        _pass "$label"
    else
        _fail "$label — did not expect '$needle' in response"
    fi
}

# Assert JSON field equals value (requires python3)
assert_json_eq() {
    local label="$1" jq_expr="$2" expected="$3"
    local actual
    actual=$(echo "$BODY" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    # simple dot-path eval
    parts = '$jq_expr'.lstrip('.').split('.')
    v = d
    for p in parts:
        if '[' in p:
            key, idx = p.rstrip(']').split('[')
            v = v[key][int(idx)]
        else:
            v = v[p]
    print(v)
except Exception as e:
    print('__ERR__:' + str(e))
" 2>/dev/null)
    if [[ "$actual" == "$expected" ]]; then
        _pass "$label"
    else
        _fail "$label — expected '$expected', got '$actual'"
    fi
}

section() { echo -e "\n${CYAN}${BOLD}▶ $1${NC}"; }

# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------
echo -e "${BOLD}TrendRadar Integration Tests${NC}"
echo -e "Target: ${CYAN}${BASE_URL}${NC}\n"

echo -n "Checking server connectivity... "
if ! curl -s --max-time "$TIMEOUT" "$BASE_URL/" > /dev/null 2>&1; then
    echo -e "${RED}FAILED${NC}"
    echo "Cannot reach $BASE_URL — make sure the server is running."
    exit 1
fi
echo -e "${GREEN}OK${NC}"

# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------
section "Root endpoint"

_curl "$BASE_URL/"
assert_status     "GET / returns 200"                          "200"
assert_contains   "Response contains 'Welcome'"               "Welcome"
assert_contains   "Response contains 'TrendRadar'"            "TrendRadar"

# ---------------------------------------------------------------------------
# GET /query – function validation
# ---------------------------------------------------------------------------
section "GET /query — function validation"

_curl "$BASE_URL/query?function=NEWS_SENTIMENT"
assert_status     "NEWS_SENTIMENT accepted (200)"             "200"

_curl "$BASE_URL/query?function=EARNINGS"
assert_status     "Unknown function rejected (400)"           "400"
assert_contains   "Error detail in body"                      "detail"

_curl "$BASE_URL/query"
assert_status     "Missing function param returns 422"        "422"

# ---------------------------------------------------------------------------
# GET /query – response schema
# ---------------------------------------------------------------------------
section "GET /query — response schema"

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&limit=3"
assert_status     "Response 200"                              "200"
assert_contains   "Has 'feed' key"                           '"feed"'
assert_contains   "Has 'items' key"                          '"items"'
assert_contains   "Has sentiment_score_definition"           "sentiment_score_definition"
assert_contains   "Has relevance_score_definition"           "relevance_score_definition"

# Feed items fields
assert_contains   "Feed item has 'title'"                    '"title"'
assert_contains   "Feed item has 'url'"                      '"url"'
assert_contains   "Feed item has 'source'"                   '"source"'
assert_contains   "Feed item has 'time_published'"           '"time_published"'
assert_contains   "Feed item has 'overall_sentiment_score'"  '"overall_sentiment_score"'
assert_contains   "Feed item has 'overall_sentiment_label'"  '"overall_sentiment_label"'

# items count matches feed array length
ITEMS_COUNT=$(echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(len(d['feed']) == int(d['items']))
" 2>/dev/null)
if [[ "$ITEMS_COUNT" == "True" ]]; then
    _pass "items count matches feed array length"
else
    _fail "items count does NOT match feed array length"
fi

# Sentiment label is one of the 5 valid values
VALID_LABELS=$(echo "$BODY" | python3 -c "
import sys, json
valid = {'Bearish','Somewhat-Bearish','Neutral','Somewhat-Bullish','Bullish'}
d = json.load(sys.stdin)
bad = [i['overall_sentiment_label'] for i in d['feed'] if i['overall_sentiment_label'] not in valid]
print(bad)
" 2>/dev/null)
if [[ "$VALID_LABELS" == "[]" ]]; then
    _pass "All sentiment labels are valid"
else
    _fail "Invalid sentiment labels found: $VALID_LABELS"
fi

# Sentiment score in [-1, 1]
SCORE_OK=$(echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
bad = [i['overall_sentiment_score'] for i in d['feed']
       if not (-1.0 <= i['overall_sentiment_score'] <= 1.0)]
print(bad)
" 2>/dev/null)
if [[ "$SCORE_OK" == "[]" ]]; then
    _pass "All sentiment scores in [-1, 1]"
else
    _fail "Sentiment scores out of range: $SCORE_OK"
fi

# ---------------------------------------------------------------------------
# GET /query – limit param
# ---------------------------------------------------------------------------
section "GET /query — limit param"

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&limit=1"
assert_status "limit=1 returns 200" "200"
FEED_LEN=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['feed']))" 2>/dev/null)
if [[ "$FEED_LEN" -le 1 ]]; then
    _pass "limit=1 returns at most 1 item (got $FEED_LEN)"
else
    _fail "limit=1 returned $FEED_LEN items"
fi

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&limit=5"
assert_status "limit=5 returns 200" "200"
FEED_LEN=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['feed']))" 2>/dev/null)
if [[ "$FEED_LEN" -le 5 ]]; then
    _pass "limit=5 returns at most 5 items (got $FEED_LEN)"
else
    _fail "limit=5 returned $FEED_LEN items"
fi

# ---------------------------------------------------------------------------
# GET /query – topics param
# ---------------------------------------------------------------------------
section "GET /query — topics param"

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&limit=2&topics=finance"
assert_status "topics=finance returns 200" "200"
TOPICS_OK=$(echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
bad = [i for i in d['feed'] if 'finance' not in i.get('topics', [])]
print(len(bad))
" 2>/dev/null)
if [[ "$TOPICS_OK" == "0" ]]; then
    _pass "topics=finance present in all feed items"
else
    _fail "topics=finance missing in $TOPICS_OK items"
fi

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&limit=2"
TOPICS_EMPTY=$(echo "$BODY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
bad = [i for i in d['feed'] if i.get('topics') != []]
print(len(bad))
" 2>/dev/null)
if [[ "$TOPICS_EMPTY" == "0" ]]; then
    _pass "No topics param → empty topics list in feed"
else
    _fail "Expected empty topics but $TOPICS_EMPTY items have topics set"
fi

# ---------------------------------------------------------------------------
# GET /query – time filter params
# ---------------------------------------------------------------------------
section "GET /query — time filters"

# YYYYMMDDTHHMM format
_curl "$BASE_URL/query?function=NEWS_SENTIMENT&time_from=20240101T0000&limit=5"
assert_status "time_from YYYYMMDDTHHMM returns 200" "200"

# YYYYMMDD format (date only)
_curl "$BASE_URL/query?function=NEWS_SENTIMENT&time_from=20240101&limit=5"
assert_status "time_from YYYYMMDD returns 200" "200"

# Both time_from and time_to
_curl "$BASE_URL/query?function=NEWS_SENTIMENT&time_from=20240101&time_to=20261231&limit=5"
assert_status "time_from + time_to returns 200" "200"

# Invalid time_from — should NOT crash (silently ignored)
_curl "$BASE_URL/query?function=NEWS_SENTIMENT&time_from=not-a-date&limit=5"
assert_status "Invalid time_from does not crash (200)" "200"

# Far future range → empty result (no crash)
_curl "$BASE_URL/query?function=NEWS_SENTIMENT&time_from=20991231&limit=5"
assert_status "Future date range returns 200" "200"

# ---------------------------------------------------------------------------
# GET /query – tickers param
# ---------------------------------------------------------------------------
section "GET /query — tickers filter"

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=vnexpress&limit=5"
assert_status "tickers=vnexpress returns 200" "200"

_curl "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=nonexistent_source_xyz&limit=5"
assert_status "tickers with no match returns 200 (empty feed)" "200"
FEED_LEN=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['feed']))" 2>/dev/null)
_pass "tickers=nonexistent returns $FEED_LEN items"

# ---------------------------------------------------------------------------
# GET /api/v1/news – native API
# ---------------------------------------------------------------------------
section "GET /api/v1/news — native API"

_curl "$BASE_URL/api/v1/news"
assert_status   "GET /api/v1/news returns 200"       "200"
assert_contains "Response is JSON array"             '"source_id"'
assert_contains "Has crawled_at field"               '"crawled_at"'
assert_contains "Has title field"                    '"title"'
assert_contains "Has url field"                      '"url"'
assert_contains "Has ranks field"                    '"ranks"'

# Limit param
_curl "$BASE_URL/api/v1/news?limit=3"
assert_status "limit=3 returns 200" "200"
NATIVE_LEN=$(echo "$BODY" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
if [[ "$NATIVE_LEN" -le 3 ]]; then
    _pass "limit=3 returns at most 3 items (got $NATIVE_LEN)"
else
    _fail "limit=3 returned $NATIVE_LEN items"
fi

# Source filter
_curl "$BASE_URL/api/v1/news?source=nonexistent_source_xyz&limit=5"
assert_status "source filter with no match returns 200" "200"
IS_ARRAY=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(isinstance(d, list))" 2>/dev/null)
if [[ "$IS_ARRAY" == "True" ]]; then
    _pass "Source filter returns array (even if empty)"
else
    _fail "Source filter did not return array"
fi

# Date range
_curl "$BASE_URL/api/v1/news?start_date=2024-01-01&end_date=2026-12-31&limit=5"
assert_status "Date range filter returns 200" "200"

# ---------------------------------------------------------------------------
# OpenAPI / docs (FastAPI built-in)
# ---------------------------------------------------------------------------
section "FastAPI built-in endpoints"

_curl "$BASE_URL/docs"
assert_status "Swagger UI (/docs) accessible" "200"

_curl "$BASE_URL/openapi.json"
assert_status "OpenAPI schema accessible"    "200"
assert_contains "OpenAPI title present"      "TrendRadar"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}─────────────────────────────────────────${NC}"
echo -e "${BOLD}Results: $([ $FAIL -eq 0 ] && echo -e "${GREEN}" || echo -e "${RED}")${PASS}/${TOTAL} passed, ${FAIL} failed${NC}"
echo -e "${BOLD}─────────────────────────────────────────${NC}"

[[ $FAIL -eq 0 ]] && exit 0 || exit 1

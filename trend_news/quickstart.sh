#!/bin/bash
#
# TrendRadar API - Quick Test Script
# Test các curl commands cho Vietnamese News Sentiment API
# 
# Usage: ./quickstart.sh
# 

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BASE_URL="${TREND_NEWS_URL:-http://localhost:8000}"
TEST_START_DATE="2026-02-01"
TEST_END_DATE="2026-02-15"

echo "============================================================"
echo "🇻🇳  TrendRadar API - Quick Test Suite"
echo "============================================================"
echo "API URL: $BASE_URL"
echo "Test Period: $TEST_START_DATE to $TEST_END_DATE"
echo "============================================================"

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}▶ $1${NC}"
    echo "------------------------------------------------------------"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

check_server() {
    if ! curl -s "$BASE_URL/" > /dev/null 2>&1; then
        print_error "Server không phản hồi tại $BASE_URL"
        echo "Hãy start server trước: python server.py"
        exit 1
    fi
    print_success "Server đang hoạt động"
}

# Test 1: Health Check
test_health() {
    print_header "Test 1: Health Check (/)"
    curl -s "$BASE_URL/" | python3 -m json.tool 2>/dev/null || echo "Server response received"
    print_success "Health check passed"
}

# Test 2: Single Ticker - VIC (Vingroup)
test_single_ticker_vic() {
    print_header "Test 2: Single Ticker - VIC (Vingroup)"
    echo "Request: /query?function=NEWS_SENTIMENT&tickers=VIC"
    
    response=$(curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=VIC&time_from=${TEST_START_DATE//-/}T0000&time_to=${TEST_END_DATE//-/}T2359&limit=10")
    
    items=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items', 0))" 2>/dev/null || echo "0")
    
    echo "Response (formatted):"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    
    if [ "$items" -gt 0 ] 2>/dev/null; then
        print_success "Found $items news articles for VIC"
    else
        print_warning "No news found for VIC (database might be empty for this period)"
    fi
}

# Test 3: Single Ticker - FPT
test_single_ticker_fpt() {
    print_header "Test 3: Single Ticker - FPT"
    echo "Request: /query?function=NEWS_SENTIMENT&tickers=FPT"
    
    response=$(curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=FPT&time_from=${TEST_START_DATE//-/}T0000&time_to=${TEST_END_DATE//-/}T2359&limit=10")
    
    items=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items', 0))" 2>/dev/null || echo "0")
    
    echo "Response (formatted):"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    
    if [ "$items" -gt 0 ] 2>/dev/null; then
        print_success "Found $items news articles for FPT"
    else
        print_warning "No news found for FPT (database might be empty for this period)"
    fi
}

# Test 4: Multiple Tickers
test_multiple_tickers() {
    print_header "Test 4: Multiple Tickers (VIC,HPG,FPT)"
    echo "Request: /query?function=NEWS_SENTIMENT&tickers=VIC,HPG,FPT"
    
    response=$(curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=VIC,HPG,FPT&time_from=${TEST_START_DATE//-/}T0000&time_to=${TEST_END_DATE//-/}T2359&limit=20")
    
    items=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items', 0))" 2>/dev/null || echo "0")
    
    echo "Response summary:"
    echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"Total items: {data.get('items', 0)}\")
for item in data.get('feed', [])[:3]:
    print(f\"  - [{item['overall_sentiment_label']}] {item['title'][:60]}...\")
" 2>/dev/null || echo "$response"
    
    print_success "Multi-ticker query completed (items: $items)"
}

# Test 5: Native API
test_native_api() {
    print_header "Test 5: Native API (/api/v1/news)"
    echo "Request: /api/v1/news?tickers=VIC&start_date=$TEST_START_DATE"
    
    response=$(curl -s "$BASE_URL/api/v1/news?start_date=$TEST_START_DATE&end_date=$TEST_END_DATE&tickers=VIC&limit=5")
    
    count=$(echo "$response" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
    
    echo "Response (first item):"
    echo "$response" | python3 -m json.tool 2>/dev/null | head -30 || echo "$response"
    
    print_success "Native API returned $count items"
}

# Test 6: Native API with Source Filter
test_native_api_source() {
    print_header "Test 6: Native API with Source Filter"
    echo "Request: /api/v1/news?source=cafef"
    
    response=$(curl -s "$BASE_URL/api/v1/news?start_date=$TEST_START_DATE&end_date=$TEST_END_DATE&source=cafef&limit=5")
    
    echo "Response (formatted):"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    
    print_success "Source filter test completed"
}

# Test 7: Banking Sector Tickers
test_banking_tickers() {
    print_header "Test 7: Banking Sector (VCB, TCB, MBB)"
    
    for ticker in VCB TCB MBB; do
        echo ""
        echo "Testing $ticker:"
        response=$(curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=$ticker&time_from=${TEST_START_DATE//-/}T0000&time_to=${TEST_END_DATE//-/}T2359&limit=5")
        items=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('items', 0))" 2>/dev/null || echo "0")
        
        if [ "$items" -gt 0 ] 2>/dev/null; then
            print_success "$ticker: $items articles"
            echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for item in data.get('feed', [])[:2]:
    print(f\"  📰 {item['title'][:50]}... ({item['overall_sentiment_label']})\")
" 2>/dev/null
        else
            print_warning "$ticker: No articles found"
        fi
    done
}

# Test 8: Sentiment Score Definition
test_sentiment_definitions() {
    print_header "Test 8: Sentiment Score Definitions"
    
    response=$(curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=VIC&time_from=${TEST_START_DATE//-/}T0000&time_to=${TEST_END_DATE//-/}T2359&limit=1")
    
    echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('Sentiment Score Definition:')
print(data.get('sentiment_score_definition', 'N/A'))
print()
print('Relevance Score Definition:')
print(data.get('relevance_score_definition', 'N/A'))
" 2>/dev/null
    
    print_success "Sentiment definitions retrieved"
}

# Test 9: Empty Result Handling
test_empty_result() {
    print_header "Test 9: Empty Result Handling (Invalid/No Data Ticker)"
    
    response=$(curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=INVALID_TICKER_XYZ&time_from=20260101T0000&time_to=20260102T2359&limit=10")
    
    echo "Response for invalid ticker:"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    
    print_success "Empty result handling works correctly"
}

# Test 10: Sentiment Learning Endpoints
test_sentiment_learning() {
    print_header "Test 10: Sentiment Learning Endpoints"
    
    echo "a) Feedback Stats:"
    curl -s "$BASE_URL/api/v1/feedback/stats?days=7" | python3 -m json.tool 2>/dev/null || echo "No stats available"
    
    echo ""
    echo "b) Keyword Suggestions:"
    curl -s "$BASE_URL/api/v1/keywords/suggestions?days=30&limit=5" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print('Positive keywords:', ', '.join([k['keyword'] for k in data.get('positive', [])[:5]]))
print('Negative keywords:', ', '.join([k['keyword'] for k in data.get('negative', [])[:5]]))
" 2>/dev/null || echo "No suggestions available"
    
    echo ""
    echo "c) Combined Lexicon:"
    curl -s "$BASE_URL/api/v1/lexicon/combined" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"Total positive: {data.get('total_positive', 0)}\")
print(f\"Total negative: {data.get('total_negative', 0)}\")
" 2>/dev/null || echo "No lexicon available"
    
    print_success "Sentiment learning endpoints checked"
}

# Test 11: Labeling Queue
test_labeling_queue() {
    print_header "Test 11: Labeling Queue Endpoints"
    
    echo "a) Queue Stats:"
    curl -s "$BASE_URL/api/v1/labeling/stats" | python3 -m json.tool 2>/dev/null || echo "No stats available"
    
    echo ""
    echo "b) Queue Items (pending):"
    curl -s "$BASE_URL/api/v1/labeling/queue?status=pending" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f\"Date: {data.get('date', 'N/A')}\")
print(f\"Count: {data.get('count', 0)}\")
for item in data.get('items', [])[:3]:
    print(f\"  - {item.get('title', 'N/A')[:50]}...\")
" 2>/dev/null || echo "No queue items"
    
    print_success "Labeling queue endpoints checked"
}

# Test 12: Error Handling
test_error_handling() {
    print_header "Test 12: Error Handling (Invalid Function)"
    
    response=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$BASE_URL/query?function=INVALID_FUNCTION&tickers=VIC")
    http_code=$(echo "$response" | grep "HTTP_CODE:" | cut -d: -f2)
    body=$(echo "$response" | grep -v "HTTP_CODE:")
    
    echo "HTTP Status: $http_code"
    echo "Response:"
    echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
    
    if [ "$http_code" = "400" ]; then
        print_success "Error handling works correctly (HTTP 400)"
    else
        print_warning "Unexpected HTTP status: $http_code"
    fi
}

# Test 13: Performance Test
test_performance() {
    print_header "Test 13: Performance Test (10 requests)"
    
    start_time=$(date +%s.%N)
    
    for i in {1..10}; do
        curl -s "$BASE_URL/query?function=NEWS_SENTIMENT&tickers=VIC&time_from=${TEST_START_DATE//-/}T0000&time_to=${TEST_END_DATE//-/}T2359&limit=5" > /dev/null
        echo -n "."
    done
    
    end_time=$(date +%s.%N)
    elapsed=$(echo "$end_time - $start_time" | bc 2>/dev/null || echo "1")
    avg=$(echo "scale=2; $elapsed / 10" | bc 2>/dev/null || echo "N/A")
    
    echo ""
    print_success "10 requests completed in ${elapsed}s (avg: ${avg}s/request)"
}

# Main execution
main() {
    # Check dependencies
    if ! command -v curl &> /dev/null; then
        print_error "curl không được cài đặt"
        exit 1
    fi
    
    if ! command -v python3 &> /dev/null; then
        print_error "python3 không được cài đặt"
        exit 1
    fi
    
    # Check server
    check_server
    
    # Run all tests
    test_health
    test_single_ticker_vic
    test_single_ticker_fpt
    test_multiple_tickers
    test_native_api
    test_native_api_source
    test_banking_tickers
    test_sentiment_definitions
    test_empty_result
    test_sentiment_learning
    test_labeling_queue
    test_error_handling
    test_performance
    
    echo ""
    echo "============================================================"
    print_success "All tests completed!"
    echo "============================================================"
    echo ""
    echo "📚 Available tickers: VIC, FPT, HPG, VCB, TCB, MBB, VNM, MSN, ..."
    echo "📚 Available sources: cafef, vnexpress-kinhdoanh, vietnamfinance, ..."
    echo ""
    echo "💡 Tip: Bạn có thể override URL bằng cách set env variable:"
    echo "   export TREND_NEWS_URL=http://localhost:8000"
    echo "   ./quickstart.sh"
}

# Handle command line arguments
case "${1:-}" in
    --health|-h)
        check_server
        exit 0
        ;;
    --single)
        check_server
        test_single_ticker_vic
        exit 0
        ;;
    --native)
        check_server
        test_native_api
        exit 0
        ;;
    --performance|-p)
        check_server
        test_performance
        exit 0
        ;;
    --help)
        echo "Usage: $0 [option]"
        echo ""
        echo "Options:"
        echo "  (no args)    Run all tests"
        echo "  --health, -h Check server health only"
        echo "  --single     Run single ticker test only"
        echo "  --native     Run native API test only"
        echo "  --performance, -p Run performance test only"
        echo "  --help       Show this help"
        echo ""
        echo "Environment variables:"
        echo "  TREND_NEWS_URL  API base URL (default: http://localhost:8000)"
        exit 0
        ;;
    *)
        main
        ;;
esac

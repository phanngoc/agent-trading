# TrendNews API Integration for TradingAgents

## Overview

This integration connects the TradingAgents multi-agent trading system with the trend_news API, enabling Vietnamese market news analysis with built-in sentiment scoring. The integration replaces yfinance (which currently has no news data) with a local Vietnamese news database that includes:

- **Vietnamese market news sources**: VnExpress, CafeF, Dan Tri, Money24h
- **Real-time sentiment analysis**: Sentiment scores and labels (Bearish/Bullish) for each article
- **Trending data**: Articles ranked by popularity
- **Historical data**: Local database with no API rate limits
- **Adaptive learning**: Sentiment system that improves over time with feedback

## Architecture

The integration follows the existing **vendor routing pattern** in TradingAgents:

```
News Analyst Agent
    ↓
calls get_news() tool
    ↓
route_to_vendor() [interface.py]
    ↓
checks config → "news_data": "trend_news"
    ↓
calls get_trend_news() [trend_news_api.py]
    ↓
HTTP request → http://localhost:8000/query
    ↓
trend_news server returns news with sentiment
    ↓
Formatted as markdown string with sentiment indicators
    ↓
Returned to News Analyst for LLM analysis
```

### Fallback Chain

If trend_news API fails (server down, no data, etc.), the system automatically falls back to:
1. **yfinance** (alternative implementation)
2. **alpha_vantage** (if API key configured)

This ensures agents always get news data even if the trend_news server is unavailable.

## Files Modified/Created

### Created Files

#### 1. `tradingagents/dataflows/trend_news_api.py` ✨ NEW
Main integration module that:
- Maps Vietnamese stock tickers to company names (VIC.VN → "Vingroup", etc.)
- Calls trend_news API at `http://localhost:8000/query`
- Formats response as markdown string with sentiment scores
- Handles errors gracefully with informative messages
- Supports configurable API URL via config

**Key Functions:**
```python
get_news(ticker, start_date, end_date) -> str
    # Fetches company-specific news with sentiment

get_global_news(curr_date, look_back_days, limit) -> str
    # Fetches broad Vietnamese market news
```

**Supported Tickers:**
```
VIC.VN  → Vingroup          HPG.VN → Hòa Phát
VNM.VN  → Vinamilk          TCB.VN → Techcombank
VCB.VN  → Vietcombank       VRE.VN → Vincom Retail
VHM.VN  → Vinhomes          GAS.VN → PV Gas
VPB.VN  → VPBank            SAB.VN → Sabeco
MSN.VN  → Masan             POW.VN → PetroVietnam Power
PLX.VN  → Petrolimex        MWG.VN → Mobile World
FPT.VN  → FPT Corporation
```

### Modified Files

#### 2. `tradingagents/dataflows/interface.py` 🔧 MODIFIED
- Added import: `from .trend_news_api import get_news, get_global_news`
- Added `"trend_news"` to `VENDOR_LIST`
- Mapped `trend_news` functions in `VENDOR_METHODS`:
  ```python
  "get_news": {
      "alpha_vantage": get_alpha_vantage_news,
      "yfinance": get_news_yfinance,
      "trend_news": get_trend_news,  # NEW
  }
  ```

#### 3. `tradingagents/default_config.py` ⚙️ MODIFIED
Changed default news vendor and added configuration:
```python
"data_vendors": {
    "news_data": "trend_news",  # Changed from "yfinance"
},
"trend_news_api_url": "http://localhost:8000",
"trend_news_sources": [],  # Optional filter
```

### Test Files

#### 4. `test_trend_news_integration.py` 🧪 NEW
Comprehensive test script that verifies:
- Server availability
- API endpoints
- Ticker mapping
- Routing system integration
- Output format

## Usage

### 1. Start the trend_news Server

```bash
cd trend_news
python server.py
```

The server will start at `http://localhost:8000`

Verify it's running:
```bash
curl http://localhost:8000/
# Should return: {"message": "Welcome to TrendRadar API"}
```

### 2. Run TradingAgents with Vietnamese Ticker

```bash
python main.py --ticker VIC.VN --start-date 2026-02-01 --end-date 2026-02-15
```

Or in interactive mode:
```bash
python main.py
# Enter ticker: VIC.VN
```

### 3. View Results

The News Analyst report will now include Vietnamese news with sentiment:

```markdown
## VIC.VN News from Vietnamese Sources, 2026-02-08 to 2026-02-15:
**Company**: Vingroup
**Total Articles**: 12

### Vingroup công bố kế hoạch mở rộng Vinfast tại Mỹ
**[Sentiment: Bullish (0.45)]**
**Source**: vnexpress_kinhdoanh
**Published**: 2026-02-14 09:30:00
**Summary**: Ranked: 1,3,5
**Link**: https://vnexpress.net/...

### Vinhomes ra mắt dự án cao cấp tại Hà Nội
**[Sentiment: Somewhat-Bullish (0.25)]**
**Source**: cafef_batdongsan
**Published**: 2026-02-13 14:20:00
**Link**: https://cafef.vn/...
```

## Configuration Options

### Switch News Vendors

Edit `tradingagents/default_config.py`:

```python
# Use trend_news (default)
"news_data": "trend_news"

# Use yfinance instead
"news_data": "yfinance"

# Use alpha_vantage (requires API key)
"news_data": "alpha_vantage"

# Use multiple with fallback: trend_news → yfinance → alpha_vantage
"news_data": "trend_news,yfinance,alpha_vantage"
```

### Change API URL

If running trend_news on a different port or server:

```python
"trend_news_api_url": "http://localhost:9000"
# or
"trend_news_api_url": "http://192.168.1.100:8000"
```

### Filter Vietnamese Sources

To only use specific news sources:

```python
"trend_news_sources": [
    "vnexpress_kinhdoanh",
    "cafef_chungkhoan"
]
```

Available sources: `vnexpress_kinhdoanh`, `vnexpress_chungkhoan`, `cafef_chungkhoan`, `cafef_batdongsan`, `dantri_kinhdoanh`, `dantri_chungkhoan`, `money24h`

## Testing

Run the integration test:

```bash
python test_trend_news_integration.py
```

Expected output:
```
Test 1: Checking if trend_news server is running...
✓ trend_news server is running at http://localhost:8000

Test 2: Testing direct API query...
✓ API returned 50 news items

Test 3: Testing ticker mapping...
✓ VIC.VN → Vingroup
✓ VNM.VN → Vinamilk
...

Test 4: Testing integration through routing system...
✓ trend_news is set as the default news vendor
✓ Router successfully called trend_news

Test 5: Testing output format...
✓ Output format is correct!
```

## API Response Format

The trend_news API uses an **Alpha Vantage-compatible format** for seamless integration:

### Request
```
GET /query?function=NEWS_SENTIMENT&tickers=Vingroup&time_from=20260208T0000&time_to=20260215T0000&limit=50
```

### Response
```json
{
  "items": "12",
  "sentiment_score_definition": "x <= -0.35: Bearish; -0.35 < x <= -0.15: Somewhat-Bearish...",
  "relevance_score_definition": "0 < x <= 1: with a higher score indicating higher relevance.",
  "feed": [
    {
      "title": "Vingroup công bố kế hoạch mở rộng...",
      "url": "https://vnexpress.net/...",
      "time_published": "20260214T093000",
      "source": "vnexpress_kinhdoanh",
      "source_domain": "vnexpress_kinhdoanh",
      "summary": "Ranked: 1,3,5",
      "topics": [],
      "overall_sentiment_score": 0.45,
      "overall_sentiment_label": "Bullish"
    }
  ]
}
```

### Sentiment Labels
- **Bullish** (≥ 0.35): Strong positive sentiment
- **Somewhat-Bullish** (0.15 to 0.35): Moderate positive
- **Neutral** (-0.15 to 0.15): Balanced or unclear
- **Somewhat-Bearish** (-0.35 to -0.15): Moderate negative
- **Bearish** (≤ -0.35): Strong negative sentiment

## Adding New Tickers

To add support for a new Vietnamese stock:

1. Edit `tradingagents/dataflows/trend_news_api.py`
2. Add to `VIETNAMESE_TICKER_MAP`:

```python
VIETNAMESE_TICKER_MAP = {
    # ... existing tickers ...
    "NEW.VN": ["Company Name", "Alternative Name", "Ticker"],
}
```

3. Test:
```bash
python test_trend_news_integration.py
# Verify NEW.VN appears in ticker mapping section
```

## Troubleshooting

### Server Not Running
**Symptom**: `Error fetching news from trend_news API: Connection refused`

**Solution**:
```bash
cd trend_news
python server.py
```

### No Data Returned
**Symptom**: `No news found for VIC.VN between dates...`

**Possible causes**:
1. Database empty or outdated → Run `python main.py` in trend_news to scrape new data
2. Date range too narrow → Expand date range
3. Company name not in database → Check logs for actual company names in DB

### Wrong Sentiment Scores
**Symptom**: Sentiment doesn't match article tone

**Solution**: The trend_news system has a learning mechanism. Use the feedback API:
```bash
curl -X POST http://localhost:8000/api/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "news_title": "Article title",
    "predicted_score": 0.45,
    "predicted_label": "Bullish",
    "user_score": -0.25,
    "user_label": "Bearish",
    "comment": "Article discusses company losses"
  }'
```

Over time, approved keywords improve sentiment accuracy.

### Ticker Not Mapped
**Symptom**: `No Vietnamese company mapping found for ticker XXXX.VN`

**Solution**: Add ticker to `VIETNAMESE_TICKER_MAP` in `trend_news_api.py` (see "Adding New Tickers" section)

### API Rate Limits
**Advantage**: trend_news has **no rate limits** since it uses a local database. You can query as frequently as needed without throttling.

## Integration Benefits

### Compared to yfinance:
- ✅ **Has news data** (yfinance currently returns empty)
- ✅ **Vietnamese sources** (yfinance only has English news)
- ✅ **Sentiment included** (yfinance requires separate analysis)
- ✅ **No rate limits** (local database)
- ✅ **Trending data** (knows which articles are most popular)

### Compared to Alpha Vantage:
- ✅ **Vietnamese market focus** (Alpha Vantage is global)
- ✅ **No API key required** (local setup)
- ✅ **Unlimited queries** (Alpha Vantage has 25 calls/day limit on free tier)
- ✅ **Adaptive learning** (sentiment improves over time)
- ✅ **Faster response** (local database vs. external API)

## Next Steps

### Enhancements to Consider:

1. **Multi-language Support**: Add English translations via API
2. **Real-time Updates**: WebSocket integration for live news
3. **Historical Analysis**: Correlate sentiment trends with stock performance
4. **Custom Lexicon**: Fine-tune sentiment for financial Vietnamese terminology
5. **Agent Specialization**: Create Vietnam-focused analyst agent
6. **Trend Analysis**: Leverage ranking data to identify breaking news

### Contributing

To expand ticker coverage:
1. Research Vietnamese company names and common references
2. Add to `VIETNAMESE_TICKER_MAP` with all name variations
3. Test with actual news queries
4. Submit PR with documentation

## License

This integration follows the same license as the parent TradingAgents project.

## Support

For issues specific to:
- **Integration code**: Check this README, run test script
- **trend_news API**: See trend_news/README.md
- **TradingAgents system**: See main project documentation

---

**Status**: ✅ **Production Ready**

The integration is fully functional with:
- Comprehensive error handling
- Automatic fallback support
- Configurable options
- Test coverage
- Documentation

Ready to analyze Vietnamese market news with sentiment-aware AI agents! 🚀

# TrendRadar API Documentation

**Version**: 1.0.0
**Base URL**: `http://localhost:8000`
**Interactive Docs**: `http://localhost:8000/docs` (Swagger UI)

---

## Overview

TrendRadar is a Vietnamese financial news aggregation API compatible with the Alpha Vantage `NEWS_SENTIMENT` format. It indexes news from 30+ Vietnamese sources, performs Vietnamese-language sentiment analysis, and provides full-text search via FTS5 with BM25 relevance ranking.

### Key Features
- **Alpha Vantage compatible** `/query` endpoint
- **Ticker-aware search**: `VIC` → searches Vingroup, VIN, Vinhomes, ...
- **FTS5 full-text index** with BM25 relevance scoring
- **Sentiment learning**: feedback loop to improve predictions over time
- **100+ Vietnamese stock tickers** supported

---

## Authentication

No authentication required. The `apikey` parameter is accepted but ignored.

---

## Endpoints

### 1. Root

```
GET /
```

**Response**
```json
{ "message": "Welcome to TrendRadar API" }
```

---

### 2. News Sentiment (Alpha Vantage Compatible)

```
GET /query
```

Alpha Vantage `NEWS_SENTIMENT` compatible endpoint. Useful as a drop-in replacement for agents configured with `"news_data": "alpha_vantage"`.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `function` | string | **Yes** | Must be `NEWS_SENTIMENT` |
| `tickers` | string | No | Stock ticker(s) for title search. Expanded via alias map. E.g. `VIC`, `HPG`, `VIC,HPG` |
| `topics` | string | No | Topic tag to attach to results (passed through, not filtered) |
| `time_from` | string | No | Start time `YYYYMMDDTHHMM` or `YYYYMMDD` |
| `time_to` | string | No | End time `YYYYMMDDTHHMM` or `YYYYMMDD` |
| `limit` | integer | No | Max results (default: `50`) |
| `apikey` | string | No | Ignored |

#### Ticker Search Behaviour

When `tickers` is provided, the API performs **FTS5 full-text search** on news titles using an alias dictionary:

| Ticker | Searches for |
|--------|-------------|
| `VIC` | Vingroup, VIC, tập đoàn Vin, dòng tiền VIN, nhóm VIN |
| `HPG` | Hòa Phát, Hoa Phat, HPG, thép Hòa Phát |
| `VNM` | Vinamilk, VNM, sữa Vinamilk |
| `MWG` | Mobile World, Thế Giới Di Động, MWG, TGDĐ |
| `BATDONGSAN` | bất động sản, nhà đất, dự án, chung cư, đất nền |
| `NGANHANG` | ngân hàng, tín dụng, lãi suất, cho vay, NHNN |

> See `src/core/ticker_mapper.py` for the full alias dictionary (100+ tickers).

#### Example Request

```bash
# Get VIC news for Feb 2026
curl "http://localhost:8000/query?function=NEWS_SENTIMENT&tickers=VIC&time_from=20260201&time_to=20260215&limit=20"

# Multiple tickers
curl "http://localhost:8000/query?function=NEWS_SENTIMENT&tickers=VIC,HPG&limit=30"

# Real estate sector
curl "http://localhost:8000/query?function=NEWS_SENTIMENT&tickers=BATDONGSAN&limit=50"
```

#### Example Response

```json
{
  "items": "3",
  "sentiment_score_definition": "x <= -0.35: Bearish; -0.35 < x <= -0.15: Somewhat-Bearish; -0.15 < x < 0.15: Neutral; 0.15 <= x < 0.35: Somewhat-Bullish; x >= 0.35: Bullish",
  "relevance_score_definition": "0 < x <= 1: with a higher score indicating higher relevance.",
  "feed": [
    {
      "title": "Cổ phiếu nhóm Vingroup ngược dòng thị trường",
      "url": "https://vnexpress.net/...",
      "time_published": "20260212T143022",
      "summary": "Ranked: 1,3",
      "banner_image": null,
      "source": "vnexpress-chungkhoan",
      "category_within_source": "General",
      "source_domain": "vnexpress-chungkhoan",
      "topics": [],
      "overall_sentiment_score": 0.21,
      "overall_sentiment_label": "Somewhat-Bullish",
      "relevance_score": 948
    }
  ]
}
```

#### Sentiment Labels

| Score Range | Label |
|-------------|-------|
| `x >= 0.35` | Bullish |
| `0.15 ≤ x < 0.35` | Somewhat-Bullish |
| `-0.15 < x < 0.15` | Neutral |
| `-0.35 < x ≤ -0.15` | Somewhat-Bearish |
| `x ≤ -0.35` | Bearish |

---

### 3. Native News API

```
GET /api/v1/news
```

Raw news query with more flexible filtering. Returns DB rows directly without Alpha Vantage wrapping.

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `start_date` | string | No | ISO date `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| `end_date` | string | No | ISO date `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| `source` | string | No | Filter by exact scraper source ID (see [Sources](#news-sources)) |
| `tickers` | string | No | Comma-separated tickers for FTS5 title search |
| `limit` | integer | No | Max results (default: `50`) |

> **Note**: `source` and `tickers` are independent filters. Combine them to get VIC news specifically from cafef: `?tickers=VIC&source=cafef`

#### Example Request

```bash
# All news from cafef today
curl "http://localhost:8000/api/v1/news?source=cafef&start_date=2026-02-15"

# HPG news last 7 days
curl "http://localhost:8000/api/v1/news?tickers=HPG&start_date=2026-02-08&end_date=2026-02-15&limit=20"

# Combine: VIC news from vnexpress only
curl "http://localhost:8000/api/v1/news?tickers=VIC&source=vnexpress-kinhdoanh"
```

#### Example Response

```json
[
  {
    "source_id": "vnexpress-chungkhoan",
    "title": "Cổ phiếu nhóm Vingroup ngược dòng thị trường",
    "url": "https://vnexpress.net/...",
    "mobile_url": "",
    "ranks": "1,3",
    "crawled_at": "2026-02-12T14:30:22",
    "relevance_score": 948
  }
]
```

---

### 4. Submit Sentiment Feedback

```
POST /api/v1/feedback
```

Submit user correction on a sentiment prediction. Used to train the learning system.

#### Request Body

```json
{
  "news_title": "Cổ phiếu nhóm Vingroup ngược dòng thị trường",
  "predicted_score": 0.15,
  "predicted_label": "Somewhat-Bullish",
  "user_score": 0.4,
  "user_label": "Bullish",
  "news_id": 142,
  "news_url": "https://vnexpress.net/...",
  "comment": "Clear positive momentum article"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `news_title` | string | **Yes** | The news headline |
| `predicted_score` | float | **Yes** | Score the model predicted (-1.0 to 1.0) |
| `predicted_label` | string | **Yes** | Label the model predicted |
| `user_score` | float | **Yes** | Correct score per user (-1.0 to 1.0) |
| `user_label` | string | **Yes** | Correct label per user |
| `news_id` | integer | No | DB article ID |
| `news_url` | string | No | Article URL |
| `comment` | string | No | Explanation |

#### Example

```bash
curl -X POST "http://localhost:8000/api/v1/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "news_title": "Hòa Phát đạt doanh thu kỷ lục",
    "predicted_score": 0.1,
    "predicted_label": "Neutral",
    "user_score": 0.45,
    "user_label": "Bullish"
  }'
```

#### Response

```json
{
  "success": true,
  "feedback_id": 42,
  "message": "Feedback recorded successfully"
}
```

---

### 5. Feedback Statistics

```
GET /api/v1/feedback/stats?days=7
```

Model accuracy metrics over the last N days.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | integer | `7` | Lookback window in days |

#### Response

```json
{
  "total_feedback": 145,
  "avg_error": 0.18,
  "accuracy_rate": 0.72,
  "label_distribution": {
    "Bullish": 42,
    "Somewhat-Bullish": 38,
    "Neutral": 30,
    "Somewhat-Bearish": 20,
    "Bearish": 15
  }
}
```

---

### 6. Keyword Suggestions

```
GET /api/v1/keywords/suggestions
```

Auto-extracted keywords from feedback data that could improve sentiment lexicon.

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `days` | integer | `30` | Lookback window |
| `min_frequency` | integer | `3` | Min occurrences to include |
| `limit` | integer | `50` | Max per category |

#### Response

```json
{
  "positive": [
    {"keyword": "tăng mạnh", "frequency": 12, "avg_score": 0.38},
    {"keyword": "đạt kỷ lục", "frequency": 8, "avg_score": 0.41}
  ],
  "negative": [
    {"keyword": "giảm sâu", "frequency": 9, "avg_score": -0.35},
    {"keyword": "cảnh báo", "frequency": 7, "avg_score": -0.28}
  ]
}
```

---

### 7. Approve Keyword

```
POST /api/v1/keywords/approve
```

Approve a suggested keyword to be added to the learned lexicon.

#### Request Body

```json
{
  "keyword": "tăng mạnh",
  "sentiment_type": "positive",
  "weight": 0.4
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `keyword` | string | **Yes** | Vietnamese keyword to add |
| `sentiment_type` | string | **Yes** | `"positive"` or `"negative"` |
| `weight` | float | **Yes** | Sentiment weight (0.0 to 1.0) |

---

### 8. Approved Keywords

```
GET /api/v1/keywords/approved
```

List all keywords currently in the learned lexicon.

#### Response

```json
{
  "positive": [
    {"keyword": "tăng mạnh", "weight": 0.4, "frequency": 12}
  ],
  "negative": [
    {"keyword": "giảm sâu", "weight": 0.35, "frequency": 9}
  ]
}
```

---

### 9. Combined Lexicon

```
GET /api/v1/lexicon/combined
```

Full lexicon combining static base keywords + user-approved learned keywords.

#### Response

```json
{
  "positive": {"tăng": 0.3, "tích cực": 0.35, "tăng mạnh": 0.4},
  "negative": {"giảm": -0.3, "rủi ro": -0.25, "giảm sâu": -0.35},
  "total_positive": 48,
  "total_negative": 35
}
```

---

### 10. Improvement Suggestions

```
GET /api/v1/analysis/improvements
```

Comprehensive suggestions for improving sentiment model accuracy.

#### Response

```json
{
  "suggested_positive_keywords": ["bứt phá", "phục hồi mạnh"],
  "suggested_negative_keywords": ["điều chỉnh", "áp lực bán"],
  "accuracy_trend": "improving",
  "top_misclassified_patterns": ["earnings miss", "quarterly loss"]
}
```

---

## News Sources

### Vietnamese Sources

| Source ID | Publisher | Category |
|-----------|-----------|----------|
| `cafef` | CafeF | Business/Finance |
| `cafef-chungkhoan` | CafeF | Stock Market |
| `vnexpress-kinhdoanh` | VnExpress | Business |
| `vnexpress-chungkhoan` | VnExpress | Stock Market |
| `dantri-kinhdoanh` | Dan Tri | Business |
| `24hmoney` | 24HMoney | Finance/Market |
| `vietnamfinance` | VietnamFinance | Finance |
| `vietnamfinance-batdongsan` | VietnamFinance | Real Estate |
| `vietnamfinance-nganhang` | VietnamFinance | Banking |
| `vietnamfinance-taichinh` | VietnamFinance | Finance |

### International Sources

| Source ID | Publisher | Language |
|-----------|-----------|----------|
| `hackernews` | Hacker News | English |
| `producthunt` | Product Hunt | English |
| `mktnews-flash` | Market News Flash | English |
| `fastbull-news` | FastBull | English |
| `wallstreetcn-news` | Wall Street CN | Chinese |
| `wallstreetcn-quick` | Wall Street CN | Chinese |
| `jin10` | Jin10 | Chinese |
| `cls-telegraph` | CLS Telegraph | Chinese |
| `baidu` | Baidu Hot | Chinese |

---

## Python Client Examples

### Using `requests`

```python
import requests

BASE_URL = "http://localhost:8000"

def get_vn_news(ticker: str, start: str, end: str) -> list[dict]:
    """Get Vietnamese news for a stock ticker."""
    resp = requests.get(f"{BASE_URL}/query", params={
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": start.replace("-", "") + "T0000",
        "time_to": end.replace("-", "") + "T2359",
        "limit": 50,
    })
    data = resp.json()
    return data.get("feed", [])

# Usage
news = get_vn_news("VIC", "2026-02-01", "2026-02-15")
for article in news:
    print(f"[{article['overall_sentiment_label']}] {article['title']}")
```

### Native API with sector filter

```python
resp = requests.get(f"{BASE_URL}/api/v1/news", params={
    "tickers": "BATDONGSAN",  # Real estate sector
    "start_date": "2026-02-01",
    "limit": 30,
})
for article in resp.json():
    print(f"[{article['source_id']}] {article['title']}")
```

### Submit feedback

```python
resp = requests.post(f"{BASE_URL}/api/v1/feedback", json={
    "news_title": "Hòa Phát đạt doanh thu kỷ lục 2025",
    "predicted_score": 0.10,
    "predicted_label": "Neutral",
    "user_score": 0.45,
    "user_label": "Bullish",
    "comment": "Record revenue = clearly positive"
})
print(resp.json())
```

---

## AI Agent Integration

TrendRadar is integrated as a **direct DB tool** in the TradingAgents LangChain/LangGraph framework via `tradingagents/dataflows/trend_news_direct.py`.

### Configure Agent to Use TrendRadar

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = {
    "data_vendors": {
        "news_data": "trend_news",   # uses trend_news_direct.py (no server needed)
    }
}

graph = TradingAgentsGraph(config=config)
result = graph.propagate("VIC", "2026-02-15")
```

### Available Agent Tools

| Tool | Description |
|------|-------------|
| `get_vn_stock_news(ticker, start, end)` | FTS5 news search for a ticker with BM25 ranking |
| `get_vn_market_overview(date, days, limit)` | Broad market news without ticker filter |
| `get_news(ticker, start, end)` | Generic news (routes to configured vendor) |
| `get_global_news(date, days, limit)` | Generic global news |

### Ticker Format

The direct tool accepts multiple formats:

```python
# All equivalent:
get_vn_stock_news("VIC", "2026-02-01", "2026-02-15")
get_vn_stock_news("VIC.VN", "2026-02-01", "2026-02-15")  # .VN suffix stripped
get_vn_stock_news("vic", "2026-02-01", "2026-02-15")     # case-insensitive

# Sector search:
get_vn_stock_news("BATDONGSAN", "2026-02-01", "2026-02-15")
get_vn_stock_news("NGANHANG", "2026-02-01", "2026-02-15")
```

---

## Error Responses

| HTTP Code | Meaning |
|-----------|---------|
| `400` | Invalid parameter (e.g. `function != NEWS_SENTIMENT`) |
| `500` | Internal server error (DB failure, etc.) |

### Error Response Body

```json
{
  "detail": "Only NEWS_SENTIMENT function is supported currently."
}
```

---

## FTS5 Relevance Score

The `relevance_score` field in news items is derived from SQLite FTS5 `bm25()`:

```
relevance_score = round(-bm25(news_fts) × 100)
```

Higher score = title is more relevant to the query.

| Score Range | Relevance |
|-------------|-----------|
| `> 800` | Very high (ticker appears multiple times) |
| `500–800` | High (primary company name match) |
| `200–500` | Medium (alias or sector term match) |
| `< 200` | Low (partial or distant match) |

---

## Rebuild FTS Index

If the FTS5 index becomes inconsistent after bulk imports:

```python
from trend_news.src.core.database import DatabaseManager
db = DatabaseManager("output/trend_news.db")
db.rebuild_fts_index()
```

Or via CLI:

```bash
cd trend_news
python -c "
from src.core.database import DatabaseManager
db = DatabaseManager('output/trend_news.db')
db.rebuild_fts_index()
"
```

---

## Running the Server

```bash
cd trend_news
pip install -r requirements.txt

# Start server (auto-reload for development)
python server.py

# Or with uvicorn directly
uvicorn server:app --host 0.0.0.0 --port 8000 --reload

# Production
uvicorn server:app --host 0.0.0.0 --port 8000 --workers 4
```

Server starts at `http://localhost:8000`.
Swagger UI available at `http://localhost:8000/docs`.

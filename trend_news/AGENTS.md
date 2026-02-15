# TrendRadar (trend_news) - AI Coding Assistant Guide

**Version**: 1.0  
**Last Updated**: February 15, 2026  
**Purpose**: Help AI assistants quickly understand and work with this Vietnamese news scraping and sentiment analysis system

---

## 🎯 Project Overview

**TrendRadar** (branded as `trend_news` in TradingAgents integration) is a Vietnamese news scraping, aggregation, and sentiment analysis system. It collects news from 30+ Vietnamese sources, performs sentiment analysis, and provides APIs for querying news data with Vietnamese stock market focus.

### Key Features
- ✅ **30+ Vietnamese news sources**: VnExpress, CafeF, Dân Trí, Money24h, etc.
- ✅ **Real-time news scraping**: Automated crawling with configurable intervals
- ✅ **Sentiment analysis**: Lexicon-based with learning system
- ✅ **FastAPI server**: RESTful API compatible with Alpha Vantage format
- ✅ **MCP Server**: FastMCP 2.0 integration for AI agents
- ✅ **SQLite database**: Efficient storage and querying
- ✅ **Multi-mode reporting**: Daily, Incremental, Current
- ✅ **Notification system**: Telegram, Email support
- ✅ **Docker support**: Easy deployment

### Integration with TradingAgents
This project serves as a **data vendor** for the parent TradingAgents project, specifically providing Vietnamese market news with sentiment scores for stock analysis.

---

## 📁 Critical File Locations

### Core System Files
```
trend_news/
├── server.py                     # ⭐ FastAPI server (port 8000)
│                                 # Alpha Vantage-compatible API
│
├── main.py                       # News scraping orchestrator
│                                 # Multi-mode operation (daily/incremental/current)
│
├── mcp_server/
│   ├── server.py                # FastMCP 2.0 server for AI agents
│   ├── tools/                   # MCP tool implementations
│   │   ├── data_query.py        # News querying tools
│   │   ├── analytics.py         # Analytics and statistics
│   │   ├── search_tools.py      # Search functionality
│   │   ├── config_mgmt.py       # Configuration management
│   │   └── system.py            # System management
│   ├── services/                # Business logic services
│   │   ├── cache_service.py     # Caching layer
│   │   ├── data_service.py      # Data access layer
│   │   └── parser_service.py    # Data parsing
│   └── utils/                   # Utilities
│       ├── date_parser.py       # Date parsing (Vietnamese format)
│       ├── errors.py            # Error handling
│       └── validators.py        # Input validation
│
├── src/
│   ├── config/
│   │   ├── settings.py          # Configuration loader
│   │   └── constants.py         # System constants
│   │
│   ├── core/
│   │   ├── database.py          # ⭐ SQLite database manager
│   │   ├── sentiment_learning.py # ⭐ Sentiment learning system
│   │   ├── analyzer.py          # Text analysis
│   │   ├── data_fetcher.py      # Generic data fetching
│   │   ├── vietnam_fetcher.py   # Vietnamese sources scraper
│   │   └── keyword_extractor.py # Keyword extraction
│   │
│   ├── scrapers/                # ⭐ Source-specific scrapers
│   │   ├── base_scraper.py      # Base scraper class
│   │   ├── vnexpress_scraper.py # VnExpress.net
│   │   ├── cafef_scraper.py     # CafeF.vn
│   │   ├── dantri_scraper.py    # Dân Trí
│   │   ├── money24h_scraper.py  # Money24h
│   │   └── ... (30+ total)
│   │
│   ├── processors/
│   │   ├── data_processor.py    # Data processing pipeline
│   │   ├── report_processor.py  # Report generation
│   │   └── statistics.py        # Statistics calculation
│   │
│   ├── renderers/
│   │   ├── html_renderer.py     # HTML report generation
│   │   └── telegram_renderer.py # Telegram formatting
│   │
│   ├── notifiers/
│   │   ├── telegram.py          # Telegram notifications
│   │   └── email.py             # Email notifications
│   │
│   └── utils/
│       ├── sentiment.py         # ⭐ Sentiment calculation
│       ├── text_utils.py        # Text processing
│       ├── time_utils.py        # Time handling
│       └── format_utils.py      # Formatting utilities
│
├── config/
│   ├── config.yaml              # ⭐ Main configuration file
│   └── frequency_words.txt      # Keywords for tracking
│
├── output/
│   ├── trend_news.db            # ⭐ SQLite database (news storage)
│   └── YYYY年MM月DD日/          # Daily output folders
│       ├── html/                # HTML reports
│       └── txt/                 # Text reports
│
└── docs/
    ├── IMPLEMENTATION_SUMMARY.md # Implementation details
    └── SENTIMENT_LEARNING.md     # Sentiment system documentation
```

### Entry Points
- **server.py** - FastAPI server for API access (port 8000)
- **main.py** - News scraping and processing
- **mcp_server/server.py** - MCP server for AI agent integration
- **sentiment_dashboard.py** - Web dashboard for sentiment visualization

---

## 🔄 System Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    NEWS SCRAPING LAYER                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  VnExpress   │  │    CafeF     │  │  Dân Trí     │     │
│  │   Scraper    │  │   Scraper    │  │   Scraper    │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                  │                  │              │
│         │  ┌──────────────────────┐          │              │
│         └──│  Money24h + 27 More  │──────────┘              │
│            │     Scrapers         │                          │
│            └──────────┬───────────┘                          │
│                       │                                      │
│              VietnamDataFetcher                             │
│                       │                                      │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                 PROCESSING LAYER                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              DataProcessor                           │  │
│  │  - Clean and normalize text                          │  │
│  │  - Extract keywords                                  │  │
│  │  - Detect duplicates                                 │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                      │
│                       ▼                                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         SentimentAnalyzer                            │  │
│  │  - Lexicon-based scoring                             │  │
│  │  - Context analysis                                  │  │
│  │  - Company/ticker detection                          │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                      │
│                       ▼                                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │      SentimentLearningManager                        │  │
│  │  - Learn from feedback                               │  │
│  │  - Update lexicon weights                            │  │
│  │  - Improve accuracy over time                        │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                      │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  STORAGE LAYER                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           DatabaseManager (SQLite)                   │  │
│  │                                                       │  │
│  │  Tables:                                             │  │
│  │  - news_articles: Scraped news with metadata        │  │
│  │  - sentiment_feedback: Learning data                │  │
│  │  - keyword_stats: Trending keywords                 │  │
│  │                                                       │  │
│  │  File: output/trend_news.db                         │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                      │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                    API LAYER                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │   FastAPI Server │         │    MCP Server    │         │
│  │   (port 8000)    │         │  (FastMCP 2.0)   │         │
│  │                  │         │                  │         │
│  │  Endpoints:      │         │  Tools:          │         │
│  │  - /query        │         │  - get_latest_news │       │
│  │  - /api/v1/news  │         │  - search_news   │         │
│  │  - /api/v1/stats │         │  - get_statistics│         │
│  │  - /health       │         │  - query_sentiment│         │
│  └──────┬───────────┘         └──────┬───────────┘         │
│         │                            │                      │
│         └──────────┬─────────────────┘                      │
│                    │                                         │
└────────────────────┼─────────────────────────────────────────┘
                     │
                     ▼
              ┌──────────────┐
              │   CLIENTS    │
              │              │
              │ - TradingAgents │
              │ - AI Agents  │
              │ - Web Apps   │
              └──────────────┘
```

### Three Operating Modes

**1. Daily Mode (Tổng hợp hàng ngày)**
- Collects ALL news from the day
- Generates comprehensive daily report
- Use case: End-of-day analysis

**2. Incremental Mode (Tăng dần)**
- Only NEW articles since last run
- Real-time updates
- Use case: Continuous monitoring

**3. Current Mode (Hiện tại)**
- Current trending topics
- Ranking-based view
- Use case: Quick market pulse check

---

## 🔌 API Integration

### FastAPI Server (server.py)

**Start Server:**
```bash
cd trend_news
python server.py
# Server runs on http://localhost:8000
```

**Endpoints:**

#### 1. Alpha Vantage Compatible Format
```bash
# Get news with sentiment
GET /query?function=NEWS_SENTIMENT&tickers=Vingroup&time_from=20260201T0000&time_to=20260215T0000&limit=50

# Response format (Alpha Vantage style)
{
  "items": "50",
  "sentiment_score_definition": "x <= -0.35: Bearish...",
  "feed": [
    {
      "title": "Vingroup công bố...",
      "url": "https://...",
      "time_published": "20260210T143000",
      "summary": "...",
      "source": "vnexpress_kinhdoanh",
      "overall_sentiment_score": 0.45,
      "overall_sentiment_label": "Bullish",
      "topics": ["Vingroup", "Vinfast"]
    }
  ]
}
```

#### 2. Native API Format
```bash
# Get news (native format)
GET /api/v1/news?start_date=2026-02-01&end_date=2026-02-15&limit=50&sources=vnexpress,cafef

# Get statistics
GET /api/v1/stats?days=7

# Get sentiment trends
GET /api/v1/sentiment/trends?ticker=Vingroup&days=30

# Health check
GET /health
```

#### 3. Markdown Format (for LLM consumption)
```python
# Internal function used by TradingAgents
from tradingagents.dataflows.trend_news_api import get_trend_news

news_md = get_trend_news("VIC.VN", "2026-02-01", "2026-02-15")
# Returns formatted markdown string
```

### MCP Server (mcp_server/server.py)

**Tools Available for AI Agents:**

```python
# 1. Data Query Tools
get_latest_news(platforms=["vnexpress", "cafef"], limit=50)
get_news_by_date(date="2026-02-15", platforms=None)
get_news_by_keyword(keyword="Vingroup", days_back=7)

# 2. Analytics Tools
get_statistics(days=7)
get_sentiment_trends(company="Vingroup", days=30)
get_top_keywords(days=7, top_n=20)

# 3. Search Tools
search_news(query="Vinfast mở rộng", exact_match=False)
find_related_news(article_id=12345, similarity_threshold=0.8)

# 4. Config Management
get_active_sources()
update_scraper_config(source_id="vnexpress", enabled=True)

# 5. System Management
trigger_scrape(sources=["vnexpress"], force=True)
get_system_health()
```

---

## 🇻🇳 Vietnamese Market Focus

### Ticker Mapping

The system maps Vietnamese stock tickers to company names for news matching:

```python
# Defined in tradingagents/dataflows/trend_news_api.py
VIETNAMESE_TICKER_MAP = {
    "VIC.VN": ["Vingroup", "Vinhomes"],
    "VNM.VN": ["Vinamilk"],
    "VCB.VN": ["Vietcombank", "BIDV"],  # Note: Smart matching
    "VHM.VN": ["Vinhomes"],
    "FPT.VN": ["FPT"],
    "HPG.VN": ["Hòa Phát", "Hoa Phat"],
    "TCB.VN": ["Techcombank"],
    "MSN.VN": ["Masan"],
    "VHC.VN": ["Vĩnh Hoàn"],
    "VRE.VN": ["Vincom Retail"],
    "GAS.VN": ["PV Gas"],
    "SAB.VN": ["Sabeco"],
    "PLX.VN": ["Petrolimex"],
    "POW.VN": ["PetroVietnam Power"],
    "MWG.VN": ["Mobile World", "Thế Giới Di Động"],
}
```

### News Sources (30+ total)

**Major Business Sources:**
- **VnExpress Kinh Doanh** (vnexpress_kinhdoanh)
- **CafeF** (cafef_congty, cafef_chungkhoan, cafef_batdongsan)
- **Dân Trí Kinh Doanh** (dantri_kinhdoanh)
- **Money24h** (money24h)
- **VietnamFinance** (vietnamfinance, vietnamfinance_taichinh, vietnamfinance_nganhang, vietnamfinance_batdongsan) ✨ NEW
- **Báo Đầu Tư** (baodautu)
- **Việt Stock** (vietstock)
- **CafeF Bất Động Sản** (cafef_batdongsan)

**General News Sources:**
- VnExpress (general news)
- Tuổi Trẻ
- Thanh Niên
- Zing News
- And 20+ more...

### Sentiment Analysis

**Lexicon-Based System:**
```python
# Basic sentiment calculation
sentiment_score = (positive_words - negative_words) / total_words

# Score ranges:
# x <= -0.35: Bearish
# -0.35 < x <= -0.15: Somewhat-Bearish
# -0.15 < x < 0.15: Neutral
# 0.15 <= x < 0.35: Somewhat-Bullish
# x >= 0.35: Bullish
```

**Learning System:**
The system learns from feedback to improve accuracy:

```python
from src.core.sentiment_learning import SentimentLearningManager

learning_mgr = SentimentLearningManager(db_path)

# Provide feedback
learning_mgr.record_feedback(
    article_id=123,
    predicted_sentiment=0.45,
    actual_sentiment=0.60,  # Corrected by analyst
    feedback_type="correction"
)

# System automatically adjusts lexicon weights
```

---

## 🛠 Adding New Features

### Adding a New News Source Scraper

**Example: Adding VietnamFinance scraper (recently added Feb 15, 2026)**

1. **Create scraper file:**
```python
# src/scrapers/vietnamfinance_scraper.py
from .base_scraper import BaseScraper
from typing import List, Dict
from bs4 import BeautifulSoup

class VietnamFinanceScraper(BaseScraper):
    """Scraper for VietnamFinance.vn"""
    
    BASE_URL = "https://vietnamfinance.vn"
    
    def __init__(self):
        super().__init__(
            source_id="vietnamfinance",
            source_name="VietnamFinance"
        )
    
    def get_url(self) -> str:
        return self.BASE_URL
    
    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """
        Parse articles from VietnamFinance.
        
        Returns:
            List of news items with keys:
            - title: str
            - url: str
            - mobileUrl: str (optional)
        """
        articles = []
        seen_urls = set()
        
        # CSS selectors for article titles
        selectors = ["h2 a", "h3 a", ".article-list a"]
        
        for selector in selectors:
            elements = soup.select(selector)
            for elem in elements:
                title = self._clean_title(elem.get_text())
                url = elem.get('href', '')
                
                if not title or len(title) < 10:
                    continue
                
                if not url.startswith('http'):
                    url = self._normalize_url(url, self.BASE_URL)
                
                if url and url not in seen_urls and '.html' in url:
                    seen_urls.add(url)
                    articles.append({
                        "title": title,
                        "url": url,
                        "mobileUrl": ""
                    })
        
        return articles[:50]
```

2. **Register in __init__.py:**
```python
# src/scrapers/__init__.py
from .vietnamfinance_scraper import (
    VietnamFinanceScraper,
    VietnamFinanceTaiChinhScraper,
    VietnamFinanceNganHangScraper,
    VietnamFinanceBatDongSanScraper,
)

VIETNAM_SCRAPERS = {
    # ... existing scrapers ...
    "vietnamfinance": VietnamFinanceScraper,
    "vietnamfinance-taichinh": VietnamFinanceTaiChinhScraper,
    "vietnamfinance-nganhang": VietnamFinanceNganHangScraper,
    "vietnamfinance-batdongsan": VietnamFinanceBatDongSanScraper,
}
```

3. **Test the scraper:**
```bash
# Test scraping
cd trend_news
python3 -c "
from src.scrapers.vietnamfinance_scraper import VietnamFinanceScraper
scraper = VietnamFinanceScraper()
result = scraper.fetch()
print(f'Fetched {len(result[\"items\"])} articles')
"
```

4. **Add to configuration (optional):**
```yaml
# config/config.yaml
platforms:
  - id: vietnamfinance
    name: VietnamFinance
    enabled: true
    priority: 8  # Higher = more important
```

### Adding New Sentiment Analysis Features

1. **Extend sentiment calculator:**
```python
# src/utils/sentiment.py

def get_sentiment_with_context(text: str, company: str) -> Dict:
    """
    Enhanced sentiment with company-specific context.
    """
    base_sentiment = get_sentiment(text)
    
    # Add company-specific adjustments
    if company.lower() in text.lower():
        # Adjust based on context
        context_boost = analyze_context(text, company)
        base_sentiment += context_boost
    
    return {
        "score": base_sentiment,
        "label": sentiment_to_label(base_sentiment),
        "confidence": calculate_confidence(text)
    }
```

2. **Update learning system:**
```python
# src/core/sentiment_learning.py

class SentimentLearningManager:
    def train_from_historical_data(self, feedback_data: List[Dict]):
        """
        Train model from historical feedback.
        """
        for feedback in feedback_data:
            self._update_weights(
                feedback['text'],
                feedback['predicted'],
                feedback['actual']
            )
```

### Adding New API Endpoints

1. **Add endpoint to server.py:**
```python
# server.py

@app.get("/api/v1/sentiment/company/{ticker}")
async def get_company_sentiment(
    ticker: str,
    days: int = 7
) -> Dict:
    """
    Get aggregated sentiment for a company.
    """
    # Get company names from ticker
    companies = VIETNAMESE_TICKER_MAP.get(ticker, [ticker])
    
    # Query news
    news_items = db_manager.get_news_by_companies(
        companies=companies,
        days_back=days
    )
    
    # Calculate aggregate sentiment
    avg_sentiment = calculate_aggregate_sentiment(news_items)
    
    return {
        "ticker": ticker,
        "sentiment_score": avg_sentiment,
        "article_count": len(news_items),
        "period_days": days
    }
```

2. **Add MCP tool:**
```python
# mcp_server/tools/analytics.py

@mcp.tool
async def analyze_company_sentiment(
    ticker: str,
    days: int = 7
) -> str:
    """
    Analyze sentiment for a specific company over time.
    """
    data = _get_tools()['analytics'].get_company_sentiment(ticker, days)
    return format_sentiment_report(data)
```

---

## 🧪 Testing and Debugging

### Quick Tests

```bash
# 1. Test database connection
cd trend_news
python3 -c "from src.core.database import DatabaseManager; db = DatabaseManager('output/trend_news.db'); print(f'DB has {db.count_articles()} articles')"

# 2. Test server
python server.py &
sleep 2
curl -s "http://localhost:8000/health" | python3 -m json.tool

# 3. Test scraping
python3 -c "from src.core.vietnam_fetcher import VietnamDataFetcher; fetcher = VietnamDataFetcher(); print(f'Loaded {len(fetcher.scrapers)} scrapers')"

# 4. Test sentiment
python3 -c "from src.utils.sentiment import get_sentiment; print(get_sentiment('Vingroup công bố kế hoạch tăng trưởng mạnh'))"

# 5. Test MCP server
cd mcp_server
python server.py
```

### Integration Test

```bash
# Run comprehensive integration test
cd trend_news
./tests/integration_test.sh

# Or run specific test
python -m pytest tests/test_server.py -v
```

### Debug Mode

**Enable debug logging:**
```python
# In any script
import logging
logging.basicConfig(level=logging.DEBUG)
```

**Debug database queries:**
```python
from src.core.database import DatabaseManager

db = DatabaseManager('output/trend_news.db')
db.debug = True  # Prints all SQL queries
```

### Common Issues

**Issue**: `Error: Database is locked`
```bash
# Solution: Check for other processes using the database
lsof | grep trend_news.db
# Kill blocking processes
kill -9 <PID>
```

**Issue**: `ImportError: No module named 'beautifulsoup4'`
```bash
# Solution: Install scraping dependencies
pip install beautifulsoup4 lxml requests
```

**Issue**: `Server returns 404 for /query`
```bash
# Solution: Check server is running
ps aux | grep "python.*server.py"
# Restart if needed
cd trend_news && python server.py &
```

**Issue**: `No news found for ticker VIC.VN`
```bash
# Solution: Check ticker mapping
python3 -c "from tradingagents.dataflows.trend_news_api import VIETNAMESE_TICKER_MAP; print(VIETNAMESE_TICKER_MAP.get('VIC.VN'))"

# Verify database has data
python3 -c "from src.core.database import DatabaseManager; db = DatabaseManager('output/trend_news.db'); print(db.search_by_keyword('Vingroup', limit=5))"
```

**Issue**: `Scraper timeout errors`
```bash
# Solution: Increase timeout in config
# Edit config/config.yaml:
scraper_settings:
  timeout: 30  # seconds
  retry_count: 3
```

---

## 📊 Configuration

### Main Config File (config/config.yaml)

```yaml
# Report mode: daily | incremental | current
report_mode: daily

# Database settings
database:
  path: output/trend_news.db
  auto_vacuum: true

# Scraper settings
scraper_settings:
  timeout: 15
  user_agent: "Mozilla/5.0..."
  retry_count: 2
  delay_between_requests: 1  # seconds

# Platforms to scrape
platforms:
  - id: vnexpress_kinhdoanh
    name: VnExpress Kinh Doanh
    enabled: true
    priority: 10
    
  - id: cafef_chungkhoan
    name: CafeF Chứng Khoán
    enabled: true
    priority: 9

# Sentiment settings
sentiment:
  lexicon_path: config/sentiment_lexicon.txt
  learning_enabled: true
  min_confidence: 0.5

# API settings
api:
  host: 0.0.0.0
  port: 8000
  cors_enabled: true
  rate_limit: 100  # requests per minute

# Notification settings (optional)
telegram:
  enabled: false
  bot_token: ""
  chat_id: ""

email:
  enabled: false
  smtp_server: smtp.gmail.com
  smtp_port: 587
  from_email: ""
  to_email: ""
```

### Keywords File (config/frequency_words.txt)

```text
# Add keywords to track (one per line)
Vingroup
Vinamilk
Vietcombank
Hòa Phát
FPT
# Stock market terms
cổ phiếu
chứng khoán
đầu tư
tăng trưởng
sáp nhập
```

---

## 🔑 Key Design Principles

### 1. **Modular Architecture**
- Each scraper is independent
- Easy to add/remove sources
- Clean separation of concerns

### 2. **Fail-Safe Design**
- Graceful degradation if scraper fails
- Continues with other sources
- Logs errors but doesn't crash

### 3. **Performance Optimized**
- Database indexing for fast queries
- Caching frequently accessed data
- Async scraping where possible

### 4. **Learning System**
- Improves accuracy over time
- Adapts to Vietnamese language nuances
- User feedback integration

### 5. **API Compatibility**
- Alpha Vantage format for easy integration
- Native format for advanced features
- Markdown format for LLM consumption

---

## 🚀 Quick Start for AI Assistants

When helping with this project:

1. **Check if server is running**: `curl http://localhost:8000/health`
2. **Verify database exists**: `ls -lh trend_news/output/trend_news.db`
3. **Test scraper**: Check `src/scrapers/` for source-specific code
4. **Review config**: `config/config.yaml` for all settings
5. **Check logs**: Look in `output/` directory for error logs

### Common Tasks

**"Add support for a new Vietnamese news source"**
→ Create scraper in `src/scrapers/`, register in `vietnam_fetcher.py`, add to config

**"Fix sentiment analysis for specific company"**
→ Check `src/utils/sentiment.py`, update lexicon, provide feedback data

**"Add new API endpoint"**
→ Modify `server.py`, add to MCP tools if needed

**"Improve scraping speed"**
→ Check `scraper_settings` in config, implement async scraping, add caching

**"Debug why no news for certain ticker"**
→ Check ticker mapping, verify database has data, test scraper directly

---

## 📚 Additional Resources

### Related Files
- **README.md** - User documentation
- **docs/IMPLEMENTATION_SUMMARY.md** - Technical implementation details
- **docs/SENTIMENT_LEARNING.md** - Sentiment system documentation
- **requirements.txt** - Python dependencies

### External Dependencies
- **FastAPI** - Web framework
- **FastMCP 2.0** - MCP server framework
- **BeautifulSoup4** - HTML parsing
- **SQLite** - Database
- **Uvicorn** - ASGI server

### Integration Points
- **TradingAgents** - Parent project using this as data vendor
- **Alpha Vantage API** - Compatible format for easy integration
- **MCP Protocol** - AI agent communication

---

## 🔄 Recent Changes (February 15, 2026)

### Integration with TradingAgents
- ✅ Created `tradingagents/dataflows/trend_news_api.py` integration
- ✅ Added Vietnamese ticker mapping (VIC.VN, VNM.VN, etc.)
- ✅ Implemented Alpha Vantage-compatible API format
- ✅ Added markdown formatting for LLM consumption
- ✅ Created sentiment score conversion

### New Features
- ✅ MCP Server with FastMCP 2.0
- ✅ Sentiment learning system
- ✅ Multi-mode reporting (daily/incremental/current)
- ✅ 30+ Vietnamese news sources
- ✅ Company-specific sentiment tracking
- ✅ **VietnamFinance scraper** - Added support for vietnamfinance.vn with 4 sections (homepage, tài chính, ngân hàng, bất động sản)

### Configuration Changes
```python
# In TradingAgents default_config.py
config["data_vendors"]["news_data"] = "trend_news"
config["trend_news_api_url"] = "http://localhost:8000"
config["trend_news_sources"] = []  # All sources by default
```

---

## 💡 Tips for AI Assistants

1. **Always check server status** before debugging API issues
2. **Test scrapers individually** before running full pipeline
3. **Use debug logging** to trace sentiment calculation issues
4. **Check database directly** when news queries return empty
5. **Verify ticker mapping** for Vietnamese stocks (VIC.VN format)
6. **Test with Vietnamese text** - encoding matters!
7. **Use MCP tools** for AI agent integration, not direct API calls
8. **Check config.yaml first** - most behavior is configurable
9. **Review scraper logs** in output/ directory for errors
10. **Use integration tests** to verify end-to-end functionality

---

## 🎯 Project Goals

### Short-term
- ✅ Stable scraping from 30+ sources
- ✅ Accurate sentiment analysis
- ✅ Fast API response times (<100ms)
- ✅ Integration with TradingAgents

### Long-term
- 🔄 Machine learning-based sentiment (beyond lexicon)
- 🔄 Real-time streaming API
- 🔄 Multi-language support (English translations)
- 🔄 Advanced analytics dashboard
- 🔄 Historical trend analysis

---

**Project**: TrendRadar (trend_news)  
**Parent**: TradingAgents  
**Repository**: phanngoc/agent-trading  
**Made by**: phanngoc  
**License**: MIT  
**Contact**: Check repository for issues and discussions

---

## 📍 Quick Reference

### Start Server
```bash
cd trend_news && python server.py
```

### Query News via API
```bash
curl "http://localhost:8000/query?function=NEWS_SENTIMENT&tickers=Vingroup&limit=10"
```

### Run Scraper
```bash
cd trend_news && python main.py
```

### Check Database
```bash
sqlite3 output/trend_news.db "SELECT COUNT(*) FROM news_articles;"
```

### Test Integration
```bash
cd .. && python -c "from tradingagents.dataflows.trend_news_api import get_trend_news; print(get_trend_news('VIC.VN', '2026-02-01', '2026-02-15'))"
```

**End of Guide** ✨

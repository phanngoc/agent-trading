"""
TrendRadar Production API Server

Standards:
  - FastAPI + Pydantic v2 strict models
  - Alpha Vantage-compatible /query endpoint (NEWS_SENTIMENT)
  - Native /api/v1/* endpoints for trading agents
  - /api/v2/intel/* endpoints for WorldMonitor global intel
  - /health + /metrics endpoints
  - API key auth (X-API-Key header or ?apikey= param)
  - Rate limiting per key (token bucket)
  - Structured error responses (RFC 7807)

Trading agent data quality:
  - Sentiment score: pre-computed (batch) with on-the-fly fallback
  - Confidence score exposed
  - Ticker-level aggregated sentiment
  - Global threat level + geo_relevance for market context
  - WM cross-reference (Iran war → oil → VN market signal)
"""

from __future__ import annotations

import os
import time
import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Optional, Tuple, Any

import asyncio
import json
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Header, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from src.core.database import DatabaseManager
from src.utils.sentiment import get_sentiment
from src.core.sentiment_learning import SentimentLearningManager
from src.core.keyword_extractor import KeywordExtractor
from src.core.ticker_mapper import TICKER_ALIASES
from src.core.sector_mapper import SECTOR_TICKERS, SECTOR_DISPLAY, TICKER_SECTOR, all_sectors

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "output", "trend_news.db")
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join("output", "trend_news.db")

API_KEYS = set(filter(None, os.environ.get("TRENDRADAR_API_KEYS", "dev-key").split(",")))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("TRENDRADAR_RATE_LIMIT", "60"))

_rate_buckets: Dict[str, List[float]] = {}

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TrendRadar API",
    description="Production news intelligence API for Vietnamese market + global context (WorldMonitor)",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

db_manager = DatabaseManager(DB_PATH)

# WebSocket signal broadcaster
from src.core.signal_broadcaster import manager as ws_manager, SignalWatcher
_signal_watcher = SignalWatcher(DB_PATH)

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    asyncio.create_task(_signal_watcher.run())
    yield
    _signal_watcher.stop()

# attach lifespan after defining it
app.router.lifespan_context = _lifespan
learning_manager = SentimentLearningManager(DB_PATH)
keyword_extractor = KeywordExtractor(DB_PATH)

# ── Auth + Rate limiting ──────────────────────────────────────────────────────

def _check_rate_limit(api_key: str) -> bool:
    now = time.time()
    window = _rate_buckets.setdefault(api_key, [])
    # Remove requests older than 60s
    _rate_buckets[api_key] = [t for t in window if now - t < 60]
    if len(_rate_buckets[api_key]) >= RATE_LIMIT_PER_MINUTE:
        return False
    _rate_buckets[api_key].append(now)
    return True

def get_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    apikey: Optional[str] = Query(None),
) -> str:
    key = x_api_key or apikey or ""
    # Dev mode: no keys configured → allow all
    if API_KEYS == {"dev-key"}:
        return key or "dev"
    if key not in API_KEYS:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Invalid or missing API key"},
        )
    if not _check_rate_limit(key):
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": f"Max {RATE_LIMIT_PER_MINUTE} req/min"},
        )
    return key

# ── Sentiment helpers ─────────────────────────────────────────────────────────

def _sentiment_label_to_score(label: str) -> float:
    """Map label → canonical score for Alpha Vantage compatibility."""
    mapping = {
        "Bullish": 0.5, "bullish": 0.5,
        "Somewhat-Bullish": 0.25, "somewhat_bullish": 0.25,
        "Neutral": 0.0, "neutral": 0.0,
        "Somewhat-Bearish": -0.25, "somewhat_bearish": -0.25,
        "Bearish": -0.5, "bearish": -0.5,
    }
    return mapping.get(label, 0.0)

def _score_to_av_label(score: float) -> str:
    """Alpha Vantage standard sentiment label from score."""
    if score <= -0.50: return "Bearish"
    if score <= -0.20: return "Somewhat-Bearish"
    if score <   0.20: return "Neutral"
    if score <   0.40: return "Somewhat-Bullish"
    return "Bullish"

def _resolve_sentiment(item: Dict) -> Tuple[float, str, float]:
    """Returns (score, label, confidence). Uses pre-computed if available."""
    db_score = item.get("sentiment_score")
    db_label = item.get("sentiment_label")
    if db_score is not None and db_label is not None:
        return float(db_score), db_label, 0.85  # batch-computed = high confidence
    score, label = get_sentiment(item.get("title", ""))
    return score, label, 0.50  # on-the-fly = lower confidence

def _source_domain(source_id: str) -> str:
    domains = {
        "cafef": "cafef.vn", "vnexpress-kinhdoanh": "vnexpress.net",
        "vneconomy-chungkhoan": "vneconomy.vn", "tinnhanhchungkhoan": "tinnhanhchungkhoan.vn",
        "24hmoney": "24hmoney.vn", "vietnamfinance": "vietnamfinance.vn",
        "wallstreetcn-hot": "wallstreetcn.com", "hackernews": "news.ycombinator.com",
    }
    return domains.get(source_id, f"{source_id}.com")

# ── Pydantic models ───────────────────────────────────────────────────────────

class NewsItem(BaseModel):
    title: str
    url: str
    time_published: str          # ISO 8601: 2026-03-22T15:30:00
    source: str
    source_domain: str
    summary: str = ""
    topics: List[str] = []
    overall_sentiment_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    overall_sentiment_label: str = "Neutral"
    sentiment_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.5)
    # Trading agent extensions
    threat_level: Optional[str] = None       # critical/high/medium/low/info
    market_signal: Optional[str] = None      # bullish/bearish/neutral
    geo_relevance: Optional[float] = None    # 0.0-1.0 (VN relevance)
    global_context: List[str] = []          # related WM headlines


class NewsSentimentResponse(BaseModel):
    items: str
    sentiment_score_definition: str = (
        "x <= -0.50: Bearish; -0.50 < x <= -0.20: Somewhat-Bearish; "
        "-0.20 < x < 0.20: Neutral; 0.20 <= x < 0.40: Somewhat-Bullish; x >= 0.40: Bullish"
    )
    relevance_score_definition: str = "0.0–1.0: higher = more relevant to query"
    feed: List[NewsItem]


class TickerSentimentItem(BaseModel):
    ticker: str
    company_name: str
    article_count: int
    avg_sentiment_score: float
    sentiment_label: str
    bullish_count: int
    bearish_count: int
    neutral_count: int
    top_headlines: List[str]
    threat_level: Optional[str] = None      # from WM global context
    market_signal: Optional[str] = None
    last_updated: str


class GlobalIntelItem(BaseModel):
    title: str
    source_name: str
    url: str
    wm_category: str
    threat_level: str
    threat_category: str
    geo_relevance: float
    published_at: Optional[int]
    crawl_date: str


class GlobalIntelResponse(BaseModel):
    date: str
    total: int
    by_category: Dict[str, int]
    by_threat: Dict[str, int]
    items: List[GlobalIntelItem]


class PipelineStatus(BaseModel):
    status: str
    db_path: str
    news_articles_total: int
    wm_articles_total: int
    news_today: int
    wm_today: int
    last_updated: str
    providers: Dict[str, Any]


class SentimentFeedback(BaseModel):
    news_title: str
    predicted_score: float
    predicted_label: str
    user_score: float
    user_label: str
    news_id: Optional[int] = None
    news_url: Optional[str] = None
    comment: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return {"service": "TrendRadar API", "version": "2.0.0", "docs": "/docs"}


@app.get("/health", tags=["Ops"])
def health():
    """Health check — returns 200 if DB accessible."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "connected", "timestamp": datetime.utcnow().isoformat() + "Z"}
    except Exception as e:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "error": str(e)})


@app.get("/metrics", tags=["Ops"])
def metrics(api_key: str = Depends(get_api_key)):
    """Pipeline metrics for monitoring."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.utcnow().date().isoformat()

    def count(table, where="1=1"):
        try:
            c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}")
            return c.fetchone()[0]
        except: return 0

    result = {
        "news_articles": {
            "total": count("news_articles"),
            "today": count("news_articles", f"crawl_date='{today}'"),
            "unscored": count("news_articles", "sentiment_score IS NULL"),
        },
        "wm_articles": {
            "total": count("wm_articles"),
            "today": count("wm_articles", f"crawl_date='{today}'"),
            "critical": count("wm_articles", f"threat_level='critical' AND crawl_date='{today}'"),
            "high": count("wm_articles", f"threat_level='high' AND crawl_date='{today}'"),
        },
        "sentiment_feedback": {"total": count("sentiment_feedback")},
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    conn.close()
    return result


# ── Alpha Vantage Compatible ──────────────────────────────────────────────────

@app.get("/query", response_model=NewsSentimentResponse, tags=["Alpha Vantage Compatible"])
def get_news_sentiment(
    function: str = Query(...),
    tickers: Optional[str] = Query(None),
    topics: Optional[str] = Query(None),
    time_from: Optional[str] = Query(None),
    time_to: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    sort: str = Query("LATEST", pattern="^(LATEST|EARLIEST|RELEVANCE)$"),
    api_key: str = Depends(get_api_key),
):
    """Alpha Vantage NEWS_SENTIMENT compatible endpoint."""
    if function != "NEWS_SENTIMENT":
        raise HTTPException(status_code=400, detail={
            "code": "UNSUPPORTED_FUNCTION",
            "message": f"Function '{function}' not supported. Use NEWS_SENTIMENT.",
        })

    def _parse_av_time(s: str) -> Optional[str]:
        for fmt in ("%Y%m%dT%H%M", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt).isoformat()
            except ValueError:
                pass
        return None

    raw = db_manager.get_filtered_news(
        start_date=_parse_av_time(time_from) if time_from else None,
        end_date=_parse_av_time(time_to) if time_to else None,
        tickers=tickers,
        limit=limit,
    )

    feed = []
    for item in raw:
        score, label, confidence = _resolve_sentiment(item)
        crawled = item.get("crawled_at", "")
        # Normalize to ISO 8601
        try:
            ts = datetime.fromisoformat(crawled).strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            ts = crawled[:19] if len(crawled) >= 19 else crawled

        feed.append(NewsItem(
            title=item.get("title", ""),
            url=item.get("url", ""),
            time_published=ts,
            source=item.get("source_id", ""),
            source_domain=_source_domain(item.get("source_id", "")),
            summary=item.get("title", ""),
            topics=[topics] if topics else [],
            overall_sentiment_score=round(score, 4),
            overall_sentiment_label=label,
            sentiment_confidence=round(confidence, 2),
            relevance_score=0.8 if tickers else 0.5,
            threat_level=item.get("threat_level"),
            market_signal=item.get("market_signal"),
            geo_relevance=item.get("geo_relevance"),
        ))

    return NewsSentimentResponse(items=str(len(feed)), feed=feed)


# ── Native v1 ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/news", tags=["Native v1"])
def get_news(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: Optional[str] = None,
    tickers: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    api_key: str = Depends(get_api_key),
):
    """Get news with optional filters. Returns enriched articles."""
    return db_manager.get_filtered_news(
        start_date=start_date,
        end_date=end_date,
        source_id=source,
        tickers=tickers,
        limit=limit,
    )


@app.get("/api/v1/tickers/{ticker}", response_model=TickerSentimentItem, tags=["Native v1"])
def get_ticker_sentiment(
    ticker: str,
    days_back: int = Query(7, ge=1, le=30),
    api_key: str = Depends(get_api_key),
):
    """
    Aggregated sentiment for a single VN stock ticker.

    Returns article count, avg sentiment, bull/bear breakdown,
    top headlines, and WM global threat context.
    """
    ticker = ticker.upper()
    aliases = TICKER_ALIASES.get(ticker)
    if not aliases:
        raise HTTPException(status_code=404, detail={
            "code": "TICKER_NOT_FOUND",
            "message": f"Ticker '{ticker}' not in alias map",
        })

    company_name = aliases[0]
    start = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()

    # Fetch articles matching this ticker's aliases
    articles = db_manager.get_filtered_news(
        start_date=start, tickers=ticker, limit=200
    )

    if not articles:
        return TickerSentimentItem(
            ticker=ticker,
            company_name=company_name,
            article_count=0,
            avg_sentiment_score=0.0,
            sentiment_label="Neutral",
            bullish_count=0, bearish_count=0, neutral_count=0,
            top_headlines=[],
            last_updated=datetime.utcnow().isoformat() + "Z",
        )

    scores, bull, bear, neutral_c = [], 0, 0, 0
    for a in articles:
        score, label, _ = _resolve_sentiment(a)
        scores.append(score)
        if score >= 0.20: bull += 1
        elif score <= -0.20: bear += 1
        else: neutral_c += 1

    avg = round(sum(scores) / len(scores), 4)

    # WM context: any critical/high global events affecting this ticker?
    wm_today = db_manager.get_wm_articles(
        threat_levels=["critical", "high"],
        limit=20,
    )
    wm_signal = "neutral"
    wm_threat = "info"
    if wm_today:
        # Check if any WM article is relevant to this ticker's sector
        # (simple: if ticker is bank/finance, match finance WM; energy → oil WM)
        sector_map = {
            "finance": ["VCB","BID","CTG","TCB","MBB","VPB","ACB","HDB","STB","TPB","VIB","OCB","MSB"],
            "energy":  ["PLX","GAS","PVS","PVD","BSR","OIL","PVC"],
            "real_estate": ["VIC","VHM","NVL","PDR","KDH","DXG"],
        }
        ticker_sector = next((s for s, tks in sector_map.items() if ticker in tks), None)
        finance_wm = [a for a in wm_today if a.get("wm_category") == "finance"]
        if finance_wm and ticker_sector in ("finance", "energy"):
            wm_threat = max(a.get("threat_level","info") for a in finance_wm)
            bearish_finance = sum(1 for a in finance_wm
                                  if any(w in a.get("title","").lower()
                                         for w in ["crash","fall","drop","decline","war","sanction","recession"]))
            wm_signal = "bearish" if bearish_finance > len(finance_wm) // 2 else "neutral"

    return TickerSentimentItem(
        ticker=ticker,
        company_name=company_name,
        article_count=len(articles),
        avg_sentiment_score=avg,
        sentiment_label=_score_to_av_label(avg),
        bullish_count=bull,
        bearish_count=bear,
        neutral_count=neutral_c,
        top_headlines=[a.get("title","") for a in articles[:5]],
        threat_level=wm_threat,
        market_signal=wm_signal,
        last_updated=datetime.utcnow().isoformat() + "Z",
    )


@app.get("/api/v1/market/summary", tags=["Native v1"])
def get_market_summary(
    days_back: int = Query(1, ge=1, le=7),
    api_key: str = Depends(get_api_key),
):
    """
    Market-level sentiment summary (VN market + global context).

    Returns overall VN market mood + top WM global threats affecting VN.
    """
    start = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()
    articles = db_manager.get_filtered_news(start_date=start, limit=500)

    total = len(articles)
    if not total:
        return {"status": "no_data", "date": start}

    scores = []
    for a in articles:
        score, _, _ = _resolve_sentiment(a)
        scores.append(score)

    avg = round(sum(scores) / len(scores), 4) if scores else 0.0
    bull = sum(1 for s in scores if s >= 0.20)
    bear = sum(1 for s in scores if s <= -0.20)

    # WM global threats
    wm_stats = db_manager.get_wm_stats()
    high_geo = wm_stats.get("high_geo_relevance", [])
    critical_count = wm_stats.get("by_threat", {}).get("critical", 0)
    high_count = wm_stats.get("by_threat", {}).get("high", 0)

    global_risk = "HIGH" if critical_count >= 5 else "MEDIUM" if critical_count >= 2 else "LOW"

    return {
        "date": start,
        "vn_market": {
            "article_count": total,
            "avg_sentiment_score": avg,
            "sentiment_label": _score_to_av_label(avg),
            "bullish_pct": round(bull / total * 100, 1),
            "bearish_pct": round(bear / total * 100, 1),
        },
        "global_risk": {
            "level": global_risk,
            "critical_events": critical_count,
            "high_events": high_count,
            "vn_relevant": [
                {
                    "title": a.get("title",""),
                    "source": a.get("source",""),
                    "threat": a.get("threat",""),
                    "geo_relevance": a.get("geo",""),
                }
                for a in high_geo[:5]
            ],
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ── WorldMonitor intel v2 ─────────────────────────────────────────────────────

@app.get("/api/v2/intel", response_model=GlobalIntelResponse, tags=["Global Intel v2"])
def get_global_intel(
    date: Optional[str] = Query(None, description="YYYY-MM-DD, default today"),
    category: Optional[str] = Query(None, description="asia|vietnam|finance|geopolitical|tech"),
    threat: Optional[str] = Query(None, description="critical|high|medium|low|info"),
    limit: int = Query(50, ge=1, le=200),
    api_key: str = Depends(get_api_key),
):
    """WorldMonitor global intelligence articles with threat classification."""
    if date is None:
        date = datetime.utcnow().date().isoformat()

    threat_filter = [threat] if threat else None
    articles = db_manager.get_wm_articles(
        crawl_date=date,
        category=category,
        threat_levels=threat_filter,
        limit=limit,
    )
    stats = db_manager.get_wm_stats(crawl_date=date)

    return GlobalIntelResponse(
        date=date,
        total=stats.get("total", 0),
        by_category=stats.get("by_category", {}),
        by_threat=stats.get("by_threat", {}),
        items=[GlobalIntelItem(**a) for a in articles],
    )


@app.get("/api/v2/intel/search", tags=["Global Intel v2"])
def search_intel(
    q: str = Query(..., min_length=2, description="Search query (FTS5)"),
    limit: int = Query(20, ge=1, le=100),
    api_key: str = Depends(get_api_key),
):
    """Full-text search across WorldMonitor global intel articles."""
    results = db_manager.search_wm_articles(q, limit=limit)
    return {"query": q, "count": len(results), "results": results}


@app.get("/api/v2/intel/threat-summary", tags=["Global Intel v2"])
def get_threat_summary(
    days_back: int = Query(3, ge=1, le=30),
    api_key: str = Depends(get_api_key),
):
    """
    Aggregated threat summary for the past N days.
    Useful for trading agents to assess macro risk environment.
    """
    results = []
    for d in range(days_back):
        date = (datetime.utcnow() - timedelta(days=d)).date().isoformat()
        stats = db_manager.get_wm_stats(crawl_date=date)
        if stats.get("total", 0) > 0:
            results.append({
                "date": date,
                "total": stats["total"],
                "by_threat": stats.get("by_threat", {}),
                "by_category": stats.get("by_category", {}),
                "high_geo": [
                    {"title": a.get("title",""), "threat": a.get("threat","")}
                    for a in stats.get("high_geo_relevance", [])[:3]
                ],
            })
    return {"days_back": days_back, "summary": results}


# ── Sentiment learning ────────────────────────────────────────────────────────

@app.post("/api/v1/feedback", tags=["Sentiment Learning"])
def add_feedback(feedback: SentimentFeedback, api_key: str = Depends(get_api_key)):
    """Submit sentiment label correction to improve the model."""
    try:
        fid = learning_manager.add_feedback(
            news_title=feedback.news_title,
            predicted_score=feedback.predicted_score,
            predicted_label=feedback.predicted_label,
            user_score=feedback.user_score,
            user_label=feedback.user_label,
            news_id=feedback.news_id,
            news_url=feedback.news_url,
            comment=feedback.comment,
        )
        return {"success": True, "feedback_id": fid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/feedback/stats", tags=["Sentiment Learning"])
def feedback_stats(days: int = 7, api_key: str = Depends(get_api_key)):
    return learning_manager.get_feedback_stats(days=days)


@app.get("/api/v1/keywords/suggestions", tags=["Sentiment Learning"])
def keyword_suggestions(
    days: int = 30,
    min_frequency: int = 3,
    limit: int = 50,
    api_key: str = Depends(get_api_key),
):
    patterns = keyword_extractor.analyze_sentiment_patterns(
        days=days, min_frequency=min_frequency
    )
    return {"positive": patterns["positive"][:limit], "negative": patterns["negative"][:limit]}


@app.get("/api/v1/lexicon/combined", tags=["Sentiment Learning"])
def combined_lexicon(api_key: str = Depends(get_api_key)):
    auto_kw = learning_manager.get_auto_aggregated_keywords(
        min_confidence=0.3, min_frequency=2, lookback_days=30
    )
    return auto_kw




# ── API v2: Batch + Sectors + Heatmap ────────────────────────────────────────

class TickerBatchRequest(BaseModel):
    tickers: List[str] = Field(..., min_length=1, max_length=30)
    days_back: int = Field(7, ge=1, le=30)


@app.post("/api/v2/tickers/batch", tags=["Native v2"])
def get_batch_ticker_sentiment(
    body: TickerBatchRequest,
    api_key: str = Depends(get_api_key),
):
    """
    Batch sentiment for multiple VN tickers in one call.
    Useful for portfolio-level analysis by trading agents.
    """
    from datetime import timedelta
    start = (datetime.utcnow() - timedelta(days=body.days_back)).date().isoformat()
    results = {}
    for ticker in [t.upper() for t in body.tickers]:
        aliases = TICKER_ALIASES.get(ticker)
        if not aliases:
            results[ticker] = {"error": "ticker_not_found"}
            continue
        articles = db_manager.get_filtered_news(start_date=start, tickers=ticker, limit=100)
        if not articles:
            results[ticker] = {
                "ticker": ticker, "company": aliases[0], "article_count": 0,
                "avg_sentiment_score": 0.0, "sentiment_label": "Neutral",
                "confidence": 0.3, "sector": TICKER_SECTOR.get(ticker),
            }
            continue
        scores = []
        for a in articles:
            score, label, conf = _resolve_sentiment(a)
            scores.append((score, conf))
        avg = round(sum(s*c for s,c in scores) / sum(c for _,c in scores), 4)
        conf = round(sum(c for _,c in scores) / len(scores), 2)
        results[ticker] = {
            "ticker": ticker,
            "company": aliases[0],
            "article_count": len(articles),
            "avg_sentiment_score": avg,
            "sentiment_label": _score_to_av_label(avg),
            "confidence": conf,
            "sector": TICKER_SECTOR.get(ticker),
            "top_headlines": [a.get("title","") for a in articles[:3]],
        }
    return {"tickers": results, "days_back": body.days_back,
            "timestamp": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/v2/sectors", tags=["Native v2"])
def list_sectors(api_key: str = Depends(get_api_key)):
    """List all available sectors with display names."""
    return {
        "sectors": [
            {"id": s, "name": SECTOR_DISPLAY.get(s, s), "ticker_count": len(SECTOR_TICKERS[s])}
            for s in all_sectors()
        ]
    }


@app.get("/api/v2/sectors/{sector}", tags=["Native v2"])
def get_sector_sentiment(
    sector: str,
    days_back: int = Query(7, ge=1, le=30),
    api_key: str = Depends(get_api_key),
):
    """
    Aggregated sentiment for all tickers in a sector.
    sector: banking|real_estate|energy|steel|tech|retail|food_beverage|
            aviation|securities|industrial|utilities|logistics
    """
    from datetime import timedelta
    tickers = SECTOR_TICKERS.get(sector.lower())
    if not tickers:
        raise HTTPException(status_code=404, detail={
            "code": "SECTOR_NOT_FOUND",
            "message": f"Sector '{sector}' not found. Use /api/v2/sectors to list available sectors.",
        })
    start = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()
    ticker_results = []
    scores = []
    for ticker in tickers:
        articles = db_manager.get_filtered_news(start_date=start, tickers=ticker, limit=50)
        if not articles:
            continue
        t_scores = []
        for a in articles:
            score, _, conf = _resolve_sentiment(a)
            t_scores.append((score, conf))
        avg = sum(s*c for s,c in t_scores) / sum(c for _,c in t_scores)
        scores.append(avg)
        ticker_results.append({
            "ticker": ticker,
            "company": TICKER_ALIASES.get(ticker, [ticker])[0],
            "score": round(avg, 4),
            "label": _score_to_av_label(avg),
            "article_count": len(articles),
        })
    if not scores:
        sector_avg, sector_label = 0.0, "Neutral"
    else:
        sector_avg = round(sum(scores)/len(scores), 4)
        sector_label = _score_to_av_label(sector_avg)
    bull = sum(1 for s in scores if s >= 0.20)
    bear = sum(1 for s in scores if s <= -0.20)
    neu  = len(scores) - bull - bear
    return {
        "sector": sector,
        "display_name": SECTOR_DISPLAY.get(sector, sector),
        "avg_sentiment_score": sector_avg,
        "sentiment_label": sector_label,
        "ticker_count": len(ticker_results),
        "bullish": bull, "bearish": bear, "neutral": neu,
        "tickers": sorted(ticker_results, key=lambda x: x["score"], reverse=True),
        "days_back": days_back,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/v2/market/heatmap", tags=["Native v2"])
def get_market_heatmap(
    days_back: int = Query(1, ge=1, le=7),
    api_key: str = Depends(get_api_key),
):
    """
    Full market heatmap: all tracked tickers color-coded by sentiment score.
    Returns scores grouped by sector for visual heatmap rendering.
    """
    from datetime import timedelta
    start = (datetime.utcnow() - timedelta(days=days_back)).date().isoformat()
    heatmap = {}
    for sector, tickers in SECTOR_TICKERS.items():
        sector_data = []
        for ticker in tickers:
            articles = db_manager.get_filtered_news(start_date=start, tickers=ticker, limit=30)
            if not articles:
                sector_data.append({
                    "ticker": ticker, "score": 0.0,
                    "label": "Neutral", "articles": 0
                })
                continue
            t_scores = [_resolve_sentiment(a)[0] for a in articles]
            avg = round(sum(t_scores)/len(t_scores), 4)
            sector_data.append({
                "ticker": ticker,
                "score": avg,
                "label": _score_to_av_label(avg),
                "articles": len(articles),
            })
        heatmap[sector] = {
            "display_name": SECTOR_DISPLAY.get(sector, sector),
            "tickers": sorted(sector_data, key=lambda x: x["score"], reverse=True),
        }
    return {
        "heatmap": heatmap,
        "days_back": days_back,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ── Intelligence Report endpoints ─────────────────────────────────────────────

@app.get("/api/v2/reports/latest", tags=["Intelligence Reports"])
def get_latest_report(api_key: str = Depends(get_api_key)):
    """Get the latest morning briefing report."""
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("""
            SELECT report_date, market_outlook, global_risk, market_score,
                   content_json, generated_at
            FROM reports
            ORDER BY report_date DESC, rowid DESC
            LIMIT 1
        """)
        row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={
                "code": "NO_REPORT", "message": "No reports generated yet. Run the intelligence agent."
            })
        cols = ["report_date","market_outlook","global_risk","market_score","content_json","generated_at"]
        result = dict(zip(cols, row))
        result["content"] = json.loads(result.pop("content_json", "{}"))
        return result
    finally:
        conn.close()


@app.post("/api/v2/reports/generate", tags=["Intelligence Reports"])
def generate_report_now(
    watchlist: Optional[List[str]] = None,
    api_key: str = Depends(get_api_key),
):
    """
    Trigger on-demand morning brief generation.
    Watchlist defaults to VN30 core tickers.
    """
    from src.core.intelligence_agent import IntelligenceAgent
    agent = IntelligenceAgent(
        db_path=DB_PATH,
        groq_api_key=os.environ.get("GROQ_API_KEY",""),
    )
    report = agent.run_morning_brief(watchlist=watchlist)
    report_id = agent.save_report(report)
    return {
        "report_id": report_id,
        "report_date": report.report_date,
        "market_outlook": report.market_outlook,
        "global_risk": report.global_risk,
        "market_score": report.market_score,
        "top_picks": [{"ticker": t.ticker, "label": t.label, "score": t.score}
                      for t in report.top_picks[:5]],
        "risk_alerts": [{"ticker": t.ticker, "label": t.label, "score": t.score}
                        for t in report.risk_alerts[:3]],
        "synthesis": report.synthesis,
        "generated_at": report.generated_at,
    }


# ── WebSocket v3: Real-time signal streaming ──────────────────────────────────

@app.websocket("/api/v3/stream")
async def websocket_stream(
    websocket: WebSocket,
    tickers: str = Query("", description="Comma-separated tickers, e.g. VCB,HPG,GAS"),
    apikey: str = Query("", description="API key"),
):
    """
    Real-time ticker signal stream via WebSocket.

    Connect: ws://host/api/v3/stream?tickers=VCB,HPG&apikey=xxx

    Message types received:
      connected      — subscription confirmed
      signal_update  — score/label changed for a subscribed ticker
      intel_alert    — new WM critical/high global event
      market_update  — overall market score change (broadcast)
      ping           — keepalive every 30s

    Send "ping" text to get "pong" response.
    """
    # Auth check
    if API_KEYS != {"dev-key"} and apikey not in API_KEYS:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        ticker_list = ["VCB", "HPG", "VIC", "GAS", "VNM"]  # defaults

    await ws_manager.connect(websocket, ticker_list)
    try:
        # Send initial snapshot for each subscribed ticker
        for ticker in ticker_list:
            score, count, headline = _signal_watcher._compute_ticker_score(ticker)
            await websocket.send_text(json.dumps({
                "type": "snapshot",
                "ticker": ticker,
                "score": score,
                "label": _score_to_av_label(score),
                "article_count": count,
                "latest_headline": headline[:100] if headline else "",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }))

        # Keepalive + receive loop
        ping_counter = 0
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send server keepalive
                await websocket.send_text(json.dumps({
                    "type": "ping",
                    "clients": ws_manager.connected_count,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                }))
                ping_counter += 1
            except WebSocketDisconnect:
                break
    finally:
        ws_manager.disconnect(websocket)


@app.get("/api/v3/stream/stats", tags=["WebSocket v3"])
def ws_stats(api_key: str = Depends(get_api_key)):
    """WebSocket connection stats."""
    return {
        "connected_clients": ws_manager.connected_count,
        "subscriptions": {
            t: ws_manager.ticker_subscriber_count(t)
            for t in ws_manager._subscriptions
            if ws_manager.ticker_subscriber_count(t) > 0
        },
        "watcher_running": _signal_watcher._running,
    }

# ── Exception handlers ────────────────────────────────────────────────────────

@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    return JSONResponse(status_code=404, content={
        "code": "NOT_FOUND", "message": str(exc.detail), "path": str(request.url.path)
    })

@app.exception_handler(422)
async def validation_error(request: Request, exc):
    return JSONResponse(status_code=422, content={
        "code": "VALIDATION_ERROR", "message": "Invalid request parameters",
        "detail": exc.errors() if hasattr(exc, "errors") else str(exc),
    })


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False, workers=1)

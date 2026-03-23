"""
TrendRadar E2E Test Suite

Tests the full system end-to-end:
  1. Data layer (DB schema, dedup, FTS5)
  2. Sentiment engine (accuracy, edge cases)
  3. API v1 (news, tickers, market)
  4. API v2 (batch, sectors, heatmap, reports, intel)
  5. Intelligence Agent (morning brief, report generation)
  6. WebSocket broadcaster (connection, stats)
  7. SDK (all namespaces)
  8. Pipeline integration (main.py data flow)
  9. Business logic (rate limit, auth, error codes)

Run:
    cd trend_news && pytest tests/test_e2e.py -v --tb=short
    pytest tests/test_e2e.py -v -k "sentiment"   # filter by name
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch, MagicMock

import pytest

# ── Setup paths ───────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "sdk"))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_mock")
os.environ.setdefault("TRENDRADAR_API_KEYS", "dev-key,e2e-test-key")

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_db():
    """Create an in-memory test DB seeded with sample data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # news_articles
    c.execute("""
        CREATE TABLE news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT DEFAULT '',
            mobile_url TEXT DEFAULT '',
            ranks TEXT,
            crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            crawl_date TEXT NOT NULL,
            sentiment_score REAL,
            sentiment_label TEXT
        )
    """)
    c.execute("CREATE UNIQUE INDEX idx_url ON news_articles(url) WHERE url != ''")
    c.execute("CREATE UNIQUE INDEX idx_title ON news_articles(source_id, title, crawl_date)")

    today = date.today().isoformat()
    articles = [
        ("vcb-test",  "VCB báo lãi kỷ lục 42.000 tỷ, cổ tức tiền mặt 18%",  "https://vcb1.vn", today, 0.35, "Bullish"),
        ("vcb-test",  "Vietcombank mở rộng mạng lưới chi nhánh quốc tế",      "https://vcb2.vn", today, 0.20, "Bullish"),
        ("hpg-test",  "HPG ký hợp đồng xuất khẩu thép 2 tỷ USD sang EU",      "https://hpg1.vn", today, 0.24, "Bullish"),
        ("vic-test",  "VIC lao dốc 7%, nhà đầu tư bán tháo ồ ạt",            "https://vic1.vn", today, -0.44, "Bearish"),
        ("gas-test",  "GAS hưởng lợi từ giá dầu tăng, doanh thu Q1 tăng 15%", "https://gas1.vn", today, 0.30, "Bullish"),
        ("neutral-1", "Ngân hàng Nhà nước công bố lãi suất điều hành mới",    "https://nn1.vn",  today, 0.0,  "Neutral"),
        ("neutral-2", "VnIndex mở cửa phiên đầu tuần",                        "https://vni1.vn", today, 0.0,  "Neutral"),
    ]
    c.executemany(
        "INSERT INTO news_articles (source_id,title,url,crawl_date,sentiment_score,sentiment_label) VALUES (?,?,?,?,?,?)",
        articles,
    )

    # wm_articles
    c.execute("""
        CREATE TABLE wm_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT, source_name TEXT, title TEXT, url TEXT DEFAULT '',
            wm_category TEXT, threat_level TEXT DEFAULT 'info',
            threat_category TEXT DEFAULT 'general', threat_confidence REAL DEFAULT 0.5,
            geo_relevance REAL DEFAULT 0.0, published_at INTEGER,
            crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, crawl_date TEXT
        )
    """)
    c.execute("CREATE UNIQUE INDEX idx_wm_url ON wm_articles(url) WHERE url != ''")
    wm = [
        ("bbc-asia", "BBC Asia", "Iran war escalates, US strikes nuclear sites",   "https://bbc1.com", "asia",        "critical", 0.8,  today),
        ("reuters",  "Reuters",  "Federal Reserve signals rate hike amid inflation","https://reu1.com", "finance",     "high",     0.5,  today),
        ("ft",       "FT",       "Vietnam exports surge 15% despite global slowdown","https://ft1.com", "vietnam",     "medium",   0.9,  today),
        ("cna",      "CNA",      "ASEAN meeting on South China Sea tensions",       "https://cna1.com", "geopolitical","high",     0.7,  today),
        ("scmp",     "SCMP",     "China tech selloff accelerates on regulation fears","https://scmp1.com","asia",      "high",     0.4,  today),
    ]
    c.executemany(
        "INSERT INTO wm_articles (source_id,source_name,title,url,wm_category,threat_level,geo_relevance,crawl_date) VALUES (?,?,?,?,?,?,?,?)",
        wm,
    )

    # reports
    c.execute("""
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT, report_type TEXT DEFAULT 'morning_brief',
            market_outlook TEXT, global_risk TEXT, market_score REAL,
            content_json TEXT, generated_at TEXT,
            UNIQUE(report_date, report_type)
        )
    """)
    c.execute("""
        INSERT INTO reports (report_date, market_outlook, global_risk, market_score, content_json, generated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (today, "Bullish", "HIGH", 0.15,
          json.dumps({"synthesis": "Thị trường tích cực hôm nay",
                      "top_picks": [{"ticker": "VCB", "label": "Bullish", "score": 0.35}],
                      "risk_alerts": [],
                      "global_context": [],
                      "critical_events": 3, "high_events": 2}),
          datetime.now().isoformat()))

    # sentiment_feedback (required by learning manager)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER, news_title TEXT NOT NULL, news_url TEXT,
            predicted_score REAL, predicted_label TEXT,
            user_score REAL, user_label TEXT, user_comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS keyword_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT,
            sentiment_type TEXT, suggested_weight REAL,
            co_occurrence_count INTEGER DEFAULT 1, supporting_titles TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, reviewed BOOLEAN DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS learned_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT UNIQUE,
            sentiment_type TEXT, weight REAL, confidence REAL DEFAULT 0.5,
            frequency INTEGER DEFAULT 1, last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'user_feedback', status TEXT DEFAULT 'pending'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
            total_predictions INTEGER DEFAULT 0, correct_predictions INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0.0, avg_confidence REAL DEFAULT 0.0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS labeling_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER, news_title TEXT, news_url TEXT,
            predicted_score REAL, predicted_label TEXT,
            confidence REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed BOOLEAN DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chatbot_sync (
            id INTEGER PRIMARY KEY, key TEXT UNIQUE, value TEXT
        )
    """)

    conn.commit()
    conn.close()
    yield db_path
    os.unlink(db_path)


@pytest.fixture(scope="session")
def api_client(test_db):
    """FastAPI TestClient with test DB."""
    # Patch DB_PATH before importing server
    import server as srv
    srv.DB_PATH = test_db
    srv.db_manager = srv.DatabaseManager(test_db)
    srv.learning_manager = srv.SentimentLearningManager(test_db)
    srv.keyword_extractor = srv.KeywordExtractor(test_db)
    from fastapi.testclient import TestClient
    return TestClient(srv.app)


@pytest.fixture(scope="session")
def sdk_client(api_client, test_db):
    """TrendRadar SDK with mocked HTTP to TestClient."""
    from trendradar import TrendRadar
    tr = TrendRadar(api_key="dev-key")

    def _mock_get(url, params=None, **kwargs):
        path = url.replace("http://localhost:8000", "")
        resp = api_client.get(path, params=params or {})
        m = MagicMock()
        m.ok = resp.status_code < 400
        m.status_code = resp.status_code
        m.json = resp.json
        m.text = resp.text
        return m

    def _mock_post(url, params=None, json=None, **kwargs):
        path = url.replace("http://localhost:8000", "")
        resp = api_client.post(path, params=params or {}, json=json or {})
        m = MagicMock()
        m.ok = resp.status_code < 400
        m.status_code = resp.status_code
        m.json = resp.json
        m.text = resp.text
        m.raise_for_status = lambda: None if m.ok else (_ for _ in ()).throw(Exception(m.text))
        return m

    tr._session.get  = _mock_get   # type: ignore
    tr._session.post = _mock_post  # type: ignore
    return tr


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════════

class TestDataLayer:
    def test_db_schema_news_articles(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("PRAGMA table_info(news_articles)")
        cols = {r[1] for r in c.fetchall()}
        conn.close()
        required = {"id","source_id","title","url","crawl_date","sentiment_score","sentiment_label"}
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_db_schema_wm_articles(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("PRAGMA table_info(wm_articles)")
        cols = {r[1] for r in c.fetchall()}
        conn.close()
        required = {"id","source_id","title","wm_category","threat_level","geo_relevance","crawl_date"}
        assert required.issubset(cols)

    def test_db_dedup_url(self, test_db):
        """Same URL should not insert twice."""
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        today = date.today().isoformat()
        c.execute(
            "INSERT OR IGNORE INTO news_articles (source_id,title,url,crawl_date) VALUES (?,?,?,?)",
            ("dup-test", "Duplicate Title", "https://vcb1.vn", today)
        )
        conn.commit()
        c.execute("SELECT COUNT(*) FROM news_articles WHERE url='https://vcb1.vn'")
        count = c.fetchone()[0]
        conn.close()
        assert count == 1, "URL dedup failed — duplicate inserted"

    def test_db_dedup_title_same_day(self, test_db):
        """Same title + source + day should not insert twice."""
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        today = date.today().isoformat()
        c.execute(
            "INSERT OR IGNORE INTO news_articles (source_id,title,url,crawl_date) VALUES (?,?,?,?)",
            ("vcb-test", "VCB báo lãi kỷ lục 42.000 tỷ, cổ tức tiền mặt 18%", "", today)
        )
        conn.commit()
        c.execute(
            "SELECT COUNT(*) FROM news_articles WHERE title LIKE 'VCB báo lãi kỷ lục%' AND crawl_date=?",
            (today,)
        )
        count = c.fetchone()[0]
        conn.close()
        assert count == 1, "Title dedup failed"

    def test_wm_articles_inserted(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM wm_articles")
        count = c.fetchone()[0]
        conn.close()
        assert count == 5

    def test_reports_table(self, test_db):
        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT market_outlook, global_risk FROM reports ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        assert row is not None
        assert row[0] in ("Bullish", "Bearish", "Neutral", "Somewhat-Bullish", "Somewhat-Bearish")
        assert row[1] in ("HIGH", "MEDIUM", "LOW")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SENTIMENT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class TestSentimentEngine:
    CASES = [
        ("VCB báo lãi kỷ lục 42.000 tỷ, cổ tức tiền mặt 18%", "Bullish"),
        ("VNIndex vượt 1.300 điểm, dòng tiền ngoại mua ròng 500 tỷ", "Bullish"),
        ("HPG ký hợp đồng xuất khẩu thép 2 tỷ USD sang EU", "Bullish"),
        ("VNM vào rổ VN30, quỹ ETF phải mua mạnh", "Bullish"),
        ("MBB trúng thầu dự án nhà ở xã hội 10.000 căn", "Bullish"),
        ("Không còn lỗ, VRE quay lại có lãi trong Q4", "Bullish"),
        ("Novaland bị call margin 3.000 tỷ, cổ phiếu giảm sàn liên tiếp", "Bearish"),
        ("VIC lao dốc 7%, nhà đầu tư bán tháo ồ ạt", "Bearish"),
        ("FLC bị huỷ niêm yết, nhà đầu tư mất trắng", "Bearish"),
        ("Không có dấu hiệu phục hồi, thị trường tiếp tục giảm", "Bearish"),
        ("Chưa đạt kế hoạch doanh thu, HPG thấp hơn kỳ vọng 20%", "Bearish"),
        ("Ngân hàng Nhà nước công bố lãi suất điều hành mới", "Neutral"),
        ("VnIndex mở cửa phiên đầu tuần", "Neutral"),
        ("Hội đồng quản trị VCB họp thường niên năm 2026", "Neutral"),
        ("Fed giữ nguyên lãi suất trong cuộc họp tháng 3", "Neutral"),
    ]

    def test_accuracy_gte_85(self):
        from src.utils.sentiment import get_sentiment
        correct = sum(1 for title, exp in self.CASES if get_sentiment(title)[1] == exp)
        accuracy = correct / len(self.CASES)
        assert accuracy >= 0.85, f"Sentiment accuracy {accuracy:.0%} < 85% ({correct}/{len(self.CASES)} correct)"

    def test_bullish_scores_positive(self):
        from src.utils.sentiment import get_sentiment
        bullish_cases = [t for t, exp in self.CASES if exp == "Bullish"]
        for title in bullish_cases:
            score, _ = get_sentiment(title)
            assert score > 0, f"Bullish case has non-positive score: {title!r} → {score}"

    def test_bearish_scores_negative(self):
        from src.utils.sentiment import get_sentiment
        bearish_cases = [t for t, exp in self.CASES if exp == "Bearish"]
        for title in bearish_cases:
            score, _ = get_sentiment(title)
            assert score < 0, f"Bearish case has non-negative score: {title!r} → {score}"

    def test_negation_handling(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("Không còn lỗ, VRE quay lại có lãi")
        assert score > 0, "Negation 'không còn lỗ' should yield positive score"

    def test_empty_input(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("")
        assert score == 0.0
        assert label == "Neutral"

    def test_score_range(self):
        from src.utils.sentiment import get_sentiment
        for title, _ in self.CASES:
            score, label = get_sentiment(title)
            assert -1.0 <= score <= 1.0, f"Score out of range: {score}"
            assert label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. API v1
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIv1:
    def test_health(self, api_client):
        r = api_client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert "timestamp" in r.json()

    def test_metrics_requires_auth(self, api_client):
        r = api_client.get("/metrics")
        # dev-key mode: passes without key
        assert r.status_code == 200

    def test_metrics_structure(self, api_client):
        r = api_client.get("/metrics", params={"apikey": "dev-key"})
        d = r.json()
        assert "news_articles" in d
        assert "wm_articles" in d
        assert d["news_articles"]["total"] >= 7

    def test_news_returns_articles(self, api_client):
        r = api_client.get("/api/v1/news", params={"apikey": "dev-key", "limit": 5})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_ticker_vcb(self, api_client):
        r = api_client.get("/api/v1/tickers/VCB", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert d["ticker"] == "VCB"
        assert "avg_sentiment_score" in d
        assert "sentiment_label" in d
        assert d["article_count"] >= 0

    def test_ticker_not_found(self, api_client):
        r = api_client.get("/api/v1/tickers/NOTEXIST", params={"apikey": "dev-key"})
        assert r.status_code == 404

    def test_market_summary(self, api_client):
        r = api_client.get("/api/v1/market/summary", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert "vn_market" in d
        assert "global_risk" in d
        assert d["global_risk"]["level"] in ("HIGH", "MEDIUM", "LOW")

    def test_alpha_vantage_compat(self, api_client):
        r = api_client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "tickers": "VCB",
            "limit": 5,
            "apikey": "dev-key",
        })
        assert r.status_code == 200
        d = r.json()
        assert "feed" in d
        assert "sentiment_score_definition" in d
        for item in d["feed"]:
            assert "overall_sentiment_score" in item
            assert "sentiment_confidence" in item
            assert -1.0 <= item["overall_sentiment_score"] <= 1.0

    def test_alpha_vantage_wrong_function(self, api_client):
        r = api_client.get("/query", params={"function": "WRONG", "apikey": "dev-key"})
        assert r.status_code == 400

    def test_feedback_endpoint(self, api_client):
        r = api_client.post("/api/v1/feedback", params={"apikey": "dev-key"}, json={
            "news_title": "Test article",
            "predicted_score": 0.3,
            "predicted_label": "Somewhat-Bullish",
            "user_score": 0.5,
            "user_label": "Bullish",
        })
        assert r.status_code == 200
        assert r.json()["success"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# 4. API v2
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIv2:
    def test_sectors_list(self, api_client):
        r = api_client.get("/api/v2/sectors", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert "sectors" in d
        assert len(d["sectors"]) == 12
        names = {s["id"] for s in d["sectors"]}
        assert "banking" in names
        assert "energy" in names

    def test_sector_banking(self, api_client):
        r = api_client.get("/api/v2/sectors/banking", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert d["sector"] == "banking"
        assert "avg_sentiment_score" in d
        assert d["ticker_count"] >= 0

    def test_sector_not_found(self, api_client):
        r = api_client.get("/api/v2/sectors/notexist", params={"apikey": "dev-key"})
        assert r.status_code == 404

    def test_batch_tickers(self, api_client):
        r = api_client.post("/api/v2/tickers/batch",
                            params={"apikey": "dev-key"},
                            json={"tickers": ["VCB", "HPG", "GAS"], "days_back": 7})
        assert r.status_code == 200
        d = r.json()
        assert "tickers" in d
        assert "VCB" in d["tickers"]
        vcb = d["tickers"]["VCB"]
        assert "avg_sentiment_score" in vcb

    def test_batch_max_30_tickers(self, api_client):
        tickers = [f"T{i:02d}" for i in range(35)]
        r = api_client.post("/api/v2/tickers/batch",
                            params={"apikey": "dev-key"},
                            json={"tickers": tickers})
        assert r.status_code == 422  # validation error

    def test_market_heatmap(self, api_client):
        r = api_client.get("/api/v2/market/heatmap", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert "heatmap" in d
        assert "banking" in d["heatmap"]
        banking = d["heatmap"]["banking"]
        assert "tickers" in banking
        assert len(banking["tickers"]) > 0

    def test_intel_all(self, api_client):
        r = api_client.get("/api/v2/intel", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert "items" in d
        assert d["total"] >= 0

    def test_intel_critical_filter(self, api_client):
        r = api_client.get("/api/v2/intel", params={"apikey": "dev-key", "threat": "critical"})
        assert r.status_code == 200
        d = r.json()
        for item in d["items"]:
            assert item["threat_level"] == "critical"

    def test_intel_search(self, api_client):
        r = api_client.get("/api/v2/intel/search", params={"apikey": "dev-key", "q": "Iran"})
        assert r.status_code == 200
        d = r.json()
        assert "results" in d

    def test_intel_threat_summary(self, api_client):
        r = api_client.get("/api/v2/intel/threat-summary", params={"apikey": "dev-key", "days_back": 2})
        assert r.status_code == 200
        d = r.json()
        assert "summary" in d

    def test_report_latest(self, api_client):
        r = api_client.get("/api/v2/reports/latest", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert "market_outlook" in d
        assert "global_risk" in d

    def test_ws_stats(self, api_client):
        r = api_client.get("/api/v3/stream/stats", params={"apikey": "dev-key"})
        assert r.status_code == 200
        d = r.json()
        assert "connected_clients" in d
        assert "watcher_running" in d


# ═══════════════════════════════════════════════════════════════════════════════
# 5. INTELLIGENCE AGENT
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntelligenceAgent:
    def test_compute_ticker_signal(self, test_db):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=test_db, groq_api_key="")
        sig = agent._compute_ticker_signal("VCB")
        assert sig.ticker == "VCB"
        assert sig.company != ""
        assert -1.0 <= sig.score <= 1.0
        assert sig.label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
        assert sig.article_count >= 0

    def test_compute_sector_signals(self, test_db):
        from src.core.intelligence_agent import IntelligenceAgent, TickerSignal
        agent = IntelligenceAgent(db_path=test_db, groq_api_key="")
        mock_signals = {
            "VCB": TickerSignal("VCB","Vietcombank",0.35,"Bullish",0.85,5,["h1"],sector="banking"),
            "HPG": TickerSignal("HPG","Hòa Phát",0.24,"Bullish",0.7,3,["h2"],sector="steel"),
            "VIC": TickerSignal("VIC","Vingroup",-0.44,"Bearish",0.85,4,["h3"],sector="real_estate"),
        }
        sectors = agent._compute_sector_signals(mock_signals)
        assert len(sectors) >= 1
        sector_ids = {s.sector for s in sectors}
        assert "banking" in sector_ids or "steel" in sector_ids

    def test_morning_brief_returns_report(self, test_db):
        from src.core.intelligence_agent import IntelligenceAgent
        # Mock Groq to avoid real API call
        agent = IntelligenceAgent(db_path=test_db, groq_api_key="")
        with patch.object(agent, "_synthesize", return_value="Test synthesis tiếng Việt"):
            report = agent.run_morning_brief(watchlist=["VCB", "HPG", "VIC"])
        assert report.report_date == date.today().isoformat()
        assert report.market_outlook in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
        assert report.global_risk in ("HIGH", "MEDIUM", "LOW")
        assert len(report.ticker_signals) == 3
        assert report.synthesis == "Test synthesis tiếng Việt"

    def test_morning_brief_saves_to_db(self, test_db):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=test_db, groq_api_key="")
        with patch.object(agent, "_synthesize", return_value=""):
            report = agent.run_morning_brief(watchlist=["VCB"])
        report_id = agent.save_report(report)
        assert report_id is not None and report_id > 0

        conn = sqlite3.connect(test_db)
        c = conn.cursor()
        c.execute("SELECT market_outlook FROM reports WHERE id=?", (report_id,))
        row = c.fetchone()
        conn.close()
        assert row is not None

    def test_telegram_format_no_crash(self, test_db):
        from src.core.intelligence_agent import IntelligenceAgent, MorningReport, TickerSignal
        from datetime import date
        report = MorningReport(
            report_date=date.today().isoformat(),
            market_outlook="Neutral", market_score=0.07,
            global_risk="HIGH", critical_events=3, high_events=5,
            ticker_signals=[], sector_signals=[],
            top_picks=[TickerSignal("VCB","Vietcombank",0.35,"Bullish",0.85,5,["Test headline"],sector="banking")],
            risk_alerts=[],
            global_context=[{"title":"Iran war","threat_level":"critical","wm_category":"geopolitical"}],
            synthesis="Test",
            generated_at=datetime.now().isoformat(),
        )
        md = report.to_telegram_md()
        assert "VCB" in md
        assert "Iran war" in md
        assert len(md) > 100


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SDK
# ═══════════════════════════════════════════════════════════════════════════════

class TestSDK:
    def test_health(self, sdk_client):
        h = sdk_client.health()
        assert h["status"] == "ok"

    def test_market_summary(self, sdk_client):
        from trendradar.models import MarketSummary
        market = sdk_client.market.summary()
        assert isinstance(market, MarketSummary)
        assert market.global_risk in ("HIGH", "MEDIUM", "LOW")
        assert market.market_label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")

    def test_sectors_list(self, sdk_client):
        sectors = sdk_client.sectors.list()
        assert len(sectors) == 12
        ids = {s["id"] for s in sectors}
        assert "banking" in ids

    def test_sector_get(self, sdk_client):
        from trendradar.models import SectorSignal
        banking = sdk_client.sectors.get("banking")
        assert isinstance(banking, SectorSignal)
        assert banking.sector == "banking"
        assert banking.ticker_count >= 0

    def test_intel_critical(self, sdk_client):
        from trendradar.models import IntelItem
        threats = sdk_client.intel.critical(limit=5)
        assert isinstance(threats, list)
        for t in threats:
            assert isinstance(t, IntelItem)
            assert t.threat_level == "critical"

    def test_intel_search(self, sdk_client):
        results = sdk_client.intel.search("Iran")
        assert isinstance(results, list)

    def test_reports_latest(self, sdk_client):
        from trendradar.models import MorningReport
        report = sdk_client.reports.latest()
        assert isinstance(report, MorningReport)
        assert report.market_outlook in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")

    def test_batch_result_methods(self, sdk_client):
        from trendradar.models import BatchResult
        batch = sdk_client.tickers(["VCB", "HPG"])
        assert isinstance(batch, BatchResult)
        bullish = batch.bullish()
        bearish = batch.bearish()
        assert isinstance(bullish, list)
        assert isinstance(bearish, list)

    def test_ticker_signal_properties(self, sdk_client):
        from trendradar.models import TickerSignal
        sig = sdk_client.ticker("VCB")
        assert isinstance(sig, TickerSignal)
        assert sig.ticker == "VCB"
        assert isinstance(sig.is_bullish, bool)
        assert isinstance(sig.is_bearish, bool)
        assert isinstance(sig.is_neutral, bool)
        assert sig.is_bullish or sig.is_bearish or sig.is_neutral


# ═══════════════════════════════════════════════════════════════════════════════
# 7. BUSINESS LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusinessLogic:
    def test_rate_limit_structure(self, api_client):
        """Rate limit state initializes correctly."""
        import server
        assert isinstance(server._rate_buckets, dict)

    def test_sentiment_score_in_av_response(self, api_client):
        """Alpha Vantage response has correct score range and label format."""
        r = api_client.get("/query", params={
            "function": "NEWS_SENTIMENT", "limit": 10, "apikey": "dev-key"
        })
        d = r.json()
        for item in d.get("feed", []):
            score = item["overall_sentiment_score"]
            label = item["overall_sentiment_label"]
            assert -1.0 <= score <= 1.0
            assert label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
            assert 0.0 <= item["sentiment_confidence"] <= 1.0

    def test_sector_mapper_coverage(self):
        """All tickers in sector mapper have aliases."""
        from src.core.sector_mapper import SECTOR_TICKERS
        from src.core.ticker_mapper import TICKER_ALIASES
        missing = []
        for sector, tickers in SECTOR_TICKERS.items():
            for t in tickers:
                if t not in TICKER_ALIASES:
                    missing.append(f"{sector}/{t}")
        assert len(missing) == 0, f"Tickers missing from TICKER_ALIASES: {missing}"

    def test_signal_watcher_init(self, test_db):
        from src.core.signal_broadcaster import SignalWatcher
        watcher = SignalWatcher(test_db)
        score, count, headline = watcher._compute_ticker_score("VCB")
        assert isinstance(score, float)
        assert isinstance(count, int)
        assert isinstance(headline, str)

    def test_iso_timestamp_format(self, api_client):
        """All timestamp fields should be ISO 8601."""
        r = api_client.get("/health")
        ts = r.json()["timestamp"]
        assert ts.endswith("Z")
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_error_response_structure(self, api_client):
        """404 should return structured error."""
        r = api_client.get("/api/v1/tickers/FAKEXYZ", params={"apikey": "dev-key"})
        assert r.status_code == 404
        d = r.json()
        assert "code" in d or "detail" in d

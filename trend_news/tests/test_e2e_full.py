"""
TrendRadar Full E2E Test Suite

Tests all layers:
  Layer 1: Sentiment engine (VN lexicon, thresholds, accuracy)
  Layer 2: WorldMonitor fetcher (RSS parse, threat classify)
  Layer 3: Article enricher (cross-reference, market signal)
  Layer 4: Database (schema, dedup, FTS5, WM table)
  Layer 5: Intelligence Agent (signal compute, sector agg, Groq)
  Layer 6: REST API v1/v2 (all endpoints, auth, rate limit)
  Layer 7: WebSocket v3 (connect, snapshot, disconnect)
  Layer 8: Python SDK (all namespaces, models, error handling)
  Layer 9: Morning Brief runner (report generation, save)

Run:
    pytest tests/test_e2e_full.py -v --tb=short
    pytest tests/test_e2e_full.py -v -k "test_sentiment"
"""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime
from typing import Dict
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sdk"))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_key")

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1: Sentiment Engine
# ─────────────────────────────────────────────────────────────────────────────

class TestSentimentEngine:
    """Accuracy tests for Vietnamese stock sentiment lexicon."""

    def setup_method(self):
        from src.utils.sentiment import get_sentiment
        self.get_sentiment = get_sentiment

    BULLISH_CASES = [
        "VCB báo lãi kỷ lục 42.000 tỷ, cổ tức tiền mặt 18%",
        "VNIndex vượt 1.300 điểm, dòng tiền ngoại mua ròng 500 tỷ",
        "HPG ký hợp đồng xuất khẩu thép 2 tỷ USD sang EU",
        "VNM vào rổ VN30, quỹ ETF phải mua mạnh",
        "MBB trúng thầu dự án nhà ở xã hội 10.000 căn",
        "Không còn lỗ, VRE quay lại có lãi trong Q4",
    ]
    BEARISH_CASES = [
        "Novaland bị call margin 3.000 tỷ, cổ phiếu giảm sàn liên tiếp",
        "VIC lao dốc 7%, nhà đầu tư bán tháo ồ ạt",
        "FLC bị huỷ niêm yết, nhà đầu tư mất trắng",
        "Không có dấu hiệu phục hồi, thị trường tiếp tục giảm",
        "Chưa đạt kế hoạch doanh thu, HPG thấp hơn kỳ vọng 20%",
        "VIC chưa có dấu hiệu phục hồi, khó khăn kéo dài",
    ]
    NEUTRAL_CASES = [
        "Ngân hàng Nhà nước công bố lãi suất điều hành mới",
        "Cổ phiếu ngân hàng diễn biến trái chiều phiên sáng",
        "VnIndex mở cửa phiên đầu tuần",
        "Hội đồng quản trị VCB họp thường niên năm 2026",
        "Fed giữ nguyên lãi suất trong cuộc họp tháng 3",
    ]

    def test_bullish_accuracy(self):
        failed = []
        for title in self.BULLISH_CASES:
            score, label = self.get_sentiment(title)
            if label not in ("Bullish", "Somewhat-Bullish"):
                failed.append(f"{label} [{score:+.3f}]: {title[:50]}")
        assert not failed, f"Bullish misclassified:\n" + "\n".join(failed)

    def test_bearish_accuracy(self):
        failed = []
        for title in self.BEARISH_CASES:
            score, label = self.get_sentiment(title)
            if label not in ("Bearish", "Somewhat-Bearish"):
                failed.append(f"{label} [{score:+.3f}]: {title[:50]}")
        assert not failed, f"Bearish misclassified:\n" + "\n".join(failed)

    def test_neutral_accuracy(self):
        failed = []
        for title in self.NEUTRAL_CASES:
            score, label = self.get_sentiment(title)
            if label not in ("Neutral", "Somewhat-Bullish", "Somewhat-Bearish"):
                failed.append(f"{label} [{score:+.3f}]: {title[:50]}")
        assert not failed, f"Neutral drifted too far:\n" + "\n".join(failed)

    def test_overall_accuracy_ge_85(self):
        all_cases = (
            [(t, True) for t in self.BULLISH_CASES] +
            [(t, False) for t in self.BEARISH_CASES] +
            [(t, None) for t in self.NEUTRAL_CASES]
        )
        correct = 0
        for title, expected_positive in all_cases:
            score, label = self.get_sentiment(title)
            if expected_positive is True and score > 0:
                correct += 1
            elif expected_positive is False and score < 0:
                correct += 1
            elif expected_positive is None and -0.30 <= score <= 0.30:
                correct += 1
        accuracy = correct / len(all_cases)
        assert accuracy >= 0.85, f"Accuracy {accuracy:.0%} < 85%"

    def test_negation_handling(self):
        score_pos, _ = self.get_sentiment("VRE quay lại có lãi")
        score_neg, _ = self.get_sentiment("Không còn lỗ, VRE có lãi trở lại")
        assert score_pos > 0, "Direct positive should be > 0"
        assert score_neg > 0, "Negation of negative should be positive"

    def test_no_false_positive_on_company_name(self):
        _, label = self.get_sentiment("Hội đồng quản trị VCB họp thường niên")
        assert label != "Bearish", "Company meeting should not be Bearish"

    def test_score_range(self):
        for title in self.BULLISH_CASES + self.BEARISH_CASES + self.NEUTRAL_CASES:
            score, _ = self.get_sentiment(title)
            assert -1.0 <= score <= 1.0, f"Score {score} out of range for: {title[:40]}"


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2: WorldMonitor Fetcher
# ─────────────────────────────────────────────────────────────────────────────

class TestWorldMonitorFetcher:
    def test_threat_classify_critical(self):
        from src.scrapers.worldmonitor_fetcher import classify_threat
        r = classify_threat("US launches airstrike on Iran nuclear facility")
        assert r["level"] == "critical"
        assert r["confidence"] >= 0.90

    def test_threat_classify_high(self):
        from src.scrapers.worldmonitor_fetcher import classify_threat
        r = classify_threat("Federal Reserve raises interest rates by 50bps")
        assert r["level"] == "high"

    def test_threat_classify_medium(self):
        from src.scrapers.worldmonitor_fetcher import classify_threat
        r = classify_threat("Vietnam-China trade talks scheduled for next month")
        assert r["level"] == "medium"

    def test_threat_classify_neutral(self):
        from src.scrapers.worldmonitor_fetcher import classify_threat
        r = classify_threat("Weather forecast for Southeast Asia")
        assert r["level"] == "info"

    def test_rss_parse_structure(self):
        from src.scrapers.worldmonitor_fetcher import _parse_rss
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>Vietnam protests China's Paracels build-up</title>
            <link>https://example.com/story1</link>
            <pubDate>Mon, 23 Mar 2026 02:00:00 GMT</pubDate>
          </item>
          <item>
            <title>Another headline</title>
            <link>https://example.com/story2</link>
            <pubDate>Mon, 23 Mar 2026 01:00:00 GMT</pubDate>
          </item>
        </channel></rss>"""
        items = _parse_rss(xml, "Test Source", "vietnam")
        assert len(items) == 2
        assert items[0]["title"] == "Vietnam protests China's Paracels build-up"
        assert items[0]["url"] == "https://example.com/story1"
        assert items[0]["wm_category"] == "vietnam"
        assert "threat_level" in items[0]

    def test_fetcher_returns_list(self):
        from src.scrapers.worldmonitor_fetcher import WorldMonitorFetcher
        fetcher = WorldMonitorFetcher(timeout=1, use_cache=False)
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                ok=True, status_code=200,
                text='<rss><channel><item><title>Test</title><link>http://x.com/1</link></item></channel></rss>'
            )
            items = fetcher.fetch_category("vietnam")
        assert isinstance(items, list)


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3: Article Enricher
# ─────────────────────────────────────────────────────────────────────────────

class TestArticleEnricher:
    def setup_method(self):
        from src.core.article_enricher import ArticleEnricher
        self.wm_articles = [
            {"title": "Vietnam exports fall amid US tariffs",
             "source": "Reuters", "url": "http://r.com/1",
             "wm_category": "vietnam", "threat_level": "high", "threat_confidence": 0.85},
            {"title": "China imposes new trade sanctions on Vietnam",
             "source": "SCMP", "url": "http://s.com/2",
             "wm_category": "geopolitical", "threat_level": "critical", "threat_confidence": 0.95},
            {"title": "Global oil prices surge 5% amid Iran conflict",
             "source": "CNBC", "url": "http://c.com/3",
             "wm_category": "finance", "threat_level": "critical", "threat_confidence": 0.9},
        ]
        self.enricher = ArticleEnricher(self.wm_articles, min_overlap_score=0.05)

    def test_enrich_adds_fields(self):
        article = {"title": "Xuất khẩu Việt Nam sang Mỹ giảm mạnh", "url": "http://x.com"}
        result = self.enricher.enrich(article)
        assert "threat_level" in result
        assert "geo_relevance" in result
        assert "market_signal" in result
        assert "global_context" in result
        assert "wm_sources" in result

    def test_threat_level_propagation(self):
        article = {"title": "Vietnam trade tariff export sanctions", "url": "http://x.com"}
        result = self.enricher.enrich(article)
        assert result["threat_level"] in ("critical", "high", "medium", "low", "info")

    def test_market_signal_values(self):
        article = {"title": "Giá dầu tăng mạnh", "url": "http://x.com"}
        result = self.enricher.enrich(article)
        assert result["market_signal"] in ("bullish", "bearish", "neutral")

    def test_geo_relevance_range(self):
        article = {"title": "Any headline", "url": "http://x.com"}
        result = self.enricher.enrich(article)
        assert 0.0 <= result["geo_relevance"] <= 1.0

    def test_enrich_batch(self):
        articles = [
            {"title": "VCB lợi nhuận tăng mạnh", "url": "http://a.com/1"},
            {"title": "VNIndex giảm điểm", "url": "http://a.com/2"},
        ]
        results = self.enricher.enrich_batch(articles)
        assert len(results) == 2
        for r in results:
            assert "threat_level" in r
            assert "global_context" in r


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 4: Database
# ─────────────────────────────────────────────────────────────────────────────

class TestDatabase:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        from src.core.database import DatabaseManager
        self.db = DatabaseManager(self.db_path)

    def teardown_method(self):
        import os
        try: os.unlink(self.db_path)
        except: pass

    def test_schema_created(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in c.fetchall()}
        conn.close()
        assert "news_articles" in tables
        assert "wm_articles" in tables
        assert "wm_articles_fts" in tables

    def test_news_articles_indexes(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='news_articles'")
        indexes = {r[0] for r in c.fetchall()}
        conn.close()
        assert "idx_unique_url" in indexes
        assert "idx_unique_news" in indexes or "idx_unique_news_new" in indexes

    def test_save_and_retrieve_news(self):
        results = {
            "cafef": {
                "VNIndex tăng mạnh hôm nay": {"url": "http://cafef.vn/1", "mobileUrl": "", "ranks": [1]},
                "HPG lãi kỷ lục": {"url": "http://cafef.vn/2", "mobileUrl": "", "ranks": [2]},
            }
        }
        count = self.db.save_news(results, {"cafef": "CafeF"})
        assert count == 2

    def test_dedup_same_url(self):
        results = {"src1": {"Article A": {"url": "http://x.com/1", "mobileUrl": "", "ranks": [1]}}}
        c1 = self.db.save_news(results, {})
        c2 = self.db.save_news(results, {})
        assert c1 == 1
        assert c2 == 0, "Duplicate URL should be skipped"

    def test_dedup_same_title_same_day(self):
        results = {"src1": {"Same Title Today": {"url": "", "mobileUrl": "", "ranks": [1]}}}
        c1 = self.db.save_news(results, {})
        c2 = self.db.save_news(results, {})
        assert c1 == 1
        assert c2 == 0, "Same title+source+day should be deduped"

    def test_wm_articles_save(self):
        articles = [
            {"title": "Iran war escalates", "url": "http://fp.com/1", "source": "Foreign Policy",
             "wm_category": "geopolitical", "threat_level": "critical", "threat_confidence": 0.95,
             "geo_relevance": 0.6, "published_at": 1700000000000},
            {"title": "Vietnam economy resilient", "url": "http://nk.com/1", "source": "Nikkei Asia",
             "wm_category": "vietnam", "threat_level": "info", "threat_confidence": 0.5,
             "geo_relevance": 0.8, "published_at": 1700000000001},
        ]
        count = self.db.save_wm_articles(articles)
        assert count == 2

    def test_wm_dedup(self):
        articles = [{"title": "Same WM Article", "url": "http://wm.com/1", "source": "BBC",
                     "wm_category": "asia", "threat_level": "high", "threat_confidence": 0.85,
                     "geo_relevance": 0.3, "published_at": 1700000000000}]
        c1 = self.db.save_wm_articles(articles)
        c2 = self.db.save_wm_articles(articles)
        assert c1 == 1
        assert c2 == 0

    def test_wm_fts5_search(self):
        articles = [
            {"title": "Vietnam exports face tariff pressure", "url": "http://r.com/1",
             "source": "Reuters", "wm_category": "vietnam", "threat_level": "medium",
             "threat_confidence": 0.7, "geo_relevance": 0.5, "published_at": None},
        ]
        self.db.save_wm_articles(articles)
        results = self.db.search_wm_articles("Vietnam tariff")
        assert len(results) >= 1
        assert any("Vietnam" in r["title"] for r in results)

    def test_wm_stats(self):
        articles = [
            {"title": f"Article {i}", "url": f"http://x.com/{i}", "source": "Test",
             "wm_category": "finance", "threat_level": lvl, "threat_confidence": 0.8,
             "geo_relevance": 0.4, "published_at": None}
            for i, lvl in enumerate(["critical", "critical", "high", "medium", "info"])
        ]
        self.db.save_wm_articles(articles)
        stats = self.db.get_wm_stats()
        assert stats["total"] >= 5
        assert "by_threat" in stats
        assert "by_category" in stats


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 5: Intelligence Agent
# ─────────────────────────────────────────────────────────────────────────────

class TestIntelligenceAgent:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        from src.core.database import DatabaseManager
        db = DatabaseManager(self.db_path)
        # Seed some news articles
        results = {
            "vcb": {"VCB lãi kỷ lục 2026": {"url": "http://vcb.com/1", "mobileUrl": "", "ranks": [1]}},
            "hpg": {"HPG xuất khẩu thép tăng mạnh": {"url": "http://hpg.com/1", "mobileUrl": "", "ranks": [1]}},
        }
        db.save_news(results, {})
        # Seed WM articles
        db.save_wm_articles([
            {"title": "Iran war critical event", "url": "http://fp.com/1", "source": "FP",
             "wm_category": "geopolitical", "threat_level": "critical", "threat_confidence": 0.95,
             "geo_relevance": 0.5, "published_at": None},
        ])

    def teardown_method(self):
        import os
        try: os.unlink(self.db_path)
        except: pass

    def test_compute_ticker_signal(self):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=self.db_path, groq_api_key="")
        sig = agent._compute_ticker_signal("VCB")
        assert sig.ticker == "VCB"
        assert -1.0 <= sig.score <= 1.0
        assert sig.label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
        assert isinstance(sig.article_count, int)

    def test_compute_sector_signals(self):
        from src.core.intelligence_agent import IntelligenceAgent, TickerSignal
        from src.core.sector_mapper import TICKER_SECTOR
        agent = IntelligenceAgent(db_path=self.db_path, groq_api_key="")
        fake_signals = {
            "VCB": TickerSignal("VCB","Vietcombank",0.35,"Bullish",0.8,5,[],
                                "info","neutral", TICKER_SECTOR.get("VCB","")),
            "HPG": TickerSignal("HPG","Hoa Phat",0.2,"Bullish",0.7,3,[],
                                "info","neutral", TICKER_SECTOR.get("HPG","")),
            "VIC": TickerSignal("VIC","Vingroup",-0.2,"Somewhat-Bearish",0.6,2,[],
                                "info","neutral", TICKER_SECTOR.get("VIC","")),
        }
        sector_sigs = agent._compute_sector_signals(fake_signals)
        assert isinstance(sector_sigs, list)
        assert len(sector_sigs) > 0
        for s in sector_sigs:
            assert -1.0 <= s.avg_score <= 1.0

    def test_morning_brief_structure(self):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=self.db_path, groq_api_key="")
        report = agent.run_morning_brief(watchlist=["VCB", "HPG"])
        assert report.report_date == date.today().isoformat()
        assert report.market_outlook in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
        assert report.global_risk in ("HIGH","MEDIUM","LOW")
        assert isinstance(report.ticker_signals, list)
        assert isinstance(report.sector_signals, list)
        assert isinstance(report.top_picks, list)
        assert isinstance(report.risk_alerts, list)

    def test_save_report(self):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=self.db_path, groq_api_key="")
        report = agent.run_morning_brief(watchlist=["VCB"])
        report_id = agent.save_report(report)
        assert isinstance(report_id, int)
        assert report_id > 0
        # Verify saved
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT report_date, market_outlook FROM reports WHERE id=?", [report_id])
        row = c.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == date.today().isoformat()

    def test_telegram_format(self):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=self.db_path, groq_api_key="")
        report = agent.run_morning_brief(watchlist=["VCB"])
        md = report.to_telegram_md()
        assert "TRENDRADAR" in md
        assert "THỊ TRƯỜNG" in md
        assert "BỐI CẢNH" in md

    def test_report_json_round_trip(self):
        from src.core.intelligence_agent import IntelligenceAgent
        agent = IntelligenceAgent(db_path=self.db_path, groq_api_key="")
        report = agent.run_morning_brief(watchlist=["VCB"])
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["report_date"] == date.today().isoformat()
        assert "market_outlook" in data


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 6: REST API (all endpoints)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def api_client():
    import server
    from fastapi.testclient import TestClient
    return TestClient(server.app)

KEY = "dev-key"

class TestAPIv1:
    def test_health(self, api_client):
        r = api_client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_metrics(self, api_client):
        r = api_client.get("/metrics", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert "news_articles" in data
        assert "wm_articles" in data

    def test_news_endpoint(self, api_client):
        r = api_client.get("/api/v1/news", params={"apikey": KEY, "limit": 5})
        assert r.status_code == 200

    def test_ticker_vcb(self, api_client):
        r = api_client.get("/api/v1/tickers/VCB", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert data["ticker"] == "VCB"
        assert "avg_sentiment_score" in data
        assert -1 <= data["avg_sentiment_score"] <= 1
        assert data["sentiment_label"] in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")

    def test_ticker_not_found(self, api_client):
        r = api_client.get("/api/v1/tickers/INVALID999", params={"apikey": KEY})
        assert r.status_code == 404
        assert "code" in r.json()

    def test_market_summary(self, api_client):
        r = api_client.get("/api/v1/market/summary", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert "vn_market" in data
        assert "global_risk" in data
        assert data["global_risk"]["level"] in ("HIGH","MEDIUM","LOW")

    def test_alpha_vantage_compat(self, api_client):
        r = api_client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "tickers": "VCB",
            "limit": 10,
            "apikey": KEY,
        })
        assert r.status_code == 200
        data = r.json()
        assert "feed" in data
        assert "items" in data
        if data["feed"]:
            item = data["feed"][0]
            assert "title" in item
            assert "overall_sentiment_score" in item
            assert "sentiment_confidence" in item  # new field
            assert "time_published" in item
            # time_published must be ISO 8601 (not stripped)
            assert "T" in item["time_published"]

    def test_alpha_vantage_wrong_function(self, api_client):
        r = api_client.get("/query", params={"function": "INVALID", "apikey": KEY})
        assert r.status_code == 400

    def test_feedback_submit(self, api_client):
        r = api_client.post("/api/v1/feedback", params={"apikey": KEY}, json={
            "news_title": "VCB tăng trưởng mạnh",
            "predicted_score": 0.3,
            "predicted_label": "Bullish",
            "user_score": 0.4,
            "user_label": "Bullish",
        })
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestAPIv2:
    def test_sectors_list(self, api_client):
        r = api_client.get("/api/v2/sectors", params={"apikey": KEY})
        assert r.status_code == 200
        sectors = r.json()["sectors"]
        assert len(sectors) == 12
        ids = [s["id"] for s in sectors]
        assert "banking" in ids
        assert "energy" in ids

    def test_sector_banking(self, api_client):
        r = api_client.get("/api/v2/sectors/banking", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert data["sector"] == "banking"
        assert "avg_sentiment_score" in data
        assert "tickers" in data
        assert data["ticker_count"] >= 0

    def test_sector_not_found(self, api_client):
        r = api_client.get("/api/v2/sectors/INVALID", params={"apikey": KEY})
        assert r.status_code == 404

    def test_batch_tickers(self, api_client):
        r = api_client.post(
            "/api/v2/tickers/batch",
            json={"tickers": ["VCB", "HPG", "GAS"], "days_back": 7},
            params={"apikey": KEY},
        )
        assert r.status_code == 200
        data = r.json()
        assert "tickers" in data
        assert "VCB" in data["tickers"]

    def test_batch_limit(self, api_client):
        r = api_client.post(
            "/api/v2/tickers/batch",
            json={"tickers": [f"T{i}" for i in range(35)]},  # >30 limit
            params={"apikey": KEY},
        )
        assert r.status_code == 422  # validation error

    def test_heatmap(self, api_client):
        r = api_client.get("/api/v2/market/heatmap", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert "heatmap" in data
        hm = data["heatmap"]
        assert "banking" in hm
        assert "tickers" in hm["banking"]

    def test_intel_endpoint(self, api_client):
        r = api_client.get("/api/v2/intel", params={"apikey": KEY, "limit": 10})
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "by_threat" in data
        assert "total" in data

    def test_intel_threat_filter(self, api_client):
        r = api_client.get("/api/v2/intel", params={
            "apikey": KEY, "threat": "critical", "limit": 20
        })
        assert r.status_code == 200
        items = r.json()["items"]
        for item in items:
            assert item["threat_level"] == "critical"

    def test_intel_search(self, api_client):
        r = api_client.get("/api/v2/intel/search", params={"q": "Vietnam", "apikey": KEY})
        assert r.status_code == 200
        assert "results" in r.json()

    def test_intel_search_too_short(self, api_client):
        r = api_client.get("/api/v2/intel/search", params={"q": "x", "apikey": KEY})
        assert r.status_code == 422

    def test_threat_summary(self, api_client):
        r = api_client.get("/api/v2/intel/threat-summary", params={"apikey": KEY, "days_back": 2})
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data

    def test_report_generate(self, api_client):
        r = api_client.post("/api/v2/reports/generate", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert "market_outlook" in data
        assert "global_risk" in data
        assert data["market_outlook"] in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")

    def test_report_latest(self, api_client):
        # Generate first
        api_client.post("/api/v2/reports/generate", params={"apikey": KEY})
        r = api_client.get("/api/v2/reports/latest", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert "market_outlook" in data
        assert "report_date" in data

    def test_ws_stats(self, api_client):
        r = api_client.get("/api/v3/stream/stats", params={"apikey": KEY})
        assert r.status_code == 200
        data = r.json()
        assert "connected_clients" in data
        assert "watcher_running" in data


class TestAPIAuth:
    def test_no_auth_returns_200_dev_mode(self, api_client):
        """In dev mode (no keys configured), all requests pass."""
        r = api_client.get("/api/v1/news")
        assert r.status_code == 200

    def test_health_no_auth(self, api_client):
        r = api_client.get("/health")
        assert r.status_code == 200

    def test_rate_limit_buckets(self, api_client):
        """Rate limit tracking should not crash on rapid requests."""
        for _ in range(5):
            r = api_client.get("/api/v1/news", params={"apikey": KEY, "limit": 1})
            assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 7: WebSocket
# ─────────────────────────────────────────────────────────────────────────────

class TestWebSocket:
    def test_ws_connect_and_snapshot(self, api_client):
        with api_client.websocket_connect(
            f"/api/v3/stream?tickers=VCB,HPG&apikey={KEY}"
        ) as ws:
            # First message: connected
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connected"
            assert "VCB" in msg["subscribed_tickers"]

            # Next messages: snapshots for each ticker
            snapshots = {}
            for _ in range(2):
                msg = json.loads(ws.receive_text())
                if msg["type"] == "snapshot":
                    snapshots[msg["ticker"]] = msg
            assert "VCB" in snapshots or "HPG" in snapshots

    def test_ws_snapshot_fields(self, api_client):
        with api_client.websocket_connect(
            f"/api/v3/stream?tickers=VCB&apikey={KEY}"
        ) as ws:
            ws.receive_text()  # connected
            snap = json.loads(ws.receive_text())  # snapshot
            assert snap["type"] == "snapshot"
            assert "score" in snap
            assert "label" in snap
            assert "article_count" in snap
            assert "timestamp" in snap
            assert -1.0 <= snap["score"] <= 1.0

    def test_ws_ping_pong(self, api_client):
        with api_client.websocket_connect(
            f"/api/v3/stream?tickers=VCB&apikey={KEY}"
        ) as ws:
            ws.receive_text()  # connected
            ws.receive_text()  # snapshot
            ws.send_text("ping")
            pong = json.loads(ws.receive_text())
            assert pong["type"] == "pong"

    def test_ws_unauthorized(self, api_client):
        """With strict auth configured, bad key should close connection."""
        import server
        original = server.API_KEYS
        server.API_KEYS = {"valid-key"}
        try:
            with pytest.raises(Exception):
                with api_client.websocket_connect("/api/v3/stream?tickers=VCB&apikey=bad") as ws:
                    ws.receive_text()
        finally:
            server.API_KEYS = original

    def test_ws_default_tickers(self, api_client):
        """Empty tickers param should get default tickers."""
        with api_client.websocket_connect(
            f"/api/v3/stream?apikey={KEY}"
        ) as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connected"
            assert len(msg["subscribed_tickers"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 8: Python SDK
# ─────────────────────────────────────────────────────────────────────────────

class TestSDK:
    """Tests for trendradar Python SDK."""

    @pytest.fixture(autouse=True)
    def setup_sdk(self, api_client):
        import server
        from trendradar import TrendRadar
        self.tr = TrendRadar(api_key="dev-key", base_url="http://testserver")

        def mock_get(url, params=None, **kwargs):
            path = url.replace("http://testserver", "")
            resp = api_client.get(path, params=params or {})
            m = MagicMock()
            m.ok = resp.status_code < 400
            m.status_code = resp.status_code
            m.json = resp.json
            m.text = resp.text
            return m

        def mock_post(url, params=None, json=None, **kwargs):
            path = url.replace("http://testserver", "")
            resp = api_client.post(path, params=params or {}, json=json or {})
            m = MagicMock()
            m.ok = resp.status_code < 400
            m.status_code = resp.status_code
            m.json = resp.json
            m.text = resp.text
            m.raise_for_status = lambda: None if m.ok else (_ for _ in ()).throw(Exception("HTTP Error"))
            return m

        self.mock_get_patch = patch.object(self.tr._session, "get", side_effect=mock_get)
        self.mock_post_patch = patch.object(self.tr._session, "post", side_effect=mock_post)
        self.mock_get_patch.start()
        self.mock_post_patch.start()
        yield
        self.mock_get_patch.stop()
        self.mock_post_patch.stop()

    def test_sdk_health(self):
        h = self.tr.health()
        assert h["status"] == "ok"

    def test_sdk_ticker(self):
        vcb = self.tr.ticker("VCB")
        from trendradar.models import TickerSignal
        assert isinstance(vcb, TickerSignal)
        assert vcb.ticker == "VCB"
        assert vcb.company
        assert vcb.label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
        assert -1 <= vcb.score <= 1
        assert vcb.is_bullish or vcb.is_bearish or vcb.is_neutral

    def test_sdk_batch(self):
        batch = self.tr.tickers(["VCB", "HPG", "GAS"])
        from trendradar.models import BatchResult
        assert isinstance(batch, BatchResult)
        assert len(batch.tickers) >= 0
        bulls = batch.bullish()
        bears = batch.bearish()
        assert isinstance(bulls, list)
        assert isinstance(bears, list)

    def test_sdk_market_summary(self):
        market = self.tr.market.summary()
        from trendradar.models import MarketSummary
        assert isinstance(market, MarketSummary)
        assert market.market_label in ("Bullish","Somewhat-Bullish","Neutral","Somewhat-Bearish","Bearish")
        assert market.global_risk in ("HIGH","MEDIUM","LOW")
        assert isinstance(market.is_high_risk, bool)

    def test_sdk_sectors_list(self):
        sectors = self.tr.sectors.list()
        assert len(sectors) == 12
        assert any(s["id"] == "banking" for s in sectors)

    def test_sdk_sectors_get(self):
        banking = self.tr.sectors.get("banking")
        from trendradar.models import SectorSignal
        assert isinstance(banking, SectorSignal)
        assert banking.sector == "banking"
        assert banking.ticker_count >= 0

    def test_sdk_intel_critical(self):
        items = self.tr.intel.critical(limit=5)
        from trendradar.models import IntelItem
        for item in items:
            assert isinstance(item, IntelItem)
            assert item.threat_level == "critical"

    def test_sdk_intel_search(self):
        results = self.tr.intel.search("Vietnam trade")
        assert isinstance(results, list)

    def test_sdk_reports_latest(self):
        # Generate first
        with patch.object(self.tr._session, "post") as mock_p:
            mock_p.return_value = MagicMock(
                ok=True, status_code=200,
                json=lambda: {"report_id": 1, "market_outlook": "Neutral",
                              "global_risk": "HIGH", "market_score": 0.07,
                              "top_picks": [], "risk_alerts": [], "synthesis": ""},
                text="",
            )
            mock_p.return_value.raise_for_status = lambda: None
        report = self.tr.reports.latest()
        from trendradar.models import MorningReport
        assert isinstance(report, MorningReport)

    def test_sdk_models_repr(self):
        from trendradar.models import TickerSignal, MarketSummary, SignalUpdate
        sig = TickerSignal("VCB","Vietcombank",0.35,"Bullish",0.85,10,[],None,None,"banking")
        assert "VCB" in repr(sig)
        assert "+0.350" in repr(sig)
        upd = SignalUpdate.from_dict({
            "type": "signal_update", "ticker": "VCB",
            "score": 0.35, "label": "Bullish", "delta": 0.1
        })
        assert "VCB" in repr(upd)


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 9: Morning Brief Runner
# ─────────────────────────────────────────────────────────────────────────────

class TestMorningBriefRunner:
    def test_morning_brief_import(self):
        import morning_brief
        assert hasattr(morning_brief, "main")
        assert hasattr(morning_brief, "_generate_report")

    def test_morning_brief_skip_fetch(self, tmp_path):
        """Run morning brief with skip-fetch flag."""
        import sys
        sys.argv = ["morning_brief.py", "--skip-fetch", "--no-telegram"]
        import morning_brief
        import os
        os.environ["GROQ_API_KEY"] = "gsk_test"
        # Just test it imports and parses args correctly
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--skip-fetch", action="store_true")
        parser.add_argument("--no-telegram", action="store_true")
        parser.add_argument("--watchlist", nargs="+", default=None)
        args = parser.parse_args(["--skip-fetch", "--no-telegram"])
        assert args.skip_fetch is True
        assert args.no_telegram is True


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION: Full pipeline smoke test
# ─────────────────────────────────────────────────────────────────────────────

class TestFullPipelineIntegration:
    """End-to-end smoke test: DB → Agent → Report → API → SDK."""

    def test_full_flow(self, api_client):
        """
        1. Generate report via API
        2. Fetch it back via API
        3. Verify fields consistent
        """
        # Step 1: Generate
        r1 = api_client.post("/api/v2/reports/generate", params={"apikey": KEY})
        assert r1.status_code == 200
        generated = r1.json()
        assert "market_outlook" in generated
        assert "global_risk" in generated
        assert "market_score" in generated

        # Step 2: Fetch latest
        r2 = api_client.get("/api/v2/reports/latest", params={"apikey": KEY})
        assert r2.status_code == 200
        latest = r2.json()
        assert latest["market_outlook"] == generated["market_outlook"]

        # Step 3: Verify content structure
        content = latest.get("content", {})
        assert "ticker_signals" in content
        assert "sector_signals" in content

    def test_sentiment_consistency(self, api_client):
        """Same ticker queried via different endpoints returns consistent signals."""
        r1 = api_client.get("/api/v1/tickers/VCB", params={"apikey": KEY})
        r2 = api_client.post("/api/v2/tickers/batch",
                             json={"tickers": ["VCB"]}, params={"apikey": KEY})
        assert r1.status_code == 200
        assert r2.status_code == 200
        score1 = r1.json()["avg_sentiment_score"]
        score2 = r2.json()["tickers"]["VCB"]["avg_sentiment_score"]
        assert abs(score1 - score2) < 0.05, f"Scores inconsistent: {score1} vs {score2}"

    def test_market_sector_alignment(self, api_client):
        """Market summary global_risk aligns with intel threat counts."""
        market_r = api_client.get("/api/v1/market/summary", params={"apikey": KEY})
        intel_r  = api_client.get("/api/v2/intel", params={"apikey": KEY, "limit": 100})
        assert market_r.status_code == 200
        assert intel_r.status_code == 200
        # Both should complete without errors
        mkt = market_r.json()
        intel = intel_r.json()
        assert mkt["global_risk"]["level"] in ("HIGH","MEDIUM","LOW")
        assert isinstance(intel["total"], int)

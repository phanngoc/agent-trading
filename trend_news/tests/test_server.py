"""
Tests for trend_news/server.py

Run from the trend_news/ directory:
    pytest tests/test_server.py -v

Or with coverage:
    pytest tests/test_server.py -v --tb=short
"""
import sys
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup: allow imports like `from src.core.database import ...`
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------
SAMPLE_DB_ROWS = [
    {
        "source_id": "vnexpress",
        "title": "Thị trường chứng khoán tăng mạnh phiên cuối tuần",
        "url": "https://vnexpress.net/thi-truong-tang.html",
        "mobile_url": "",
        "ranks": "1,2",
        "crawled_at": "2024-12-01T08:00:00",
    },
    {
        "source_id": "cafef",
        "title": "Giá vàng lao dốc không phanh",
        "url": "https://cafef.vn/vang-lao-doc.html",
        "mobile_url": "",
        "ranks": "3",
        "crawled_at": "2024-12-01T09:30:00",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_client(mock_db_rows=None):
    """
    Build a FastAPI TestClient with DatabaseManager patched.
    Returns (client, mock_db_manager_instance).
    """
    from fastapi.testclient import TestClient

    rows = mock_db_rows if mock_db_rows is not None else SAMPLE_DB_ROWS

    mock_db = MagicMock()
    mock_db.get_filtered_news.return_value = rows
    mock_db.get_latest_news.return_value = rows

    # Patch DatabaseManager at the module level used by server.py
    with patch("src.core.database.DatabaseManager", return_value=mock_db):
        # Re-import server each time so the patched class is used
        import importlib
        import server as srv_module

        importlib.reload(srv_module)
        client = TestClient(srv_module.app)
        return client, mock_db


# ---------------------------------------------------------------------------
# Tests: Root
# ---------------------------------------------------------------------------
class TestRoot:
    def test_root_returns_welcome_message(self):
        client, _ = _make_client()
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Welcome to TrendRadar API"


# ---------------------------------------------------------------------------
# Tests: /query – Alpha Vantage Compatible
# ---------------------------------------------------------------------------
class TestQueryEndpoint:
    # --- Function validation -----------------------------------------------
    def test_wrong_function_returns_400(self):
        client, _ = _make_client()
        resp = client.get("/query", params={"function": "EARNINGS"})
        assert resp.status_code == 400

    def test_missing_function_returns_422(self):
        """FastAPI validates required Query params → 422 Unprocessable Entity."""
        client, _ = _make_client()
        resp = client.get("/query")
        assert resp.status_code == 422

    # --- Happy path --------------------------------------------------------
    def test_news_sentiment_basic(self):
        client, mock_db = _make_client()
        resp = client.get("/query", params={"function": "NEWS_SENTIMENT"})
        assert resp.status_code == 200
        body = resp.json()
        assert "feed" in body
        assert body["items"] == str(len(SAMPLE_DB_ROWS))
        mock_db.get_filtered_news.assert_called_once()

    def test_response_schema_fields(self):
        client, _ = _make_client()
        resp = client.get("/query", params={"function": "NEWS_SENTIMENT"})
        body = resp.json()
        assert "sentiment_score_definition" in body
        assert "relevance_score_definition" in body
        first = body["feed"][0]
        for field in ("title", "url", "time_published", "source",
                      "overall_sentiment_score", "overall_sentiment_label"):
            assert field in first, f"Missing field: {field}"

    def test_empty_db_returns_empty_feed(self):
        client, _ = _make_client(mock_db_rows=[])
        resp = client.get("/query", params={"function": "NEWS_SENTIMENT"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["feed"] == []
        assert body["items"] == "0"

    # --- Ticker / source filter --------------------------------------------
    def test_tickers_passed_as_source_filter(self):
        client, mock_db = _make_client()
        client.get("/query", params={"function": "NEWS_SENTIMENT", "tickers": "vnexpress"})
        call_kwargs = mock_db.get_filtered_news.call_args
        assert call_kwargs.kwargs.get("source_id") == "vnexpress" or \
               call_kwargs.args[2] == "vnexpress"

    # --- Topics ------------------------------------------------------------
    def test_topics_included_in_feed_items(self):
        client, _ = _make_client()
        resp = client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "topics": "finance",
        })
        body = resp.json()
        for item in body["feed"]:
            assert "finance" in item["topics"]

    def test_no_topics_param_gives_empty_list(self):
        client, _ = _make_client()
        resp = client.get("/query", params={"function": "NEWS_SENTIMENT"})
        body = resp.json()
        for item in body["feed"]:
            assert item["topics"] == []

    # --- Limit -------------------------------------------------------------
    def test_limit_passed_to_db(self):
        client, mock_db = _make_client()
        client.get("/query", params={"function": "NEWS_SENTIMENT", "limit": 10})
        call_kwargs = mock_db.get_filtered_news.call_args
        # limit is passed as positional or keyword arg
        args = call_kwargs.args
        kwargs = call_kwargs.kwargs
        assert kwargs.get("limit") == 10 or (len(args) >= 4 and args[3] == 10)

    # --- Time format parsing -----------------------------------------------
    def test_time_from_yyyymmddthhmm_format(self):
        """Valid YYYYMMDDTHHMM should parse and pass start_date to DB."""
        client, mock_db = _make_client()
        client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "time_from": "20241201T0800",
        })
        call_kwargs = mock_db.get_filtered_news.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[0]
        assert start_date is not None
        # Should be ISO format
        dt = datetime.fromisoformat(start_date)
        assert dt.year == 2024
        assert dt.month == 12
        assert dt.day == 1

    def test_time_from_yyyymmdd_format(self):
        """YYYYMMDD (date-only) should also be accepted."""
        client, mock_db = _make_client()
        client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "time_from": "20241201",
        })
        call_kwargs = mock_db.get_filtered_news.call_args
        start_date = call_kwargs.kwargs.get("start_date") or call_kwargs.args[0]
        assert start_date is not None
        dt = datetime.fromisoformat(start_date)
        assert dt.year == 2024

    def test_time_to_yyyymmddthhmm_format(self):
        client, mock_db = _make_client()
        client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "time_to": "20241231T2359",
        })
        call_kwargs = mock_db.get_filtered_news.call_args
        end_date = call_kwargs.kwargs.get("end_date") or call_kwargs.args[1]
        assert end_date is not None
        dt = datetime.fromisoformat(end_date)
        assert dt.year == 2024
        assert dt.month == 12

    def test_invalid_time_from_silently_ignored(self):
        """Invalid time_from should not raise; DB called with start_date=None."""
        client, mock_db = _make_client()
        resp = client.get("/query", params={
            "function": "NEWS_SENTIMENT",
            "time_from": "not-a-date",
        })
        assert resp.status_code == 200
        call_kwargs = mock_db.get_filtered_news.call_args
        # server.py uses keyword args; start_date_iso stays None on bad input
        start_date = call_kwargs.kwargs.get("start_date")
        assert start_date is None

    # --- Sentiment in response ---------------------------------------------
    def test_sentiment_fields_are_numeric_and_string(self):
        client, _ = _make_client()
        resp = client.get("/query", params={"function": "NEWS_SENTIMENT"})
        for item in resp.json()["feed"]:
            assert isinstance(item["overall_sentiment_score"], float)
            assert isinstance(item["overall_sentiment_label"], str)
            assert item["overall_sentiment_label"] in (
                "Bearish", "Somewhat-Bearish", "Neutral", "Somewhat-Bullish", "Bullish"
            )


# ---------------------------------------------------------------------------
# Tests: /api/v1/news – Native API
# ---------------------------------------------------------------------------
class TestNativeNewsEndpoint:
    def test_native_news_returns_list(self):
        client, mock_db = _make_client()
        resp = client.get("/api/v1/news")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        mock_db.get_filtered_news.assert_called_once()

    def test_native_news_with_source_filter(self):
        client, mock_db = _make_client()
        client.get("/api/v1/news", params={"source": "cafef"})
        call_kwargs = mock_db.get_filtered_news.call_args
        # server.py passes source as positional arg[2]
        assert "cafef" in str(call_kwargs)

    def test_native_news_with_limit(self):
        client, mock_db = _make_client()
        client.get("/api/v1/news", params={"limit": 5})
        call_kwargs = mock_db.get_filtered_news.call_args
        assert "5" in str(call_kwargs) or 5 in str(call_kwargs)

    def test_native_news_returns_db_data(self):
        client, _ = _make_client()
        resp = client.get("/api/v1/news")
        data = resp.json()
        assert len(data) == len(SAMPLE_DB_ROWS)
        assert data[0]["source_id"] == SAMPLE_DB_ROWS[0]["source_id"]


# ---------------------------------------------------------------------------
# Tests: Sentiment utility
# ---------------------------------------------------------------------------
class TestSentimentUtil:
    def test_get_sentiment_returns_tuple(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("The market is rising strongly today!")
        assert isinstance(score, float)
        assert isinstance(label, str)

    def test_get_sentiment_empty_string(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("")
        assert score == 0.0
        assert label == "Neutral"

    def test_get_sentiment_score_range(self):
        from src.utils.sentiment import get_sentiment
        score, _ = get_sentiment("good great excellent")
        assert -1.0 <= score <= 1.0

    def test_sentiment_labels_valid(self):
        from src.utils.sentiment import get_sentiment
        valid_labels = {"Bearish", "Somewhat-Bearish", "Neutral", "Somewhat-Bullish", "Bullish"}
        for text in ("crash collapse terrible", "bad", "okay", "good profit", "amazing bull run"):
            _, label = get_sentiment(text)
            assert label in valid_labels, f"Unexpected label '{label}' for text '{text}'"

    def test_vietnamese_positive(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("Thị trường tăng mạnh, khởi sắc")
        assert score > 0.0
        assert label in ("Somewhat-Bullish", "Bullish")

    def test_vietnamese_negative(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("Giá vàng lao dốc không phanh")
        assert score < 0.0
        assert label in ("Bearish", "Somewhat-Bearish")

    def test_vietnamese_neutral(self):
        from src.utils.sentiment import get_sentiment
        score, label = get_sentiment("Hội nghị thường niên của công ty")
        assert label == "Neutral"

    def test_is_vietnamese_detection(self):
        from src.utils.sentiment import _is_vietnamese
        assert _is_vietnamese("Thị trường chứng khoán")
        assert not _is_vietnamese("The stock market today")
        assert not _is_vietnamese("Bonjour le monde")

    def test_mixed_vi_en_routes_vietnamese(self):
        from src.utils.sentiment import get_sentiment, _is_vietnamese
        text = "VN-Index tăng điểm, uptrend confirmed"
        assert _is_vietnamese(text)
        score, label = get_sentiment(text)
        assert score > 0.0

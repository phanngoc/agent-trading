#!/usr/bin/env python3
"""
Test script cho get_vn_news function
Tương thích với Alpha Vantage NEWS_SENTIMENT API
"""

import requests
import json

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


def get_vn_news_with_sentiment(ticker: str, start: str, end: str) -> dict:
    """
    Get Vietnamese news with full response including sentiment definitions.
    Returns entire response for debugging.
    """
    resp = requests.get(f"{BASE_URL}/query", params={
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": start.replace("-", "") + "T0000",
        "time_to": end.replace("-", "") + "T2359",
        "limit": 50,
    })
    return resp.json()


def print_news_summary(ticker: str, news_list: list[dict]):
    """Print formatted news summary."""
    print(f"\n{'='*60}")
    print(f"📈 Ticker: {ticker} - Found {len(news_list)} news articles")
    print(f"{'='*60}")
    
    if not news_list:
        print("  ⚠️  No news found for this ticker")
        return
    
    for i, item in enumerate(news_list, 1):
        sentiment_emoji = {
            "Bullish": "🟢",
            "Somewhat-Bullish": "🟡",
            "Neutral": "⚪",
            "Somewhat-Bearish": "🟠",
            "Bearish": "🔴"
        }.get(item.get("overall_sentiment_label", "Neutral"), "⚪")
        
        print(f"\n  {i}. {sentiment_emoji} {item['title']}")
        print(f"     📰 Source: {item['source']}")
        print(f"     📅 Published: {item['time_published']}")
        print(f"     😊 Sentiment: {item['overall_sentiment_label']} (score: {item['overall_sentiment_score']:.2f})")
        print(f"     🔗 URL: {item['url']}")


def test_multiple_tickers():
    """Test với nhiều ticker phổ biến ở VN."""
    tickers = ["VIC", "FPT", "HPG", "VCB", "VNM", "MSN"]
    start_date = "2026-02-01"
    end_date = "2026-02-15"
    
    print(f"\n{'#'*60}")
    print(f"# Testing Vietnamese News API")
    print(f"# Date range: {start_date} to {end_date}")
    print(f"{'#'*60}")
    
    for ticker in tickers:
        try:
            news = get_vn_news(ticker, start_date, end_date)
            print_news_summary(ticker, news)
        except Exception as e:
            print(f"\n❌ Error fetching {ticker}: {e}")


def test_native_api():
    """Test native API endpoint."""
    print(f"\n{'#'*60}")
    print(f"# Testing Native API (/api/v1/news)")
    print(f"{'#'*60}")
    
    resp = requests.get(f"{BASE_URL}/api/v1/news", params={
        "start_date": "2026-02-01",
        "end_date": "2026-02-15",
        "tickers": "VIC",
        "limit": 5,
    })
    
    data = resp.json()
    print(f"\n✅ Native API returned {len(data)} items")
    if data:
        print(f"   Sample: {data[0].get('title', 'N/A')[:60]}...")


def test_multiple_tickers_combined():
    """Test với nhiều ticker cùng lúc."""
    print(f"\n{'#'*60}")
    print(f"# Testing Multiple Tickers (VIC,HPG,FPT)")
    print(f"{'#'*60}")
    
    result = get_vn_news_with_sentiment("VIC,HPG,FPT", "2026-02-01", "2026-02-15")
    print(f"\n✅ Total items: {result.get('items', 0)}")
    print(f"   Sentiment Definition: {result.get('sentiment_score_definition', 'N/A')[:50]}...")
    
    for item in result.get("feed", [])[:3]:
        print(f"\n   📰 {item['title'][:70]}...")
        print(f"      😊 {item['overall_sentiment_label']} | 🔗 {item['source']}")


def main():
    print("="*60)
    print("🇻🇳 Vietnamese News API Test Suite")
    print("="*60)
    
    # Test 1: Multiple tickers
    test_multiple_tickers()
    
    # Test 2: Native API
    test_native_api()
    
    # Test 3: Combined tickers
    test_multiple_tickers_combined()
    
    print(f"\n{'='*60}")
    print("✅ All tests completed!")
    print("="*60)


if __name__ == "__main__":
    main()

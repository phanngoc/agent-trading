"""trend_news API integration for Vietnamese market news with sentiment analysis."""

import requests
from datetime import datetime, timedelta
from typing import Optional

# Import config to get API URL
from .config import get_config


# ---------------------------------------------------------------------------
# Vietnamese ticker map — built dynamically from ticker_mapper module.
# Supports both 'VIC.VN' and bare 'VIC' lookups.
# ---------------------------------------------------------------------------

def _build_vn_ticker_map() -> dict:
    """
    Build VIETNAMESE_TICKER_MAP by importing from trend_news ticker_mapper.
    Returns a dict of {TICKER.VN: [aliases...]} for all supported tickers.
    Falls back to a minimal static map if the import fails.
    """
    import os, sys
    _root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "trend_news")
    )
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from src.core.ticker_mapper import TICKER_ALIASES
        result = {}
        for ticker, aliases in TICKER_ALIASES.items():
            # Register both 'VIC.VN' and bare 'VIC' keys
            if not ticker.isupper() or len(ticker) > 6:
                continue  # skip sector keys
            result[f"{ticker}.VN"] = aliases
            result[ticker] = aliases
        return result
    except ImportError:
        # Minimal fallback
        return {
            "VIC.VN": ["Vingroup", "VIC"], "VIC": ["Vingroup", "VIC"],
            "HPG.VN": ["Hòa Phát", "HPG"], "HPG": ["Hòa Phát", "HPG"],
            "VNM.VN": ["Vinamilk", "VNM"], "VNM": ["Vinamilk", "VNM"],
            "VCB.VN": ["Vietcombank", "VCB"], "VCB": ["Vietcombank", "VCB"],
            "MWG.VN": ["Thế Giới Di Động", "MWG"], "MWG": ["Thế Giới Di Động", "MWG"],
            "FPT.VN": ["FPT", "FPT Corporation"], "FPT": ["FPT", "FPT Corporation"],
        }

VIETNAMESE_TICKER_MAP = _build_vn_ticker_map()

# Default API URL (can be overridden by config)
DEFAULT_API_URL = "http://localhost:8000"


def _format_datetime_for_trend_api(date_str: str) -> str:
    """
    Convert yyyy-mm-dd format to YYYYMMDDTHHMM format for trend_news API.
    
    Args:
        date_str: Date string in yyyy-mm-dd format
        
    Returns:
        Formatted date string in YYYYMMDDTHHMM format
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y%m%dT%H%M")
    except ValueError:
        return date_str


def _parse_trend_api_time(time_str: str) -> str:
    """
    Parse time from trend_news API format to readable format.
    
    Args:
        time_str: Time string from API (e.g., "20260213T123000" or ISO format)
        
    Returns:
        Readable datetime string
    """
    try:
        # Try compact format first (YYYYMMDDTHHMMSS)
        if 'T' in time_str and len(time_str.replace('T', '')) >= 12:
            dt = datetime.strptime(time_str[:15], "%Y%m%dT%H%M%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    
    try:
        # Try ISO format
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        pass
    
    return time_str


def _get_search_terms_for_ticker(ticker: str) -> Optional[str]:
    """
    Return the primary company name for a Vietnamese ticker (used in HTTP API calls).

    Strips exchange suffixes (.VN, .HNX) before lookup.

    Args:
        ticker: Stock ticker (e.g. 'VIC', 'VIC.VN')

    Returns:
        Primary company name string, or None if not found
    """
    ticker_upper = ticker.upper()
    aliases = VIETNAMESE_TICKER_MAP.get(ticker_upper)
    if aliases:
        return aliases[0]

    # Try bare ticker without suffix
    ticker_base = ticker_upper.split(".")[0]
    aliases = VIETNAMESE_TICKER_MAP.get(ticker_base)
    if aliases:
        return aliases[0]

    return None


def _call_trend_news_api(
    api_url: str,
    tickers: Optional[str] = None,
    time_from: Optional[str] = None,
    time_to: Optional[str] = None,
    limit: int = 50,
    topics: Optional[str] = None,
) -> dict:
    """
    Call trend_news API endpoint.
    
    Args:
        api_url: Base API URL
        tickers: Ticker symbol or search term
        time_from: Start time in YYYYMMDDTHHMM format
        time_to: End time in YYYYMMDDTHHMM format
        limit: Maximum number of results
        topics: Topics to filter by
        
    Returns:
        API response dictionary
    """
    params = {
        "function": "NEWS_SENTIMENT",
        "limit": limit,
    }
    
    if tickers:
        params["tickers"] = tickers
    if time_from:
        params["time_from"] = time_from
    if time_to:
        params["time_to"] = time_to
    if topics:
        params["topics"] = topics
    
    try:
        response = requests.get(f"{api_url}/query", params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e), "feed": []}


def get_news(
    ticker: str,
    start_date: str,
    end_date: str,
    api_url: str = None,
) -> str:
    """
    Retrieve news for a specific stock ticker using trend_news API.
    
    This function fetches Vietnamese market news with sentiment analysis
    from the trend_news database.
    
    Args:
        ticker: Stock ticker symbol (e.g., "VIC.VN")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format
        api_url: trend_news API base URL (default: from config or http://localhost:8000)
        
    Returns:
        Formatted string containing news articles with sentiment scores
    """
    # Get API URL from config if not provided
    if api_url is None:
        config = get_config()
        api_url = config.get("trend_news_api_url", DEFAULT_API_URL)
    # Map ticker to Vietnamese company name
    search_term = _get_search_terms_for_ticker(ticker)
    
    if not search_term:
        return f"No Vietnamese company mapping found for ticker {ticker}. " \
               f"This ticker may not be supported by trend_news API. " \
               f"Currently supported: {', '.join(VIETNAMESE_TICKER_MAP.keys())}"
    
    # Format dates for API
    time_from = _format_datetime_for_trend_api(start_date)
    time_to = _format_datetime_for_trend_api(end_date)
    
    # Call API
    response = _call_trend_news_api(
        api_url=api_url,
        tickers=search_term,
        time_from=time_from,
        time_to=time_to,
        limit=50,
    )
    
    # Handle errors
    if "error" in response:
        return f"Error fetching news from trend_news API: {response['error']}\n" \
               f"Make sure the trend_news server is running at {api_url}"
    
    feed = response.get("feed", [])
    
    if not feed:
        return f"No news found for {ticker} ({search_term}) between {start_date} and {end_date} " \
               f"from Vietnamese sources."
    
    # Format news as markdown string (similar to yfinance format)
    news_str = f"## {ticker} News from Vietnamese Sources, {start_date} to {end_date}:\n"
    news_str += f"**Company**: {search_term}\n"
    news_str += f"**Total Articles**: {len(feed)}\n\n"
    
    for item in feed:
        title = item.get("title", "No title")
        url = item.get("url", "")
        source = item.get("source", "Unknown")
        summary = item.get("summary", "")
        
        # Sentiment information
        sentiment_score = item.get("overall_sentiment_score", 0.0)
        sentiment_label = item.get("overall_sentiment_label", "Neutral")
        
        # Time information
        time_published = item.get("time_published", "")
        if time_published:
            time_published = _parse_trend_api_time(time_published)
        
        # Format sentiment indicator
        sentiment_indicator = f"**[Sentiment: {sentiment_label} ({sentiment_score:.2f})]**"
        
        # Build article string
        news_str += f"### {title}\n"
        news_str += f"{sentiment_indicator}\n"
        news_str += f"**Source**: {source}\n"
        
        if time_published:
            news_str += f"**Published**: {time_published}\n"
        
        if summary and summary != "No summary":
            news_str += f"**Summary**: {summary}\n"
        
        if url:
            news_str += f"**Link**: {url}\n"
        
        news_str += "\n"
    
    return news_str


def get_global_news(
    curr_date: str,
    look_back_days: int = 7,
    limit: int = 50,
    api_url: str = None,
) -> str:
    """
    Retrieve global Vietnamese market news without ticker-specific filtering.
    
    This function fetches broad market news from Vietnamese sources
    with sentiment analysis.
    
    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back (default 7)
        limit: Maximum number of articles (default 50)
        api_url: trend_news API base URL (default: from config or http://localhost:8000)
        
    Returns:
        Formatted string containing global news articles with sentiment scores
    """
    # Get API URL from config if not provided
    if api_url is None:
        config = get_config()
        api_url = config.get("trend_news_api_url", DEFAULT_API_URL)
    # Calculate start date
    try:
        curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        start_dt = curr_dt - timedelta(days=look_back_days)
        start_date = start_dt.strftime("%Y-%m-%d")
    except ValueError:
        return f"Invalid date format: {curr_date}. Expected yyyy-mm-dd"
    
    # Format dates for API
    time_from = _format_datetime_for_trend_api(start_date)
    time_to = _format_datetime_for_trend_api(curr_date)
    
    # Call API without ticker filter to get all Vietnamese market news
    response = _call_trend_news_api(
        api_url=api_url,
        time_from=time_from,
        time_to=time_to,
        limit=limit,
    )
    
    # Handle errors
    if "error" in response:
        return f"Error fetching global news from trend_news API: {response['error']}\n" \
               f"Make sure the trend_news server is running at {api_url}"
    
    feed = response.get("feed", [])
    
    if not feed:
        return f"No global news found between {start_date} and {curr_date} " \
               f"from Vietnamese sources."
    
    # Format news as markdown string
    news_str = f"## Vietnamese Market News, {start_date} to {curr_date}:\n"
    news_str += f"**Total Articles**: {len(feed)}\n"
    news_str += f"**Period**: Last {look_back_days} days\n\n"
    
    # Group by source for better organization
    sources = {}
    for item in feed:
        source = item.get("source", "Unknown")
        if source not in sources:
            sources[source] = []
        sources[source].append(item)
    
    news_str += f"**Sources**: {', '.join(sources.keys())}\n\n"
    
    # Format articles
    for item in feed:
        title = item.get("title", "No title")
        url = item.get("url", "")
        source = item.get("source", "Unknown")
        summary = item.get("summary", "")
        
        # Sentiment information
        sentiment_score = item.get("overall_sentiment_score", 0.0)
        sentiment_label = item.get("overall_sentiment_label", "Neutral")
        
        # Time information
        time_published = item.get("time_published", "")
        if time_published:
            time_published = _parse_trend_api_time(time_published)
        
        # Trending rank information
        ranks = summary.replace("Ranked: ", "") if "Ranked:" in summary else ""
        
        # Format sentiment indicator
        sentiment_indicator = f"**[Sentiment: {sentiment_label} ({sentiment_score:.2f})]**"
        
        # Build article string
        news_str += f"### {title}\n"
        news_str += f"{sentiment_indicator}\n"
        news_str += f"**Source**: {source}\n"
        
        if time_published:
            news_str += f"**Published**: {time_published}\n"
        
        if ranks:
            news_str += f"**Trending Ranks**: {ranks}\n"
        
        if url:
            news_str += f"**Link**: {url}\n"
        
        news_str += "\n"
    
    return news_str


# Alias for compatibility if needed
get_trend_news = get_news
get_trend_global_news = get_global_news

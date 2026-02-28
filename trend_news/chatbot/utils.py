"""Shared utility helpers for the chatbot."""

import re
import sys
import os
from datetime import datetime
from typing import List, Dict, Any

# Ensure trend_news src is importable
_TREND_NEWS_DIR = os.path.dirname(os.path.dirname(__file__))
if _TREND_NEWS_DIR not in sys.path:
    sys.path.insert(0, _TREND_NEWS_DIR)

from src.core.ticker_mapper import TICKER_ALIASES, SECTOR_MAP

# --- Vietnamese sector keywords → canonical sector name ---
SECTOR_KEYWORDS: Dict[str, str] = {
    "ngân hàng": "banking",
    "bank": "banking",
    "bất động sản": "real_estate",
    "bdss": "real_estate",
    "chứng khoán": "securities",
    "securities": "securities",
    "thép": "steel",
    "steel": "steel",
    "dầu khí": "oil_gas",
    "dau khi": "oil_gas",
    "công nghệ": "technology",
    "tech": "technology",
    "hàng không": "aviation",
    "hàng tiêu dùng": "consumer",
    "dược": "pharma",
    "pharma": "pharma",
    "điện": "energy",
    "năng lượng": "energy",
    "thực phẩm": "food",
    "food": "food",
    "viễn thông": "telecom",
    "bảo hiểm": "insurance",
}

# All ticker symbols as a set for O(1) lookup
_ALL_TICKERS = set(TICKER_ALIASES.keys())


def extract_tickers_from_query(query: str) -> str:
    """
    Detect Vietnamese stock ticker symbols and sector names in a free-text query.
    Returns comma-separated ticker string suitable for DatabaseManager.get_filtered_news().

    Examples:
        "Tin tức VIC hôm nay" → "VIC"
        "Ngành ngân hàng có gì mới VCB TCB" → "VCB,TCB"
        "thị trường chứng khoán" → ""
    """
    tickers_found: List[str] = []

    # 1. Direct ticker match (2-4 uppercase letters, word boundary)
    potential_tickers = re.findall(r"\b([A-Z]{2,4})\b", query.upper())
    for t in potential_tickers:
        if t in _ALL_TICKERS:
            tickers_found.append(t)

    # 2. Sector keyword match → find representative tickers (first 3 of sector)
    query_lower = query.lower()
    for keyword, sector in SECTOR_KEYWORDS.items():
        if keyword in query_lower:
            sector_tickers = SECTOR_MAP.get(sector, [])
            for t in sector_tickers[:3]:
                if t not in tickers_found:
                    tickers_found.append(t)
            break  # use first matching sector only

    return ",".join(dict.fromkeys(tickers_found))  # deduplicate, preserve order


def format_news_for_prompt(articles: List[Dict], max_items: int = 10) -> str:
    """Format ranked news articles into a string suitable for LLM system prompt."""
    if not articles:
        return "Không có tin tức nào."

    from chatbot.prompts import NEWS_ITEM_FORMAT, SENTIMENT_ICONS

    lines = []
    for i, article in enumerate(articles[:max_items], 1):
        label = article.get("sentiment_label") or "Neutral"
        icon = SENTIMENT_ICONS.get(label, "⚪")
        crawled_at = article.get("crawled_at") or article.get("crawl_date") or ""
        # Shorten datetime for prompt
        if "T" in str(crawled_at):
            crawled_at = crawled_at[:16].replace("T", " ")

        lines.append(
            NEWS_ITEM_FORMAT.format(
                rank=i,
                sentiment_icon=icon,
                source=article.get("source_id", "unknown"),
                title=article.get("title", ""),
                date=crawled_at,
                sentiment_label=label,
                url=article.get("url") or article.get("mobile_url") or "",
            )
        )
    return "\n".join(lines)


def parse_mem0_results(results: List[Dict]) -> Dict[str, Any]:
    """
    Parse mem0 search results into a structured preferences dict.
    mem0 returns: [{"memory": "text", "score": float, ...}, ...]
    """
    preferences: Dict[str, Any] = {
        "sectors": [],
        "tickers": [],
        "topics": [],
        "sentiment_bias": None,
        "raw_memories": [],
    }

    for result in results:
        text = result.get("memory", "").lower()
        preferences["raw_memories"].append(result.get("memory", ""))

        # Extract tickers
        found_tickers = re.findall(r"\b([A-Z]{2,4})\b", text.upper())
        for t in found_tickers:
            if t in _ALL_TICKERS and t not in preferences["tickers"]:
                preferences["tickers"].append(t)

        # Extract sectors
        for kw, sector in SECTOR_KEYWORDS.items():
            if kw in text and sector not in preferences["sectors"]:
                preferences["sectors"].append(sector)

        # Extract sentiment bias
        if any(w in text for w in ["tăng", "bullish", "tích cực", "mua"]):
            preferences["sentiment_bias"] = "bullish"
        elif any(w in text for w in ["giảm", "bearish", "tiêu cực", "bán"]):
            preferences["sentiment_bias"] = "bearish"

    return preferences


def parse_cognee_results(cognee_output: Any) -> List[Dict]:
    """
    Normalize Cognee search results to the same dict schema as news_articles rows.

    Cognee 0.5.x returns a list of result objects. Each object has:
        .search_result — either:
            List[dict]  for CHUNKS    → each dict has 'text' (article text)
            List[str]   for GRAPH_COMPLETION / RAG_COMPLETION → narrative strings

    Legacy / plain string formats are also handled.
    """
    articles = []
    if not cognee_output:
        return articles

    items = cognee_output if isinstance(cognee_output, list) else [cognee_output]

    for item in items:
        # --- Case 1: plain string (legacy) ---
        if isinstance(item, str):
            article = _parse_structured_text(item)
            if article:
                articles.append(article)
            elif len(item.strip()) > 20:
                articles.append(_make_narrative_article(item))

        # --- Case 2: Cognee 0.5.x result object with search_result ---
        else:
            # Supports both dict-with-key and object-with-attribute
            if isinstance(item, dict):
                sr = item.get("search_result")
            elif hasattr(item, "search_result"):
                sr = item.search_result
            else:
                sr = None

            if sr is not None:
                chunks = sr if isinstance(sr, list) else [sr]
                for chunk in chunks:
                    if isinstance(chunk, dict):
                        # CHUNKS format: dict with 'text' key containing article text
                        text = chunk.get("text") or chunk.get("content", "")
                        if text:
                            parsed = _parse_structured_text(str(text))
                            articles.append(parsed if parsed else _make_narrative_article(str(text)))
                    elif isinstance(chunk, str) and chunk.strip():
                        # GRAPH_COMPLETION / RAG_COMPLETION: narrative string
                        parsed = _parse_structured_text(chunk)
                        articles.append(parsed if parsed else _make_narrative_article(chunk))

            # --- Case 3: plain dict without search_result ---
            elif isinstance(item, dict):
                text = item.get("text") or item.get("title", "")
                if text:
                    parsed = _parse_structured_text(str(text))
                    if parsed:
                        articles.append(parsed)
                    else:
                        articles.append({
                            "title": str(text)[:400],
                            "source_id": item.get("source_id", "cognee"),
                            "url": item.get("url", ""),
                            "crawled_at": item.get("crawled_at", ""),
                            "sentiment_score": item.get("sentiment_score"),
                            "sentiment_label": item.get("sentiment_label"),
                        })

    return articles


def _make_narrative_article(text: str) -> Dict:
    """Wrap a plain narrative string into the standard article dict schema."""
    return {
        "title": text.strip()[:400],
        "source_id": "cognee",
        "url": "",
        "crawled_at": "",
        "sentiment_score": None,
        "sentiment_label": None,
    }


def _parse_structured_text(text: str) -> Dict | None:
    """
    Parse our structured article text format back into a dict:
    'TIN TỨC TÀI CHÍNH: [{source}] {date}\\nTiêu đề: {title}\\nCảm xúc: ...\\nNguồn: {url}'
    """
    if not text or "Tiêu đề:" not in text:
        return None

    article: Dict[str, Any] = {
        "source_id": "unknown",
        "title": "",
        "url": "",
        "crawled_at": "",
        "sentiment_score": 0.0,
        "sentiment_label": "Neutral",
    }

    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith("TIN TỨC TÀI CHÍNH:"):
            # Extract source_id and date from header
            m = re.search(r"\[([^\]]+)\]\s*([\d-]+)", line)
            if m:
                article["source_id"] = m.group(1)
                article["crawled_at"] = m.group(2)
        elif line.startswith("Tiêu đề:"):
            article["title"] = line[len("Tiêu đề:"):].strip()
        elif line.startswith("Nguồn:"):
            article["url"] = line[len("Nguồn:"):].strip()
        elif line.startswith("Cảm xúc"):
            m = re.search(r"(Bullish|Bearish|Neutral|Somewhat-Bullish|Somewhat-Bearish)\s*\(([^)]+)\)", line)
            if m:
                article["sentiment_label"] = m.group(1)
                try:
                    article["sentiment_score"] = float(m.group(2))
                except ValueError:
                    pass

    return article if article["title"] else None

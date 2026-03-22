"""
GroqSummarizer — LLM-powered article summarization using Groq API.

Free tier: 14,400 requests/day (more than enough for trend_news).
Caches by content-hash to avoid repeat calls.

Ported summarization pattern from:
  worldmonitor/server/worldmonitor/news/v1/summarize-article.ts
"""

import hashlib
import json
import os
import time
from typing import Dict, List, Optional

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"   # fast + free tier

# Simple in-process cache {hash: result}
_SUMMARY_CACHE: Dict[str, str] = {}


def _hash_headlines(headlines: List[str]) -> str:
    return hashlib.sha256("|".join(h.lower().strip() for h in headlines).encode()).hexdigest()[:16]


class GroqSummarizer:
    """
    Summarize news articles with global context using Groq (llama-3.3-70b).

    Usage:
        summarizer = GroqSummarizer(api_key="gsk_...")
        summary = summarizer.summarize_with_context(
            vn_headlines=["VnIndex tăng 15 điểm..."],
            global_context=["China imposes new tariffs..."],
        )
        signal = summarizer.classify_market_impact(article_dict)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = GROQ_MODEL,
        max_tokens: int = 150,
        timeout: int = 20,
    ):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

        if not self.api_key:
            print("⚠ GroqSummarizer: No GROQ_API_KEY — summaries will be skipped")

    def _call(self, system: str, user: str) -> Optional[str]:
        """Make a single Groq API call."""
        if not self.api_key:
            return None
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                    "max_tokens": self.max_tokens,
                    "top_p": 0.9,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return content if len(content) > 10 else None
        except Exception as e:
            print(f"  ✗ Groq API error: {e}")
            return None

    def summarize_with_context(
        self,
        vn_headlines: List[str],
        global_context: Optional[List[str]] = None,
        lang: str = "vi",
    ) -> Optional[str]:
        """
        Summarize VN headlines with optional global context injected.

        Args:
            vn_headlines:   List of Vietnamese article titles
            global_context: Related global headlines from WorldMonitor
            lang:           Output language: "vi" or "en"

        Returns:
            2-3 sentence summary, or None if Groq unavailable.
        """
        if not vn_headlines:
            return None

        cache_key = _hash_headlines(vn_headlines + (global_context or []))
        if cache_key in _SUMMARY_CACHE:
            return _SUMMARY_CACHE[cache_key]

        # Build prompt
        context_block = ""
        if global_context:
            context_block = "\n\nGlobal context (for background, do NOT translate):\n" + \
                "\n".join(f"- {h}" for h in global_context[:5])

        if lang == "vi":
            system = (
                "Bạn là chuyên gia phân tích tài chính và kinh tế Việt Nam. "
                "Tóm tắt các tin tức VN bằng tiếng Việt ngắn gọn (2-3 câu), "
                "nêu rõ tác động đến thị trường chứng khoán hoặc kinh tế Việt Nam. "
                "Không dịch tin tức quốc tế, chỉ dùng làm ngữ cảnh."
            )
            user = (
                f"Tin tức Việt Nam:\n" +
                "\n".join(f"- {h}" for h in vn_headlines[:8]) +
                context_block +
                "\n\nTóm tắt tác động:"
            )
        else:
            system = (
                "You are a financial analyst specializing in Vietnam markets. "
                "Summarize the Vietnamese news in English (2-3 sentences), "
                "focusing on market impact and economic implications."
            )
            user = (
                f"Vietnamese news:\n" +
                "\n".join(f"- {h}" for h in vn_headlines[:8]) +
                context_block +
                "\n\nSummary:"
            )

        result = self._call(system, user)
        if result:
            _SUMMARY_CACHE[cache_key] = result
        return result

    def classify_market_impact(self, article: Dict) -> str:
        """
        Classify market impact of a single article: bullish / bearish / neutral.
        Uses Groq for ambiguous cases, keyword heuristic for clear ones.
        """
        title = article.get("title", "")
        if not title:
            return "neutral"

        # Fast keyword check first (save API calls)
        lower = title.lower()
        bearish_words = ["giảm", "sụt", "mất", "lao dốc", "rớt", "khủng hoảng",
                         "fall", "drop", "crash", "decline", "recession", "war", "sanction"]
        bullish_words = ["tăng", "bứt phá", "lên", "hồi phục", "tăng trưởng",
                         "rally", "surge", "gain", "growth", "recovery", "deal"]

        bear_count = sum(1 for w in bearish_words if w in lower)
        bull_count = sum(1 for w in bullish_words if w in lower)

        if bull_count > bear_count + 1:
            return "bullish"
        if bear_count > bull_count + 1:
            return "bearish"

        # Ambiguous — ask Groq
        cache_key = "mkt:" + _hash_headlines([title])
        if cache_key in _SUMMARY_CACHE:
            return _SUMMARY_CACHE[cache_key]

        system = (
            "Classify the market impact of this news headline as exactly one word: "
            "bullish, bearish, or neutral. Reply with only the word."
        )
        result = self._call(system, f'Headline: "{title}"')
        signal = (result or "neutral").strip().lower()
        if signal not in ("bullish", "bearish", "neutral"):
            signal = "neutral"

        _SUMMARY_CACHE[cache_key] = signal
        return signal

    def enrich_article(self, article: Dict) -> Dict:
        """
        Add groq_summary and groq_market_signal to an enriched article.
        Uses global_context already attached by ArticleEnricher.
        """
        enriched = dict(article)
        global_ctx = [c["title"] for c in article.get("global_context", [])]

        enriched["groq_summary"] = self.summarize_with_context(
            vn_headlines=[article.get("title", "")],
            global_context=global_ctx,
            lang="vi",
        )
        enriched["groq_market_signal"] = self.classify_market_impact(article)
        return enriched

    def enrich_batch(
        self,
        articles: List[Dict],
        delay_between: float = 0.1,
    ) -> List[Dict]:
        """
        Enrich a batch of articles with Groq summaries.
        Adds small delay to respect rate limits (14,400/day = ~10/min safe pace).
        """
        results = []
        for i, art in enumerate(articles):
            results.append(self.enrich_article(art))
            if delay_between and i < len(articles) - 1:
                time.sleep(delay_between)
        return results

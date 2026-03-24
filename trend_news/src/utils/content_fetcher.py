"""
Article content fetcher — async batch fetching with source-specific CSS selectors.

Usage:
    fetcher = ContentFetcher()
    text = fetcher.fetch_article_content(url, source_id)

    # Async batch
    import asyncio
    results = asyncio.run(fetcher.fetch_batch([(id, url, source_id), ...]))
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

MAX_CONTENT_LEN = 2000
TIMEOUT = 8
RETRY = 1

# CSS selectors per source_id prefix → ordered by priority
SELECTORS: Dict[str, List[str]] = {
    "cafef":              [".detail-content", ".contentdetail", ".detail-cmain", ".fck_detail"],
    "vnexpress":          [".description", ".Normal", ".article-body", ".fck_detail"],
    "vietnambiz":         [".cms-body", ".article__body", ".content-detail"],
    "tinnhanhchungkhoan": [".content-news-detail", ".article-body", ".fck_detail"],
    "24hmoney":           [".article-content", ".entry-content", ".post-content"],
    "baodautu":           [".content-detail", ".article-content", ".fck_detail"],
    "vneconomy":          [".detail-content", ".article__body", ".article-content"],
    "vietnamfinance":     [".article-content", ".content-detail", ".fck_detail"],
    "dantri":             [".singular-content", ".article-content"],
    # CN sources
    "wallstreetcn":       ["[class*='_articleBody']", ".article__content", ".live-detail__body", "[class*='articleBody']", ".p-\\[15px\\]"],
    "cls":                [".article-content", ".detail-content", "article"],
    "jin10":              [".flash-detail", ".jin-layout", ".jin-detail", ".article-content", "article"],
}

FALLBACK_SELECTORS = ["article", "main", ".article", ".content", ".post", "[class*='article']", "[class*='content']"]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}


_CN_NAV_NOISE = re.compile(r"^首页\s*[^\n]{0,60}分享[：:][^\n]{0,30}\n?")

def _clean_cn_noise(text: str) -> str:
    """Remove jin10/cn navigation prefix noise."""
    text = _CN_NAV_NOISE.sub("", text)
    # Remove timestamps like "2026-02-15 周日 12:54:05"
    text = re.sub(r"\d{4}-\d{2}-\d{2}\s+\w+\s+\d{2}:\d{2}:\d{2}\s*", "", text)
    return text.strip()


def _extract_text(html: str, source_id: str) -> str:
    """Extract article body text from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
        tag.decompose()

    # Try source-specific selectors
    prefix = source_id.split("-")[0]  # "cafef-chungkhoan" → "cafef"
    selectors = SELECTORS.get(source_id, SELECTORS.get(prefix, []))

    for sel in selectors + FALLBACK_SELECTORS:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 100:
                # Clean CN navigation noise for CN sources
                if any(s in source_id for s in ["jin10", "wallstreetcn", "cls", "zaobao", "gelonghui"]):
                    text = _clean_cn_noise(text)
                return text[:MAX_CONTENT_LEN]

    # Last resort: find the tag with most text
    candidates = [(len(tag.get_text(strip=True)), tag) for tag in soup.find_all(["div", "section", "article"])]
    if candidates:
        _, best = max(candidates, key=lambda x: x[0])
        text = best.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 100:
            return text[:MAX_CONTENT_LEN]

    return ""


class ContentFetcher:
    """Sync + async article content fetcher."""

    def fetch_article_content(self, url: str, source_id: str, timeout: int = TIMEOUT) -> str:
        """
        Fetch full article body text. Returns plain text, max 2000 chars.
        Returns empty string on failure.
        """
        if not url or not url.startswith("http"):
            return ""

        for attempt in range(RETRY + 1):
            try:
                resp = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
                resp.raise_for_status()
                # Force UTF-8 for CN sources that send wrong charset header
                if any(src in source_id for src in ["wallstreetcn", "cls", "jin10", "gelonghui", "zaobao", "cankaoxiaoxi", "thepaper", "kaopu", "sputniknewscn"]):
                    resp.encoding = "utf-8"
                else:
                    resp.encoding = resp.apparent_encoding or "utf-8"
                return _extract_text(resp.text, source_id)
            except requests.exceptions.Timeout:
                if attempt < RETRY:
                    time.sleep(1)
            except Exception:
                break

        return ""

    async def fetch_batch(
        self,
        articles: List[Tuple[int, str, str]],
        concurrency: int = 5,
    ) -> Dict[int, str]:
        """
        Async batch fetch article content.

        Args:
            articles: list of (article_id, url, source_id)
            concurrency: max parallel requests

        Returns:
            {article_id: content_text}
        """
        try:
            import aiohttp
        except ImportError:
            # Fallback to sync
            return {aid: self.fetch_article_content(url, src) for aid, url, src in articles}

        sem = asyncio.Semaphore(concurrency)
        results: Dict[int, str] = {}

        async def _fetch_one(session: aiohttp.ClientSession, aid: int, url: str, source_id: str) -> None:
            if not url or not url.startswith("http"):
                return
            async with sem:
                for attempt in range(RETRY + 1):
                    try:
                        async with session.get(url, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as resp:
                            html = await resp.text(errors="replace")
                            text = _extract_text(html, source_id)
                            if text:
                                results[aid] = text
                            return
                    except asyncio.TimeoutError:
                        if attempt < RETRY:
                            await asyncio.sleep(1)
                    except Exception:
                        break

        connector = aiohttp.TCPConnector(limit=concurrency, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [_fetch_one(session, aid, url, src) for aid, url, src in articles]
            await asyncio.gather(*tasks, return_exceptions=True)

        return results


# Module-level singleton
_fetcher: Optional[ContentFetcher] = None


def get_fetcher() -> ContentFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = ContentFetcher()
    return _fetcher

"""
article_fetcher.py — Robust async article content extractor.

Architecture (3-layer waterfall per article):

  Layer 1 — Site-specific CSS selector  (fast, zero extra CPU)
             Keyed by domain prefix from source_id.
             Handles the 9 known Vietnamese news domains perfectly.

  Layer 2 — trafilatura universal extraction  (handles 1000+ sites)
             Uses the same HTML already fetched in Layer 1.
             Removes ads/nav/boilerplate automatically.
             Falls back gracefully on unknown domains.

  Layer 3 — <p>-tag heuristic  (last resort)
             Concatenates <p> tags with >40 chars.
             Always returns *something* rather than empty string.

Public API:
    await fetch_articles_batch(articles, max_fetch=5, max_concurrent=3)
    → returns the same list with 'full_content' key added to each article.

In-process URL cache avoids re-fetching the same URL within a session.
"""

import asyncio
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Site-specific CSS selectors keyed by domain prefix.
# The prefix is derived from source_id before the first '-'.
# E.g. "vnexpress-chungkhoan" → "vnexpress"
# ---------------------------------------------------------------------------

SITE_SELECTORS: Dict[str, List[str]] = {
    "vnexpress": [
        ".fck_detail",
        ".article-body",
        "article .content-detail",
    ],
    "cafef": [
        ".detail-content",
        ".afcbc-body",
        ".knc-content",
    ],
    "dantri": [
        ".dt-news__content",
        ".singular-content",
        "article .content-detail",
    ],
    "24hmoney": [
        ".post-body",
        ".article-body",
        ".content-body",
    ],
    "vneconomy": [
        ".detail__content",
        ".article-body",
        ".fck_detail",
    ],
    "baodautu": [
        ".detail-content",
        ".news-content",
        ".article-content",
    ],
    "vietnamfinance": [
        ".article-body",
        ".entry-content",
        ".post-content",
    ],
    "vietnambiz": [
        ".content-detail",
        ".article__body",
        "article .detail-content",
    ],
    "tinnhanhchungkhoan": [
        ".detail-content-body",
        ".article-body",
        ".content-detail",
    ],
    "cafebiz": [
        ".detail-content",
        ".afcbc-body",
    ],
    "ndh": [
        ".article-body",
        ".fck_detail",
    ],
    "stockbiz": [
        ".content-detail",
        ".article-content",
    ],
}

# Selectors tried as final generic fallback when domain is unknown
_GENERIC_SELECTORS: List[str] = [
    "[itemprop='articleBody']",
    ".article-body",
    ".article-content",
    ".detail-content",
    ".content-detail",
    ".fck_detail",
    ".article__body",
    ".post-content",
    ".entry-content",
    "article",
]

_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}

# In-process cache: url → content  (cleared on process restart — intentional)
_content_cache: Dict[str, str] = {}

_MIN_CONTENT_CHARS = 150  # below this → consider extraction failed, try next layer


def _domain_prefix(source_id: str) -> str:
    """'vnexpress-chungkhoan' → 'vnexpress'."""
    return source_id.split("-")[0] if source_id else ""


def _extract_layer1(html: str, source_id: str) -> str:
    """Layer 1: site-specific CSS selector extraction via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                         "figure", "figcaption", "iframe", "noscript", "form"]):
            tag.decompose()

        domain = _domain_prefix(source_id)
        selectors = SITE_SELECTORS.get(domain, []) + _GENERIC_SELECTORS

        for selector in selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) >= _MIN_CONTENT_CHARS:
                    return _clean_text(text)

    except Exception:
        pass
    return ""


def _extract_layer2(html: str, url: str) -> str:
    """Layer 2: trafilatura universal extraction."""
    try:
        import trafilatura

        text = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            favor_recall=True,          # prefer more text on short VN articles
            target_language=None,       # don't discard Vietnamese documents
            deduplicate=True,
        )
        if text and len(text) >= _MIN_CONTENT_CHARS:
            return _clean_text(text)
    except Exception:
        pass
    return ""


def _extract_layer3(html: str) -> str:
    """Layer 3: <p>-tag heuristic — last resort."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        paragraphs = [
            p.get_text(strip=True)
            for p in soup.find_all("p")
            if len(p.get_text(strip=True)) > 40
        ]
        text = "\n".join(paragraphs)
        if len(text) >= _MIN_CONTENT_CHARS:
            return _clean_text(text)
    except Exception:
        pass
    return ""


def _clean_text(text: str) -> str:
    """Collapse excessive blank lines and strip trailing whitespace."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def _extract_content(html: str, url: str, source_id: str) -> str:
    """
    Run the 3-layer waterfall and return the best non-empty result.
    """
    result = _extract_layer1(html, source_id)
    if result:
        return result

    result = _extract_layer2(html, url)
    if result:
        return result

    return _extract_layer3(html)


async def _fetch_one(session, article: Dict, semaphore: asyncio.Semaphore) -> str:
    """
    Fetch a single article URL and extract its main text content.
    Uses in-process cache to avoid duplicate fetches within a session.
    """
    url: str = article.get("url") or article.get("mobile_url") or ""
    source_id: str = article.get("source_id", "")

    if not url:
        return ""

    # Cache hit
    if url in _content_cache:
        return _content_cache[url]

    try:
        import aiohttp

        async with semaphore:
            timeout = aiohttp.ClientTimeout(total=12, connect=5)
            async with session.get(url, headers=_FETCH_HEADERS, timeout=timeout,
                                   allow_redirects=True, max_redirects=5) as resp:
                if resp.status != 200:
                    # Try mobile_url as fallback if desktop URL fails
                    mobile = article.get("mobile_url") or ""
                    if mobile and mobile != url:
                        async with session.get(mobile, headers=_FETCH_HEADERS,
                                               timeout=timeout, allow_redirects=True) as r2:
                            if r2.status != 200:
                                return ""
                            html = await r2.text(errors="replace")
                    else:
                        return ""
                else:
                    html = await resp.text(errors="replace")

        content = await asyncio.to_thread(_extract_content, html, url, source_id)
        _content_cache[url] = content
        return content

    except asyncio.TimeoutError:
        print(f"[Fetcher] Timeout: {url}")
        return ""
    except Exception as exc:
        print(f"[Fetcher] Error fetching {url}: {exc}")
        return ""


async def fetch_articles_batch(
    articles: List[Dict],
    max_fetch: int = 5,
    max_concurrent: int = 3,
) -> List[Dict]:
    """
    Concurrently fetch full article content for up to `max_fetch` articles.

    Modifies articles in-place adding 'full_content' key, and also returns
    the modified list for convenience.

    Args:
        articles:       List of article dicts (must have 'url' and 'source_id').
        max_fetch:      Maximum number of articles to fetch (top N by rank).
        max_concurrent: Max simultaneous HTTP connections.

    Returns:
        The same list with 'full_content' populated on the first max_fetch items.
    """
    import aiohttp

    to_fetch = articles[:max_fetch]
    if not to_fetch:
        return articles

    semaphore = asyncio.Semaphore(max_concurrent)
    connector = aiohttp.TCPConnector(ssl=False, limit=max_concurrent)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [_fetch_one(session, a, semaphore) for a in to_fetch]
        contents = await asyncio.gather(*tasks)

    for article, content in zip(to_fetch, contents):
        article["full_content"] = content

    return articles

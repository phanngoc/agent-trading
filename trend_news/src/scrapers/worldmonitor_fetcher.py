"""
WorldMonitor RSS Fetcher for TrendNews.

Fetches global news from WorldMonitor's curated RSS feed list.
Adds threat classification using keyword patterns ported from
worldmonitor/server/worldmonitor/news/v1/_classifier.ts

Output format is identical to BaseScraper.fetch() so it plugs directly
into the existing pipeline.
"""

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

import requests

# ── Feed definitions ─────────────────────────────────────────────────────────

def _gn(query: str, lang: str = "en", country: str = "US") -> str:
    """Build a Google News RSS URL from a search query."""
    from urllib.parse import quote
    return (
        f"https://news.google.com/rss/search?q={quote(query)}"
        f"&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
    )


WORLDMONITOR_FEEDS: Dict[str, List[Tuple[str, str]]] = {
    # Asia — directly relevant to Vietnam
    "asia": [
        ("BBC Asia",        "https://feeds.bbci.co.uk/news/world/asia/rss.xml"),
        # ("The Diplomat",  "https://thediplomat.com/feed/"),  # timeout — disabled
        ("Nikkei Asia EN",  "https://news.google.com/rss/search?q=site:asia.nikkei.com+when:1d"),
        ("CNA",             "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml"),
        ("Nikkei Asia",     _gn("site:asia.nikkei.com when:3d")),
        ("SCMP China",      _gn("site:scmp.com china when:2d")),
        ("Al Jazeera",      "https://www.aljazeera.com/xml/rss/all.xml"),
    ],
    # Vietnam direct
    "vietnam": [
        ("Vietnam News (EN)",   _gn("Vietnam when:1d")),
        ("VN Economy",          _gn("Vietnam economy OR market when:1d")),
        ("VN-China Trade",      _gn("Vietnam China trade when:2d")),
        ("VN Finance",          _gn("Vietnam stock OR VNIndex when:1d")),
        ("VN-US Relations",     _gn("Vietnam United States when:3d")),
    ],
    # Global finance — market signals
    "finance": [
        ("Reuters Business",    _gn("site:reuters.com business markets")),
        ("CNBC Markets",        "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("Yahoo Finance",       "https://finance.yahoo.com/news/rssindex"),
        ("FT",                  "https://www.ft.com/rss/home"),
        ("MarketWatch",         _gn("site:marketwatch.com markets when:1d")),
    ],
    # Geopolitical — affects VN markets
    "geopolitical": [
        ("Foreign Policy",      "https://foreignpolicy.com/feed/"),
        ("Crisis Group",        "https://www.crisisgroup.org/rss"),
        ("CSIS",                "https://www.csis.org/rss.xml"),
        ("Atlantic Council",    "https://www.atlanticcouncil.org/feed/"),
        ("UN News",             "https://www.un.org/en/rss.xml"),
    ],
    # Tech & AI — global signals
    "tech": [
        ("Hacker News",         "https://hnrss.org/frontpage"),
        ("Ars Technica",        "https://feeds.arstechnica.com/arstechnica/technology-lab"),
        ("VentureBeat AI",      "https://venturebeat.com/category/ai/feed/"),
        ("MIT Tech Review",     "https://www.technologyreview.com/feed/"),
    ],
}

# ── Threat keyword classifier (ported from worldmonitor _classifier.ts) ───────

THREAT_KEYWORDS = {
    "critical": [
        r"\b(war|warfare|nuclear|missile|attack|explosion|killed|airstrike|invasion|coup)\b",
        r"\b(crisis|emergency|catastrophe|genocide|terror|terrorist)\b",
        r"\b(sanction|blockade|embargo)\b",
    ],
    "high": [
        r"\b(conflict|military|troops|soldiers|combat|battle|strike|offensive)\b",
        r"\b(protest|riot|unrest|demonstration|clash)\b",
        r"\b(recession|crash|collapse|default|bankruptcy)\b",
        r"\b(earthquake|flood|typhoon|tsunami|disaster)\b",
        r"\b(raises?\s+interest\s+rate|rate\s+hike|fed\s+hike|tightening|rate\s+rises?)\b",
        r"raises\s+interest\s+rates?",
    ],
    "medium": [
        r"\b(tension|dispute|warning|threat|concern|risk|volatile)\b",
        r"\b(inflation|interest rate|fed|central bank|tariff|trade war)\b",
        r"\b(election|vote|referendum|political)\b",
        r"\b(talks?|negotiation|scheduled|planned meeting)\b",
    ],
    "low": [
        r"\b(deal|agreement|partnership|cooperation|talks|negotiation)\b",
        r"\b(growth|recovery|expansion|investment|gdp)\b",
    ],
}

CATEGORY_KEYWORDS = {
    "military":     [r"\b(military|army|navy|air force|troops|weapon|missile|nuclear)\b"],
    "finance":      [r"\b(market|stock|bond|currency|gdp|inflation|interest rate|trade)\b"],
    "geopolitical": [r"\b(sanction|diplomacy|summit|treaty|alliance|china|russia|us)\b"],
    "disaster":     [r"\b(earthquake|flood|typhoon|hurricane|wildfire|tsunami)\b"],
    "tech":         [r"\b(ai|artificial intelligence|chip|semiconductor|cyber|hack)\b"],
    "energy":       [r"\b(oil|gas|opec|energy|renewable|coal|lng)\b"],
    "asia":         [r"\b(china|vietnam|japan|korea|india|asean|southeast asia)\b"],
}


def classify_threat(title: str) -> Dict:
    """
    Classify a headline into threat level and category.
    Returns: {level, category, confidence}
    """
    title_lower = title.lower()

    level = "info"
    confidence = 0.5
    for lvl in ["critical", "high", "medium", "low"]:
        for pattern in THREAT_KEYWORDS[lvl]:
            if re.search(pattern, title_lower, re.IGNORECASE):
                level = lvl
                confidence = {"critical": 0.95, "high": 0.85, "medium": 0.75, "low": 0.65}[lvl]
                break
        if level != "info":
            break

    category = "general"
    for cat, patterns in CATEGORY_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, title_lower, re.IGNORECASE):
                category = cat
                break
        if category != "general":
            break

    return {"level": level, "category": category, "confidence": confidence}


# ── XML/RSS parser ────────────────────────────────────────────────────────────

_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_RSS_HEADERS = {
    "User-Agent": _CHROME_UA,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Simple in-process cache {url: (timestamp, items)}
_FEED_CACHE: Dict[str, Tuple[float, List[Dict]]] = {}
CACHE_TTL = 3600  # 1 hour


def _parse_rss(xml_text: str, source_name: str, category: str) -> List[Dict]:
    """Parse RSS/Atom XML and return article list."""
    items = []
    try:
        root = ElementTree.fromstring(xml_text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        entries = root.findall(".//item")
        # Atom fallback
        if not entries:
            entries = root.findall(".//atom:entry", ns) or root.findall(".//entry")

        for entry in entries[:10]:
            def _get(tag: str) -> str:
                for t in [tag, f"atom:{tag}"]:
                    el = entry.find(t)
                    if el is None:
                        el = entry.find(t, ns)
                    if el is not None and el.text:
                        return el.text.strip()
                return ""

            title = _get("title")
            if not title:
                continue

            # Strip CDATA
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title, flags=re.DOTALL).strip()

            link = _get("link")
            if not link:
                # Atom href attribute
                link_el = entry.find("link") or entry.find("atom:link", ns)
                if link_el is not None:
                    link = link_el.get("href", "")

            pub_raw = _get("pubDate") or _get("published") or _get("updated")
            try:
                pub_ts = int(datetime.fromisoformat(
                    pub_raw.replace("Z", "+00:00").replace("GMT", "+00:00")
                ).timestamp() * 1000) if pub_raw else int(time.time() * 1000)
            except Exception:
                pub_ts = int(time.time() * 1000)

            threat = classify_threat(title)

            # Extract summary/description as content
            summary = _get("description") or _get("summary") or _get("content")
            summary = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", summary, flags=re.DOTALL).strip()
            # Strip HTML tags from summary
            summary = re.sub(r"<[^>]+>", " ", summary)
            summary = re.sub(r"\s+", " ", summary).strip()[:1000]

            items.append({
                "title": title,
                "url": link,
                "mobileUrl": "",
                "content": summary or None,
                "source": source_name,
                "wm_category": category,
                "threat_level": threat["level"],
                "threat_category": threat["category"],
                "threat_confidence": threat["confidence"],
                "published_at": pub_ts,
                "published_iso": datetime.fromtimestamp(
                    pub_ts / 1000, tz=timezone.utc
                ).isoformat(),
            })
    except Exception as e:
        pass  # malformed XML — skip silently

    return items


# ── Main fetcher class ────────────────────────────────────────────────────────

class WorldMonitorFetcher:
    """
    Fetch global news from WorldMonitor's curated RSS feed list.
    Designed to plug into TrendNews pipeline as an additional data source.

    Usage:
        fetcher = WorldMonitorFetcher()
        results = fetcher.fetch_all()
        # results: {"asia": [...], "vietnam": [...], "finance": [...], ...}

        flat = fetcher.fetch_flat(categories=["asia", "vietnam"])
        # flat: List[article_dict]
    """

    def __init__(
        self,
        timeout: int = 10,
        max_items_per_feed: int = 8,
        use_cache: bool = True,
    ):
        self.timeout = timeout
        self.max_items = max_items_per_feed
        self.use_cache = use_cache

    def _fetch_feed(self, url: str, source_name: str, category: str) -> List[Dict]:
        """Fetch and parse a single RSS feed with caching."""
        now = time.time()

        if self.use_cache and url in _FEED_CACHE:
            ts, cached = _FEED_CACHE[url]
            if now - ts < CACHE_TTL:
                return cached

        try:
            resp = requests.get(url, headers=_RSS_HEADERS, timeout=self.timeout)
            resp.raise_for_status()
            items = _parse_rss(resp.text, source_name, category)[:self.max_items]
            if self.use_cache:
                _FEED_CACHE[url] = (now, items)
            return items
        except Exception as e:
            print(f"  ✗ WM [{source_name}]: {e}")
            return []

    def fetch_category(self, category: str) -> List[Dict]:
        """Fetch all feeds for a given category."""
        feeds = WORLDMONITOR_FEEDS.get(category, [])
        items = []
        for name, url in feeds:
            result = self._fetch_feed(url, name, category)
            items.extend(result)
            if result:
                print(f"  ✓ WM [{category}] {name}: {len(result)} articles")
        return items

    def fetch_all(
        self, categories: Optional[List[str]] = None
    ) -> Dict[str, List[Dict]]:
        """
        Fetch all (or selected) categories.

        Returns:
            {category: [article, ...], ...}
        """
        cats = categories or list(WORLDMONITOR_FEEDS.keys())
        results = {}
        for cat in cats:
            print(f"\n[WorldMonitor] Fetching category: {cat}")
            results[cat] = self.fetch_category(cat)
        return results

    def fetch_flat(
        self, categories: Optional[List[str]] = None
    ) -> List[Dict]:
        """Fetch and return a flat list of all articles across categories."""
        all_results = self.fetch_all(categories)
        flat = []
        for articles in all_results.values():
            flat.extend(articles)
        # Dedup by URL
        seen = set()
        deduped = []
        for a in flat:
            if a["url"] and a["url"] not in seen:
                seen.add(a["url"])
                deduped.append(a)
        # Sort by published_at desc
        deduped.sort(key=lambda x: x.get("published_at", 0), reverse=True)
        return deduped

    def fetch_as_pipeline_format(
        self, categories: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Return articles in the same format as BaseScraper.fetch():
        {"status": "success", "id": source_id, "items": [...]}
        
        Grouped by source so existing pipeline can handle directly.
        """
        flat = self.fetch_flat(categories)
        # Group by source
        by_source: Dict[str, List] = {}
        for art in flat:
            src = art["source"]
            by_source.setdefault(src, []).append({
                "title": art["title"],
                "url": art["url"],
                "mobileUrl": art.get("mobileUrl", ""),
                # Extended fields for enrichment
                "wm_category": art.get("wm_category"),
                "threat_level": art.get("threat_level"),
                "threat_category": art.get("threat_category"),
                "threat_confidence": art.get("threat_confidence"),
                "published_at": art.get("published_at"),
            })

        return [
            {
                "status": "success",
                "id": f"wm-{src.lower().replace(' ', '-')}",
                "source_name": src,
                "items": items,
                "wm_source": True,
            }
            for src, items in by_source.items()
        ]

"""
ArticleEnricher — cross-reference VN articles with WorldMonitor global context.

For each Vietnamese article, finds related global articles from WorldMonitor
and computes:
  - global_context: related headlines from WM
  - threat_level:   critical / high / medium / low / info
  - geo_relevance:  0.0-1.0 (how geopolitically relevant to VN)
  - market_signal:  bullish / bearish / neutral
"""

import re
from typing import Dict, List, Optional, Tuple


# ── Keyword mappings: VN → EN equivalents ─────────────────────────────────────

VN_EN_MAPPING = {
    # Economic terms
    "xuất khẩu": ["export", "trade"],
    "nhập khẩu": ["import", "trade"],
    "chứng khoán": ["stock", "market", "index"],
    "cổ phiếu": ["stock", "share", "equity"],
    "ngân hàng": ["bank", "banking", "financial"],
    "tín dụng": ["credit", "loan"],
    "lãi suất": ["interest rate", "rate hike", "fed"],
    "lạm phát": ["inflation", "cpi", "price"],
    "tỷ giá": ["exchange rate", "currency", "dollar", "usd"],
    "đầu tư": ["investment", "invest", "fund"],
    "bất động sản": ["real estate", "property", "housing"],
    "dầu": ["oil", "crude", "opec", "energy"],
    "vàng": ["gold", "commodity"],
    "trái phiếu": ["bond", "yield", "treasury"],
    # Political/Geopolitical
    "trung quốc": ["china", "chinese", "beijing"],
    "mỹ": ["us", "usa", "united states", "american", "washington"],
    "nga": ["russia", "russian", "moscow"],
    "nhật bản": ["japan", "japanese", "tokyo"],
    "hàn quốc": ["korea", "korean"],
    "asean": ["asean", "southeast asia"],
    "thương mại": ["trade", "commerce", "tariff"],
    "thuế": ["tariff", "tax", "duty"],
    "chiến tranh": ["war", "conflict", "military"],
    "căng thẳng": ["tension", "dispute", "conflict"],
    # Companies
    "samsung": ["samsung"],
    "intel": ["intel"],
    "foxconn": ["foxconn", "apple supply"],
    "vingroup": ["vingroup"],
    "vietcombank": ["vietcombank"],
}

# ── Market signal keywords ─────────────────────────────────────────────────────

BEARISH_KEYWORDS = [
    r"\b(crash|collapse|fall|drop|decline|recession|default|crisis|war|sanction|"
    r"inflation|rate hike|tightening|sell.off|bear|plunge|slump|tumble)\b"
]
BULLISH_KEYWORDS = [
    r"\b(rally|surge|gain|rise|recovery|growth|bull|boom|invest|deal|"
    r"partnership|expansion|stimulus|cut rate|easing|upgrade)\b"
]

# ── Geo-relevance: terms that directly impact Vietnam ─────────────────────────

VN_GEO_TERMS = [
    r"\b(vietnam|vietnamese|hanoi|ho chi minh|viet|asean)\b",
    r"\b(china|south china sea|mekong|taiwan strait)\b",
    r"\b(supply chain|manufacturing|factory|semiconductor|chip)\b",
    r"\b(export|import|trade war|tariff|sanction)\b",
    r"\b(oil|energy|lng|commodity|rice|coffee|rubber)\b",
    r"\b(fed|interest rate|dollar|usd|vnd|dong)\b",
]


class ArticleEnricher:
    """
    Cross-reference Vietnamese articles with WorldMonitor global context.
    
    Usage:
        enricher = ArticleEnricher(wm_articles)
        enriched = enricher.enrich_batch(vn_articles)
    """

    def __init__(
        self,
        wm_articles: List[Dict],
        max_context_items: int = 5,
        min_overlap_score: float = 0.15,
    ):
        """
        Args:
            wm_articles:      Flat list of WM articles (from WorldMonitorFetcher.fetch_flat())
            max_context_items: Max global context articles to attach per VN article
            min_overlap_score: Minimum keyword overlap score to include as context
        """
        self.wm_articles = wm_articles
        self.max_context = max_context_items
        self.min_overlap = min_overlap_score

    # ── Scoring helpers ───────────────────────────────────────────────────────

    def _extract_keywords(self, title: str) -> set:
        """Extract normalised keywords from title (works for VN and EN)."""
        # Map VN terms to EN
        lower = title.lower()
        tokens = set(re.findall(r'\b\w{3,}\b', lower))
        for vn_term, en_terms in VN_EN_MAPPING.items():
            if vn_term in lower:
                tokens.update(en_terms)
        return tokens

    def _overlap_score(self, vn_title: str, wm_title: str) -> float:
        """Jaccard-inspired overlap score between two titles."""
        vn_kw = self._extract_keywords(vn_title)
        wm_kw = self._extract_keywords(wm_title)
        # Remove stopwords
        stop = {"the", "and", "for", "with", "from", "this", "that",
                "are", "was", "has", "have", "will", "its", "new"}
        vn_kw -= stop
        wm_kw -= stop
        if not vn_kw or not wm_kw:
            return 0.0
        intersection = vn_kw & wm_kw
        union = vn_kw | wm_kw
        return len(intersection) / len(union)

    def _geo_relevance(self, wm_title: str) -> float:
        """Score 0-1 how geopolitically relevant a WM headline is to Vietnam."""
        score = 0.0
        lower = wm_title.lower()
        for pattern in VN_GEO_TERMS:
            if re.search(pattern, lower, re.IGNORECASE):
                score += 0.2
        return min(score, 1.0)

    def _market_signal(self, articles: List[Dict]) -> str:
        """Determine bullish/bearish/neutral signal from a list of articles."""
        bear, bull = 0, 0
        for a in articles:
            title = a.get("title", "").lower()
            for p in BEARISH_KEYWORDS:
                if re.search(p, title, re.IGNORECASE):
                    bear += 1
                    break
            for p in BULLISH_KEYWORDS:
                if re.search(p, title, re.IGNORECASE):
                    bull += 1
                    break
        if bull > bear + 1:
            return "bullish"
        if bear > bull + 1:
            return "bearish"
        return "neutral"

    def _worst_threat(self, articles: List[Dict]) -> str:
        """Return the worst threat level from a list."""
        order = ["critical", "high", "medium", "low", "info"]
        for lvl in order:
            if any(a.get("threat_level") == lvl for a in articles):
                return lvl
        return "info"

    # ── Main enrichment ───────────────────────────────────────────────────────

    def enrich(self, vn_article: Dict) -> Dict:
        """
        Enrich a single VN article with global context.

        Input article must have at least: title, url
        Returns the article with added fields:
          global_context, threat_level, geo_relevance, market_signal, wm_sources
        """
        vn_title = vn_article.get("title", "")

        # Score all WM articles against this VN article
        scored = []
        for wm in self.wm_articles:
            wm_title = wm.get("title", "")
            overlap = self._overlap_score(vn_title, wm_title)
            geo = self._geo_relevance(wm_title)
            combined = overlap * 0.6 + geo * 0.4
            if combined >= self.min_overlap:
                scored.append((combined, wm))

        # Sort by combined score, take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [wm for _, wm in scored[: self.max_context]]

        enriched = dict(vn_article)
        enriched["global_context"] = [
            {
                "title": a.get("title", ""),
                "source": a.get("source", ""),
                "url": a.get("url", ""),
                "threat_level": a.get("threat_level", "info"),
                "wm_category": a.get("wm_category", ""),
                "published_at": a.get("published_at"),
            }
            for a in top
        ]
        enriched["threat_level"] = self._worst_threat(top) if top else "info"
        enriched["geo_relevance"] = round(
            max((s for s, _ in scored[:3]), default=0.0), 3
        )
        enriched["market_signal"] = self._market_signal(top)
        enriched["wm_sources"] = list({a.get("source", "") for a in top if a.get("source")})

        return enriched

    def enrich_batch(self, vn_articles: List[Dict]) -> List[Dict]:
        """Enrich a list of VN articles."""
        return [self.enrich(a) for a in vn_articles]

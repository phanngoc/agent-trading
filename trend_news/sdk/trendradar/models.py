"""TrendRadar SDK data models."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class TickerSignal:
    ticker: str
    company: str
    score: float
    label: str                        # Bullish/Somewhat-Bullish/Neutral/...
    confidence: float                 # 0–1 (0.85 = batch, 0.5 = on-the-fly)
    article_count: int
    sector: Optional[str]
    top_headlines: List[str]
    threat_level: Optional[str]       # critical/high/medium/low/info
    market_signal: Optional[str]      # bullish/bearish/neutral (WM context)

    @property
    def is_bullish(self) -> bool:
        return self.score >= 0.20

    @property
    def is_bearish(self) -> bool:
        return self.score <= -0.20

    @property
    def is_neutral(self) -> bool:
        return not self.is_bullish and not self.is_bearish

    def __repr__(self) -> str:
        return (f"TickerSignal(ticker={self.ticker!r}, label={self.label!r}, "
                f"score={self.score:+.3f}, articles={self.article_count})")


@dataclass
class BatchResult:
    tickers: Dict[str, TickerSignal]
    days_back: int
    timestamp: str

    def bullish(self) -> List[TickerSignal]:
        return sorted([s for s in self.tickers.values() if s.is_bullish],
                      key=lambda x: x.score, reverse=True)

    def bearish(self) -> List[TickerSignal]:
        return sorted([s for s in self.tickers.values() if s.is_bearish],
                      key=lambda x: x.score)

    def __getitem__(self, ticker: str) -> TickerSignal:
        return self.tickers[ticker.upper()]

    def __repr__(self) -> str:
        return (f"BatchResult(tickers={list(self.tickers.keys())}, "
                f"bullish={len(self.bullish())}, bearish={len(self.bearish())})")


@dataclass
class MarketSummary:
    date: str
    market_score: float
    market_label: str
    bullish_pct: float
    bearish_pct: float
    article_count: int
    global_risk: str                  # HIGH/MEDIUM/LOW
    critical_events: int
    high_events: int
    vn_relevant_events: List[Dict]
    timestamp: str

    @property
    def is_high_risk(self) -> bool:
        return self.global_risk == "HIGH"

    def __repr__(self) -> str:
        return (f"MarketSummary(label={self.market_label!r}, "
                f"risk={self.global_risk!r}, score={self.market_score:+.3f})")


@dataclass
class SectorSignal:
    sector: str
    display_name: str
    avg_score: float
    label: str
    ticker_count: int
    bullish: int
    bearish: int
    neutral: int
    tickers: List[Dict]
    timestamp: str

    def __repr__(self) -> str:
        return (f"SectorSignal(sector={self.sector!r}, label={self.label!r}, "
                f"score={self.avg_score:+.3f}, tickers={self.ticker_count})")


@dataclass
class IntelItem:
    title: str
    source_name: str
    url: str
    wm_category: str
    threat_level: str
    threat_category: str
    geo_relevance: float
    published_at: Optional[int]
    crawl_date: str

    @property
    def is_vn_relevant(self) -> bool:
        return self.geo_relevance >= 0.3

    def __repr__(self) -> str:
        return (f"IntelItem(threat={self.threat_level!r}, "
                f"geo={self.geo_relevance:.0%}, title={self.title[:50]!r})")


@dataclass
class MorningReport:
    report_date: str
    market_outlook: str
    global_risk: str
    market_score: float
    top_picks: List[Dict]
    risk_alerts: List[Dict]
    synthesis: str
    generated_at: str
    content: Dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return (f"MorningReport(date={self.report_date!r}, "
                f"outlook={self.market_outlook!r}, risk={self.global_risk!r})")


@dataclass
class SignalUpdate:
    """Received via WebSocket stream."""
    type: str                         # signal_update / intel_alert / ping / snapshot
    ticker: Optional[str] = None
    score: Optional[float] = None
    label: Optional[str] = None
    delta: Optional[float] = None     # score change (signal_update only)
    article_count: Optional[int] = None
    latest_headline: Optional[str] = None
    threat_level: Optional[str] = None
    title: Optional[str] = None
    wm_category: Optional[str] = None
    geo_relevance: Optional[float] = None
    timestamp: Optional[str] = None
    raw: Dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict) -> "SignalUpdate":
        return cls(
            type=d.get("type", ""),
            ticker=d.get("ticker"),
            score=d.get("score"),
            label=d.get("label"),
            delta=d.get("delta"),
            article_count=d.get("article_count"),
            latest_headline=d.get("latest_headline"),
            threat_level=d.get("threat_level"),
            title=d.get("title"),
            wm_category=d.get("wm_category"),
            geo_relevance=d.get("geo_relevance"),
            timestamp=d.get("timestamp"),
            raw=d,
        )

    def __repr__(self) -> str:
        if self.type == "signal_update":
            return (f"SignalUpdate({self.ticker}, {self.label}, "
                    f"{self.score:+.3f}, delta={self.delta:+.3f})")
        if self.type == "intel_alert":
            return f"IntelAlert(threat={self.threat_level}, {self.title[:40]!r})"
        return f"SignalUpdate(type={self.type!r})"

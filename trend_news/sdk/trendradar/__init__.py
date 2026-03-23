"""
TrendRadar Python SDK

pip install trendradar  (or: pip install -e ./sdk)

Usage:
    from trendradar import TrendRadar

    tr = TrendRadar(api_key="tr_xxx", base_url="http://localhost:8000")

    # Single ticker
    sig = tr.ticker("VCB")
    print(sig.label, sig.score, sig.confidence)

    # Batch tickers
    batch = tr.tickers(["VCB", "HPG", "GAS"])
    for ticker, sig in batch.items():
        print(ticker, sig.label)

    # Market summary
    market = tr.market.summary()
    print(market.market_label, market.global_risk)

    # Sector sentiment
    banking = tr.sectors.get("banking")
    print(banking.avg_score, banking.bullish)

    # Morning report
    report = tr.reports.latest()
    print(report.market_outlook, report.synthesis)

    # Global intel
    threats = tr.intel.critical()
    for t in threats:
        print(t.title, t.threat_level)

    # WebSocket streaming (async)
    async with tr.stream(tickers=["VCB", "HPG"]) as stream:
        async for update in stream:
            print(update.ticker, update.score, update.delta)
"""

from .client import TrendRadar
from .models import (
    TickerSignal, BatchResult, MarketSummary,
    SectorSignal, IntelItem, MorningReport,
    SignalUpdate,
)

__version__ = "1.0.0"
__all__ = [
    "TrendRadar",
    "TickerSignal", "BatchResult", "MarketSummary",
    "SectorSignal", "IntelItem", "MorningReport",
    "SignalUpdate",
]

# TrendRadar Python SDK

Vietnamese stock market intelligence SDK for AI trading agents.

## Install

```bash
pip install trendradar
# With WebSocket streaming:
pip install trendradar[stream]

# Local dev:
pip install -e ./sdk
```

## Quick Start

```python
from trendradar import TrendRadar

tr = TrendRadar(api_key="tr_xxx", base_url="https://api.trendradar.vn")

# Single ticker
vcb = tr.ticker("VCB")
print(vcb.label, vcb.score, vcb.confidence)
# → Bullish +0.35 0.85

# Batch (portfolio)
batch = tr.tickers(["VCB", "HPG", "GAS", "VIC", "VNM"])
for sig in batch.bullish():
    print(f"{sig.ticker}: {sig.label} ({sig.score:+.3f})")

# Market summary
market = tr.market.summary()
print(f"Market: {market.market_label}, Global risk: {market.global_risk}")

# Sector analysis
banking = tr.sectors.get("banking")
print(f"Banking: {banking.label}, {banking.bullish}↑/{banking.bearish}↓")

# Morning brief
report = tr.reports.latest()
print(report.synthesis)
for pick in report.top_picks[:3]:
    print(f"  {pick['ticker']}: {pick['label']}")

# Global intel
for event in tr.intel.critical(limit=5):
    print(f"🔴 [{event.wm_category}] {event.title}")
    if event.is_vn_relevant:
        print(f"   ⚠️ VN relevance: {event.geo_relevance:.0%}")
```

## WebSocket Streaming

```python
import asyncio
from trendradar import TrendRadar

tr = TrendRadar(api_key="tr_xxx")

async def main():
    async with tr.stream(["VCB", "HPG", "GAS"]) as stream:
        async for update in stream:
            if update.type == "signal_update":
                print(f"{update.ticker}: {update.label} ({update.delta:+.3f} delta)")
            elif update.type == "intel_alert":
                print(f"🔴 ALERT: {update.title}")

asyncio.run(main())
```

## Alpha Vantage Compatible

```python
import requests

# Drop-in replacement for Alpha Vantage NEWS_SENTIMENT
resp = requests.get("http://localhost:8000/query", params={
    "function": "NEWS_SENTIMENT",
    "tickers": "VCB",
    "limit": 50,
    "apikey": "tr_xxx",
})
data = resp.json()
for item in data["feed"]:
    print(item["title"], item["overall_sentiment_label"])
```

## API Reference

| Method | Description |
|---|---|
| `tr.ticker(ticker)` | Single ticker signal |
| `tr.tickers([...])` | Batch up to 30 tickers |
| `tr.market.summary()` | VN market + global risk |
| `tr.market.heatmap()` | All tickers by sector |
| `tr.sectors.list()` | Available sectors |
| `tr.sectors.get(sector)` | Sector-level sentiment |
| `tr.intel.critical()` | Critical global events |
| `tr.intel.search(query)` | FTS search WM intel |
| `tr.reports.latest()` | Latest morning brief |
| `tr.stream([tickers])` | WebSocket async stream |
| `tr.news(tickers=...)` | Raw news articles |

## Sectors

`banking` `real_estate` `energy` `steel` `tech` `retail`
`food_beverage` `aviation` `securities` `industrial` `utilities` `logistics`

"""TrendRadar Python SDK — main client."""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, List, Optional
from urllib.parse import urlencode

import requests

try:
    import websockets
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False

from .models import (
    BatchResult, IntelItem, MarketSummary, MorningReport,
    SectorSignal, SignalUpdate, TickerSignal,
)


class TrendRadarError(Exception):
    """Raised when the API returns an error."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class _BaseNamespace:
    def __init__(self, client: "TrendRadar"):
        self._c = client


# ── Sub-namespaces ────────────────────────────────────────────────────────────

class _MarketNamespace(_BaseNamespace):
    def summary(self, days_back: int = 1) -> MarketSummary:
        d = self._c._get("/api/v1/market/summary", {"days_back": days_back})
        vn = d.get("vn_market", {})
        gr = d.get("global_risk", {})
        return MarketSummary(
            date=d.get("date", ""),
            market_score=vn.get("avg_sentiment_score", 0.0),
            market_label=vn.get("sentiment_label", "Neutral"),
            bullish_pct=vn.get("bullish_pct", 0.0),
            bearish_pct=vn.get("bearish_pct", 0.0),
            article_count=vn.get("article_count", 0),
            global_risk=gr.get("level", "LOW"),
            critical_events=gr.get("critical_events", 0),
            high_events=gr.get("high_events", 0),
            vn_relevant_events=gr.get("vn_relevant", []),
            timestamp=d.get("timestamp", ""),
        )

    def heatmap(self, days_back: int = 1) -> Dict:
        return self._c._get("/api/v2/market/heatmap", {"days_back": days_back})


class _SectorNamespace(_BaseNamespace):
    def list(self) -> List[Dict]:
        return self._c._get("/api/v2/sectors")["sectors"]

    def get(self, sector: str, days_back: int = 7) -> SectorSignal:
        d = self._c._get(f"/api/v2/sectors/{sector}", {"days_back": days_back})
        return SectorSignal(
            sector=d.get("sector", ""),
            display_name=d.get("display_name", ""),
            avg_score=d.get("avg_sentiment_score", 0.0),
            label=d.get("sentiment_label", "Neutral"),
            ticker_count=d.get("ticker_count", 0),
            bullish=d.get("bullish", 0),
            bearish=d.get("bearish", 0),
            neutral=d.get("neutral", 0),
            tickers=d.get("tickers", []),
            timestamp=d.get("timestamp", ""),
        )


class _IntelNamespace(_BaseNamespace):
    def get(
        self,
        date: Optional[str] = None,
        category: Optional[str] = None,
        threat: Optional[str] = None,
        limit: int = 50,
    ) -> List[IntelItem]:
        params = {"limit": limit}
        if date:     params["date"] = date
        if category: params["category"] = category
        if threat:   params["threat"] = threat
        items = self._c._get("/api/v2/intel", params).get("items", [])
        return [IntelItem(**item) for item in items]

    def critical(self, limit: int = 20) -> List[IntelItem]:
        return self.get(threat="critical", limit=limit)

    def high(self, limit: int = 20) -> List[IntelItem]:
        return self.get(threat="high", limit=limit)

    def vn_relevant(self, limit: int = 20) -> List[IntelItem]:
        items = self.get(category="vietnam", limit=limit)
        return [i for i in items if i.is_vn_relevant]

    def search(self, query: str, limit: int = 20) -> List[Dict]:
        return self._c._get("/api/v2/intel/search", {"q": query, "limit": limit})["results"]

    def threat_summary(self, days_back: int = 3) -> Dict:
        return self._c._get("/api/v2/intel/threat-summary", {"days_back": days_back})


class _ReportsNamespace(_BaseNamespace):
    def latest(self) -> MorningReport:
        d = self._c._get("/api/v2/reports/latest")
        content = d.get("content", {})
        return MorningReport(
            report_date=d.get("report_date", ""),
            market_outlook=d.get("market_outlook", "Neutral"),
            global_risk=d.get("global_risk", "LOW"),
            market_score=d.get("market_score", 0.0),
            top_picks=content.get("top_picks", []),
            risk_alerts=content.get("risk_alerts", []),
            synthesis=content.get("synthesis", ""),
            generated_at=d.get("generated_at", ""),
            content=content,
        )

    def generate(self, watchlist: Optional[List[str]] = None) -> Dict:
        params = {"apikey": self._c.api_key}
        body = {}
        if watchlist:
            body["watchlist"] = watchlist  # type: ignore
        resp = requests.post(
            f"{self._c.base_url}/api/v2/reports/generate",
            params=params, json=body, timeout=self._c.timeout,
        )
        resp.raise_for_status()
        return resp.json()


# ── Stream context manager ────────────────────────────────────────────────────

class _StreamContext:
    def __init__(self, client: "TrendRadar", tickers: List[str]):
        self._client = client
        self._tickers = tickers
        self._ws = None

    async def __aenter__(self) -> "_StreamContext":
        if not _WS_AVAILABLE:
            raise ImportError("websockets package required: pip install websockets")
        qs = urlencode({"tickers": ",".join(self._tickers), "apikey": self._client.api_key})
        ws_url = self._client.base_url.replace("http://", "ws://").replace("https://", "wss://")
        self._ws = await websockets.connect(f"{ws_url}/api/v3/stream?{qs}")
        return self

    async def __aexit__(self, *args):
        if self._ws:
            await self._ws.close()

    def __aiter__(self):
        return self

    async def __anext__(self) -> SignalUpdate:
        if not self._ws:
            raise StopAsyncIteration
        try:
            msg = await self._ws.recv()
            return SignalUpdate.from_dict(json.loads(msg))
        except Exception:
            raise StopAsyncIteration


# ── Main client ───────────────────────────────────────────────────────────────

class TrendRadar:
    """
    TrendRadar Python SDK client.

    Args:
        api_key:  API key (default: "dev-key" for local dev)
        base_url: API base URL (default: http://localhost:8000)
        timeout:  Request timeout in seconds (default: 30)

    Examples:
        tr = TrendRadar(api_key="tr_xxx", base_url="https://api.trendradar.vn")

        # Ticker sentiment
        vcb = tr.ticker("VCB")
        print(vcb.label, vcb.score)

        # Batch
        batch = tr.tickers(["VCB", "HPG", "GAS"])
        for bullish in batch.bullish():
            print(bullish.ticker, bullish.score)

        # Market & sectors
        market = tr.market.summary()
        banking = tr.sectors.get("banking")

        # Reports
        report = tr.reports.latest()
        print(report.synthesis)

        # Global intel
        threats = tr.intel.critical()

        # WebSocket stream (async)
        async with tr.stream(["VCB", "HPG"]) as stream:
            async for update in stream:
                if update.type == "signal_update":
                    print(update.ticker, update.delta)
    """

    def __init__(
        self,
        api_key: str = "dev-key",
        base_url: str = "http://localhost:8000",
        timeout: int = 30,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.params = {"apikey": api_key}  # type: ignore

        # Sub-namespaces
        self.market  = _MarketNamespace(self)
        self.sectors = _SectorNamespace(self)
        self.intel   = _IntelNamespace(self)
        self.reports = _ReportsNamespace(self)

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        resp = self._session.get(
            f"{self.base_url}{path}",
            params=params or {},
            timeout=self.timeout,
        )
        if not resp.ok:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            raise TrendRadarError(resp.status_code, detail)
        return resp.json()

    # ── Top-level methods ─────────────────────────────────────────────────────

    def ticker(self, ticker: str, days_back: int = 7) -> TickerSignal:
        """Get sentiment signal for a single VN ticker."""
        d = self._get(f"/api/v1/tickers/{ticker.upper()}", {"days_back": days_back})
        return TickerSignal(
            ticker=d.get("ticker", ""),
            company=d.get("company_name", ""),
            score=d.get("avg_sentiment_score", 0.0),
            label=d.get("sentiment_label", "Neutral"),
            confidence=0.85,
            article_count=d.get("article_count", 0),
            sector=d.get("sector"),
            top_headlines=d.get("top_headlines", []),
            threat_level=d.get("threat_level"),
            market_signal=d.get("market_signal"),
        )

    def tickers(self, tickers: List[str], days_back: int = 7) -> BatchResult:
        """Batch sentiment for multiple tickers."""
        resp = self._session.post(
            f"{self.base_url}/api/v2/tickers/batch",
            json={"tickers": tickers, "days_back": days_back},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        d = resp.json()
        signals = {}
        for ticker, info in d.get("tickers", {}).items():
            if "error" in info:
                continue
            signals[ticker] = TickerSignal(
                ticker=ticker,
                company=info.get("company", ""),
                score=info.get("avg_sentiment_score", 0.0),
                label=info.get("sentiment_label", "Neutral"),
                confidence=info.get("confidence", 0.5),
                article_count=info.get("article_count", 0),
                sector=info.get("sector"),
                top_headlines=info.get("top_headlines", []),
                threat_level=None,
                market_signal=None,
            )
        return BatchResult(
            tickers=signals,
            days_back=d.get("days_back", days_back),
            timestamp=d.get("timestamp", ""),
        )

    def news(
        self,
        tickers: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get raw news articles with optional filters."""
        params: Dict = {"limit": limit}
        if tickers:     params["tickers"] = tickers
        if start_date:  params["start_date"] = start_date
        if end_date:    params["end_date"] = end_date
        if source:      params["source"] = source
        return self._get("/api/v1/news", params)

    def stream(self, tickers: List[str]) -> _StreamContext:
        """
        Async context manager for WebSocket signal streaming.

        Usage:
            async with tr.stream(["VCB", "HPG"]) as s:
                async for update in s:
                    print(update)
        """
        return _StreamContext(self, tickers)

    def health(self) -> Dict:
        return self._get("/health")

    def metrics(self) -> Dict:
        return self._get("/metrics")

    def __repr__(self) -> str:
        return f"TrendRadar(base_url={self.base_url!r}, api_key={self.api_key[:6]!r}...)"

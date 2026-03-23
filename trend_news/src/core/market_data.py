"""
VN Market Data Fetcher

Sources (fallback chain):
  1. Yahoo Finance (.VN suffix) — free, global, 15min delay
  2. CafeF scrape — free, daily OHLCV
  3. Cached in SQLite (market_prices table)

Usage:
    fetcher = MarketDataFetcher(db_path="output/trend_news.db")

    # Single ticker
    price = fetcher.get_price("VCB")
    # → PriceData(ticker="VCB", close=57800, change_pct=1.2, volume=2_500_000)

    # Batch
    prices = fetcher.get_prices(["VCB", "HPG", "GAS"])

    # VNIndex
    index = fetcher.get_index()
    # → IndexData(value=1250.5, change=8.2, change_pct=0.66)

    # Signal with price context
    signal = fetcher.enrich_ticker_signal(ticker_signal, price_data)
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
import requests

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
CAFEF_PRICE_URL = "https://s.cafef.vn/ajax/PageNew/DataHistory/PriceHistory.ashx"
CACHE_TTL_MINUTES = 30

_PRICE_CACHE: Dict[str, Tuple[float, "PriceData"]] = {}


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class PriceData:
    ticker: str
    close: float             # VND
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: int = 0
    change: float = 0.0      # absolute change VND
    change_pct: float = 0.0  # % change
    prev_close: float = 0.0
    trade_date: str = ""
    source: str = "yahoo"

    @property
    def is_up(self) -> bool:
        return self.change_pct > 0

    @property
    def is_down(self) -> bool:
        return self.change_pct < 0

    @property
    def signal(self) -> str:
        """Simple price signal: up/down/flat."""
        if self.change_pct > 0.5:   return "up"
        if self.change_pct < -0.5:  return "down"
        return "flat"

    def format_price(self) -> str:
        """Format price in VND thousands."""
        return f"{self.close/1000:.1f}k"

    def format_change(self) -> str:
        icon = "▲" if self.is_up else "▼" if self.is_down else "─"
        return f"{icon} {abs(self.change_pct):.2f}%"

    def __repr__(self) -> str:
        return (f"PriceData({self.ticker}, close={self.format_price()}, "
                f"change={self.format_change()}, vol={self.volume:,})")


@dataclass
class IndexData:
    name: str              # VNINDEX / HNX / UPCOM
    value: float
    change: float
    change_pct: float
    advances: int = 0      # số mã tăng
    declines: int = 0      # số mã giảm
    unchanged: int = 0
    volume: int = 0
    trade_date: str = ""

    @property
    def breadth(self) -> str:
        """Market breadth: bullish/bearish/neutral."""
        if self.advances > self.declines * 1.5: return "bullish"
        if self.declines > self.advances * 1.5: return "bearish"
        return "neutral"

    def __repr__(self) -> str:
        icon = "▲" if self.change_pct > 0 else "▼"
        return f"IndexData({self.name}={self.value:.2f} {icon}{abs(self.change_pct):.2f}%)"


@dataclass
class EnrichedSignal:
    """Ticker signal enriched with price data."""
    ticker: str
    sentiment_score: float
    sentiment_label: str
    price: Optional[PriceData]
    combined_signal: str     # strong_buy/buy/hold/sell/strong_sell
    reasoning: List[str]     # human-readable factors


# ── Fetcher ───────────────────────────────────────────────────────────────────

class MarketDataFetcher:
    """Fetch VN stock prices from Yahoo Finance with CafeF fallback."""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0",
    }

    def __init__(self, db_path: str = "output/trend_news.db", timeout: int = 8):
        self.db_path = db_path
        self.timeout = timeout
        self._init_table()

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_table(self):
        conn = self._db()
        try:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS market_prices (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker      TEXT NOT NULL,
                    trade_date  TEXT NOT NULL,
                    open        REAL, high REAL, low REAL, close REAL,
                    volume      INTEGER,
                    change      REAL,
                    change_pct  REAL,
                    prev_close  REAL,
                    source      TEXT,
                    fetched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, trade_date)
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_mp_ticker ON market_prices(ticker)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_mp_date ON market_prices(trade_date)")
            conn.commit()
        finally:
            conn.close()

    def _cache_get(self, ticker: str) -> Optional[PriceData]:
        entry = _PRICE_CACHE.get(ticker)
        if entry and time.time() - entry[0] < CACHE_TTL_MINUTES * 60:
            return entry[1]
        return None

    def _cache_set(self, ticker: str, data: PriceData):
        _PRICE_CACHE[ticker] = (time.time(), data)

    def _fetch_yahoo(self, ticker: str) -> Optional[PriceData]:
        """Fetch from Yahoo Finance (ticker.VN format)."""
        symbol = f"{ticker}.VN"
        try:
            r = requests.get(
                f"{YAHOO_BASE}/{symbol}",
                params={"interval": "1d", "range": "5d"},
                headers=self.HEADERS,
                timeout=self.timeout,
            )
            if not r.ok:
                return None
            d = r.json()
            result = d["chart"]["result"][0]
            meta = result["meta"]
            quotes = result.get("indicators", {}).get("quote", [{}])[0]
            timestamps = result.get("timestamp", [])

            close_price = meta.get("regularMarketPrice", 0.0)
            prev_close  = meta.get("chartPreviousClose", meta.get("previousClose", close_price))
            change      = close_price - prev_close
            change_pct  = (change / prev_close * 100) if prev_close else 0.0

            # Get latest OHLCV from quote data
            opens   = quotes.get("open", [])
            highs   = quotes.get("high", [])
            lows    = quotes.get("low", [])
            volumes = quotes.get("volume", [])

            open_p  = opens[-1]  if opens   and opens[-1]   is not None else 0.0
            high_p  = highs[-1]  if highs   and highs[-1]   is not None else 0.0
            low_p   = lows[-1]   if lows    and lows[-1]    is not None else 0.0
            vol     = volumes[-1] if volumes and volumes[-1] is not None else 0

            trade_date = (datetime.fromtimestamp(timestamps[-1]).strftime("%Y-%m-%d")
                         if timestamps else date.today().isoformat())

            return PriceData(
                ticker=ticker,
                close=close_price,
                open=open_p,
                high=high_p,
                low=low_p,
                volume=int(vol) if vol else 0,
                change=round(change, 2),
                change_pct=round(change_pct, 2),
                prev_close=prev_close,
                trade_date=trade_date,
                source="yahoo",
            )
        except Exception:
            return None

    def _fetch_cafef(self, ticker: str) -> Optional[PriceData]:
        """Fallback: CafeF daily OHLCV."""
        today = datetime.now().strftime("%d/%m/%Y")
        yesterday = (datetime.now() - timedelta(days=5)).strftime("%d/%m/%Y")
        try:
            r = requests.get(
                CAFEF_PRICE_URL,
                params={"Symbol": ticker, "StartDate": yesterday, "EndDate": today, "PageIndex": 1, "PageSize": 3},
                headers={**self.HEADERS, "Referer": "https://cafef.vn/"},
                timeout=self.timeout,
            )
            if not r.ok:
                return None
            items = r.json().get("Data", {}).get("Data", [])
            if not items:
                return None
            i = items[0]
            close = float(i.get("GiaDongCua", 0)) * 1000
            prev  = float(i.get("GiaDieuChinh", close)) * 1000
            chg   = close - prev
            return PriceData(
                ticker=ticker,
                close=close,
                open=float(i.get("GiaMoCua", 0)) * 1000,
                high=float(i.get("GiaCaoNhat", 0)) * 1000,
                low=float(i.get("GiaThapNhat", 0)) * 1000,
                volume=int(i.get("KhoiLuongKhopLenh", 0)),
                change=round(chg, 2),
                change_pct=round(chg / prev * 100, 2) if prev else 0.0,
                prev_close=prev,
                trade_date=i.get("Ngay", today),
                source="cafef",
            )
        except Exception:
            return None

    def _save_to_db(self, data: PriceData):
        conn = self._db()
        try:
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO market_prices
                    (ticker, trade_date, open, high, low, close, volume,
                     change, change_pct, prev_close, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (data.ticker, data.trade_date, data.open, data.high, data.low,
                  data.close, data.volume, data.change, data.change_pct,
                  data.prev_close, data.source))
            conn.commit()
        finally:
            conn.close()

    def get_price(self, ticker: str) -> Optional[PriceData]:
        """Get latest price for a ticker. Cache → Yahoo → CafeF → DB fallback."""
        # 1. Memory cache
        cached = self._cache_get(ticker)
        if cached:
            return cached

        # 2. Yahoo Finance (primary)
        data = self._fetch_yahoo(ticker)

        # 3. CafeF fallback
        if not data:
            data = self._fetch_cafef(ticker)

        # 4. DB fallback (last known price)
        if not data:
            conn = self._db()
            try:
                c = conn.cursor()
                c.execute("""
                    SELECT ticker, trade_date, open, high, low, close,
                           volume, change, change_pct, prev_close, source
                    FROM market_prices WHERE ticker = ?
                    ORDER BY trade_date DESC LIMIT 1
                """, [ticker])
                row = c.fetchone()
                if row:
                    cols = ["ticker","trade_date","open","high","low","close",
                            "volume","change","change_pct","prev_close","source"]
                    d = dict(zip(cols, row))
                    data = PriceData(**d)
            finally:
                conn.close()

        if data:
            self._cache_set(ticker, data)
            self._save_to_db(data)

        return data

    def get_prices(self, tickers: List[str]) -> Dict[str, Optional[PriceData]]:
        """Fetch prices for multiple tickers."""
        return {t: self.get_price(t) for t in tickers}

    def get_index(self, symbol: str = "^VNINDEX") -> Optional[IndexData]:
        """Fetch VNIndex / HNX / UPCOM."""
        try:
            r = requests.get(
                f"{YAHOO_BASE}/{symbol}",
                params={"interval": "1d", "range": "2d"},
                headers=self.HEADERS,
                timeout=self.timeout,
            )
            if not r.ok:
                return None
            meta = r.json()["chart"]["result"][0]["meta"]
            val   = meta.get("regularMarketPrice", 0.0)
            prev  = meta.get("chartPreviousClose", val)
            chg   = val - prev
            return IndexData(
                name=symbol.replace("^", ""),
                value=round(val, 2),
                change=round(chg, 2),
                change_pct=round(chg / prev * 100, 2) if prev else 0.0,
                trade_date=date.today().isoformat(),
            )
        except Exception:
            return None

    # ── Signal enrichment ─────────────────────────────────────────────────────

    def enrich_signal(
        self,
        ticker: str,
        sentiment_score: float,
        sentiment_label: str,
    ) -> EnrichedSignal:
        """
        Combine sentiment score with price action to produce final signal.

        Matrix:
          Sentiment ↑ + Price ↑ = Strong Buy
          Sentiment ↑ + Price ↓ = Buy (oversold, good entry?)
          Sentiment ↓ + Price ↑ = Sell (overbought?)
          Sentiment ↓ + Price ↓ = Strong Sell
          Neutral either side   = Hold
        """
        price = self.get_price(ticker)
        reasons = []

        # Sentiment signal
        sent_bullish = sentiment_score >= 0.20
        sent_bearish = sentiment_score <= -0.20

        # Price signal
        price_up = price and price.change_pct > 0.5
        price_down = price and price.change_pct < -0.5
        price_flat = not price_up and not price_down

        if price:
            reasons.append(f"Giá: {price.format_price()} ({price.format_change()})")
            reasons.append(f"Vol: {price.volume:,}")

        reasons.append(f"Sentiment: {sentiment_label} ({sentiment_score:+.3f})")

        # Combined signal
        if sent_bullish and price_up:
            signal = "strong_buy"
            reasons.append("✅ Tâm lý + giá cùng tăng")
        elif sent_bullish and price_down:
            signal = "buy"
            reasons.append("⬆ Tâm lý tốt, giá giảm → cơ hội vào hàng")
        elif sent_bearish and price_down:
            signal = "strong_sell"
            reasons.append("🔴 Tâm lý + giá cùng giảm")
        elif sent_bearish and price_up:
            signal = "sell"
            reasons.append("⬇ Tâm lý xấu, giá tăng → cẩn thận overbought")
        elif sent_bullish and price_flat:
            signal = "buy"
            reasons.append("⬆ Tâm lý tốt, giá ổn định")
        elif sent_bearish and price_flat:
            signal = "sell"
            reasons.append("⬇ Tâm lý xấu, chờ xác nhận")
        else:
            signal = "hold"
            reasons.append("➡ Không có tín hiệu rõ ràng")

        return EnrichedSignal(
            ticker=ticker,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
            price=price,
            combined_signal=signal,
            reasoning=reasons,
        )

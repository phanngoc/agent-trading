"""Price-cache reader.

Wraps the per-ticker CSVs produced by ``scripts/benchmark/seed_history.py``
in a small, immutable :class:`PriceBook` that the simulator consults for
fills and mark-to-market. Keeping this in its own module means the
portfolio / execution logic never has to know where the prices came
from — they could just as easily come from a backtest fixture.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# vnstock serves VN equity prices in *thousands of VND* — e.g. TCB at 32.0
# in the response actually means 32,000 VND per share. The portfolio /
# fees / NAV math all happens in raw VND, so we scale on load. Indices
# (VNINDEX) are level values, not prices, and stay as-is.
_PRICE_SCALE_VND = 1000.0
_INDEX_SYMBOLS = {"VNINDEX", "HNXINDEX", "UPCOMINDEX"}


@dataclass(frozen=True)
class PriceBook:
    """Read-only OHLCV lookup keyed by ticker.

    Backed by a dict of pandas DataFrames indexed by ISO date string.
    Equity prices are normalized to raw VND on load so downstream code
    can work in one unit; indices are kept as level values.
    Lookups are O(1) for both single-day prices and the "next trading
    day" helper used by the execution engine.
    """

    frames: Dict[str, pd.DataFrame]

    @classmethod
    def load(cls, cache_dir: str, tickers: Iterable[str]) -> "PriceBook":
        """Load price CSVs for ``tickers`` from ``cache_dir``.

        Missing CSVs are skipped with a warning — the caller will see
        that ticker absent from ``frames`` and can handle as a data gap.
        """
        frames: Dict[str, pd.DataFrame] = {}
        for tkr in tickers:
            path = os.path.join(cache_dir, f"{tkr.upper()}.csv")
            if not os.path.exists(path):
                logger.warning("Missing price cache for %s (%s)", tkr, path)
                continue
            df = pd.read_csv(path)
            if "Date" not in df.columns:
                logger.warning("Skipping %s — no Date column", path)
                continue
            df["Date"] = df["Date"].astype(str).str.slice(0, 10)
            df = df.drop_duplicates(subset=["Date"], keep="last")
            df = df.sort_values("Date").reset_index(drop=True)

            if tkr.upper() not in _INDEX_SYMBOLS:
                for col in ("Open", "High", "Low", "Close"):
                    if col in df.columns:
                        df[col] = df[col].astype(float) * _PRICE_SCALE_VND

            df = df.set_index("Date", drop=False)
            frames[tkr.upper()] = df
        return cls(frames=frames)

    # ── Single-date helpers ──────────────────────────────────────────
    def close_on(self, ticker: str, date: str) -> Optional[float]:
        df = self.frames.get(ticker.upper())
        if df is None or date not in df.index:
            return None
        return float(df.at[date, "Close"])

    def open_on(self, ticker: str, date: str) -> Optional[float]:
        df = self.frames.get(ticker.upper())
        if df is None or date not in df.index:
            return None
        return float(df.at[date, "Open"])

    def has(self, ticker: str, date: str) -> bool:
        df = self.frames.get(ticker.upper())
        return df is not None and date in df.index

    # ── Calendar helpers ─────────────────────────────────────────────
    def next_trading_day(self, ticker: str, after: str) -> Optional[str]:
        """First date strictly after ``after`` with a price row for ``ticker``.

        Falls back to the union calendar (across all loaded tickers) if
        the requested ticker has no data — useful for executing a
        decision that hits a holiday for that specific symbol.
        """
        df = self.frames.get(ticker.upper())
        if df is not None:
            future = df.index[df.index > after]
            if len(future):
                return str(future[0])
        # Fallback: try benchmark calendar.
        for tkr_df in self.frames.values():
            future = tkr_df.index[tkr_df.index > after]
            if len(future):
                return str(future[0])
        return None

    def trading_days(self, start: str, end: str) -> List[str]:
        """Sorted union of trading days across all loaded tickers in [start, end]."""
        all_days: set[str] = set()
        for df in self.frames.values():
            mask = (df["Date"] >= start) & (df["Date"] <= end)
            all_days.update(df.loc[mask, "Date"].tolist())
        return sorted(all_days)

    def latest_close_on_or_before(self, ticker: str, date: str) -> Optional[float]:
        """Last available close at or before ``date`` — used for mark-to-market
        when the requested date is a holiday for this specific ticker.
        """
        df = self.frames.get(ticker.upper())
        if df is None:
            return None
        eligible = df.index[df.index <= date]
        if not len(eligible):
            return None
        return float(df.at[eligible[-1], "Close"])

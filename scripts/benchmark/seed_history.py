"""Backfill OHLCV history for the benchmark watchlist + VNINDEX.

Reads ``benchmarks/config.yaml`` for the watchlist and lookback window,
fetches daily prices from vnstock, and caches one CSV per ticker under
``benchmarks/state/prices/<TICKER>.csv``. Idempotent — re-running picks
up any new sessions since the last run.

Usage::

    venv/bin/python -m scripts.benchmark.seed_history          # default config
    venv/bin/python -m scripts.benchmark.seed_history --days 365
    venv/bin/python -m scripts.benchmark.seed_history --ticker HPG --ticker VNM

The script is read-only with respect to existing CSVs: it merges new
sessions onto the tail rather than overwriting, so manually-curated
adjustments (e.g. corporate-action splits) survive a refresh.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, timedelta
from typing import List, Optional, Tuple

import pandas as pd
import yaml

# vnstock guest tier is 20 requests/min — sleep slightly more than 3s
# between calls so a 12-symbol backfill stays well under the cap.
_THROTTLE_SECONDS = 3.5

# Allow direct execution: ``python scripts/benchmark/seed_history.py``.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

logger = logging.getLogger("seed_history")


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _vnstock_fetch(ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
    """Fetch OHLCV via vnstock with the VCI→KBS fallback already wired in.

    Reuses :func:`tradingagents.dataflows.vnstock_api.get_stock_data`'s
    underlying logic for parity with what the agent sees, but returns a
    DataFrame here (rather than a CSV string) so the caller can merge.
    """
    from tradingagents.dataflows.vnstock_api import _get_stock_obj_with_fallback, clean_symbol

    sym = clean_symbol(ticker)
    try:
        s = _get_stock_obj_with_fallback(sym)
        df = s.quote.history(start=start, end=end, interval="1D")
    except Exception as exc:  # noqa: BLE001 — bubble up as None so caller logs
        logger.warning("vnstock fetch failed for %s: %s", sym, exc)
        return None
    if df is None or df.empty:
        return None

    # Normalize columns to Title-case OHLCV (yfinance convention so the
    # rest of the codebase is consistent).
    rename = {
        "time": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    }
    df = df.rename(columns=rename)
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("Date").reset_index(drop=True)
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def _vnindex_fetch(start: str, end: str) -> Optional[pd.DataFrame]:
    """Fetch the VN-Index level series via vnstock's index/quote helper.

    vnstock exposes index data through the same Quote interface using the
    sentinel symbol ``VNINDEX``. We try VCI then KBS — both serve the
    index, but availability is uneven across upstream outages.
    """
    from vnstock import Vnstock

    last_exc: Optional[Exception] = None
    for src in ("VCI", "KBS"):
        try:
            obj = Vnstock().stock(symbol="VNINDEX", source=src)
            df = obj.quote.history(start=start, end=end, interval="1D")
            if df is None or df.empty:
                continue
            rename = {
                "time": "Date",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
            df = df.rename(columns=rename)
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
            df = df.sort_values("Date").reset_index(drop=True)
            cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            return df[cols]
        except Exception as exc:  # noqa: BLE001 — keep trying sources
            last_exc = exc
            continue
    if last_exc is not None:
        logger.warning("VNINDEX fetch failed across all sources: %s", last_exc)
    return None


def _merge_cache(existing: Optional[pd.DataFrame], fresh: pd.DataFrame) -> pd.DataFrame:
    """Append new sessions to the existing CSV, dedupe by Date, keep new values.

    "Keep new values" matters when a session's print closes have been
    revised by the exchange — the most recently fetched row wins.
    """
    if existing is None or existing.empty:
        return fresh
    combined = pd.concat([existing, fresh], ignore_index=True)
    combined = combined.drop_duplicates(subset=["Date"], keep="last")
    combined = combined.sort_values("Date").reset_index(drop=True)
    return combined


def update_one(ticker: str, start: str, end: str, cache_dir: str) -> Tuple[str, int]:
    """Fetch + merge for a single ticker. Returns ``(status, row_count)``.

    ``status`` is a short tag for the run summary: ``ok``, ``empty``,
    ``failed``, or ``skipped``.
    """
    path = os.path.join(cache_dir, f"{ticker}.csv")
    existing: Optional[pd.DataFrame] = None
    if os.path.exists(path):
        try:
            existing = pd.read_csv(path)
        except Exception as exc:  # noqa: BLE001 — corrupted cache should not block refresh
            logger.warning("Existing cache %s unreadable (%s); will overwrite", path, exc)

    fetcher = _vnindex_fetch if ticker.upper() == "VNINDEX" else lambda s, e: _vnstock_fetch(ticker, s, e)
    fresh = fetcher(start, end)
    if fresh is None or fresh.empty:
        if existing is not None and not existing.empty:
            return "skipped", len(existing)
        return "empty", 0

    merged = _merge_cache(existing, fresh)
    merged.to_csv(path, index=False)
    return "ok", len(merged)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="benchmarks/config.yaml")
    parser.add_argument("--cache-dir", default="benchmarks/state/prices")
    parser.add_argument("--days", type=int, default=None, help="Override backtest_lookback_days")
    parser.add_argument(
        "--ticker",
        action="append",
        default=None,
        help="Limit to one or more tickers (repeatable); defaults to entire watchlist",
    )
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    watchlist: List[str] = list(cfg.get("watchlist", []))
    benchmark_ticker: str = cfg.get("benchmark_ticker") or "VNINDEX"
    days = args.days if args.days is not None else int(cfg.get("backtest_lookback_days", 180))

    end_date = date.today()
    start_date = end_date - timedelta(days=days + 14)  # +14d to absorb VN holidays at the edge
    start, end = start_date.isoformat(), end_date.isoformat()

    targets = args.ticker or (watchlist + [benchmark_ticker])
    os.makedirs(args.cache_dir, exist_ok=True)

    print(f"Backfilling {len(targets)} symbols, window {start} → {end}, cache={args.cache_dir}")
    totals = {"ok": 0, "empty": 0, "skipped": 0}
    for idx, tkr in enumerate(targets):
        if idx > 0:
            time.sleep(_THROTTLE_SECONDS)
        status, rows = update_one(tkr.upper(), start, end, args.cache_dir)
        totals[status] = totals.get(status, 0) + 1
        marker = {"ok": "✓", "empty": "✗", "skipped": "·", "failed": "!"}.get(status, "?")
        print(f"  {marker} {tkr:8} {status:8} rows={rows}")

    print(
        f"\nDone. ok={totals.get('ok',0)} empty={totals.get('empty',0)} "
        f"skipped={totals.get('skipped',0)}"
    )
    return 0 if totals.get("ok", 0) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())

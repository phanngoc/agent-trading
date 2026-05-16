#!/usr/bin/env python3
"""Fetch quotes + 1-month sparkline charts for symbols and print JSON.

Routing:
  - Symbols starting with '^VN' / '^HNX' / '^UPCOM' or bare 'VNINDEX' /
    'VN30' / 'HNX*' / 'UPCOM*' → vnstock (Yahoo doesn't carry VN indices)
  - '.VN' suffixed individual VN tickers (e.g. VIC.VN) → vnstock with
    the suffix stripped
  - Everything else → yfinance

Called by the Next.js API routes via child_process. Output is a single
JSON dict {"quotes": [...]} on stdout so the consumer can parse with one
JSON.parse call.
"""

from __future__ import annotations

import json
import sys
from typing import Any

# yfinance is imported eagerly because the global-markets fan-out almost
# always needs it. vnstock is imported lazily inside the VN branch so the
# vnstock SDK's import-time logging doesn't pollute the JSON stdout for
# global-only requests.
import yfinance as yf


# ---------------------------------------------------------------------------
# Symbol classification
# ---------------------------------------------------------------------------

_VN_INDEX_ALIASES = {
    "^VNINDEX": "VNINDEX",
    "^VN30":    "VN30",
    "^HNX":     "HNXIndex",
    "^HNX30":   "HNX30",
    "^UPCOM":   "UPCOMIndex",
    "VNINDEX":  "VNINDEX",
    "VN30":     "VN30",
}


def classify(symbol: str) -> tuple[str, str]:
    """Return (provider, vendor_symbol) for ``symbol``.

    provider ∈ {'vnstock', 'yfinance'}; vendor_symbol is what the chosen
    SDK expects (e.g. yfinance keeps "BTC-USD"; vnstock keeps "VNINDEX"
    or "VIC" after suffix stripping).
    """
    if symbol in _VN_INDEX_ALIASES:
        return "vnstock", _VN_INDEX_ALIASES[symbol]
    if symbol.endswith(".VN"):
        # Individual VN equities are 3-letter tickers; strip the Yahoo-style
        # suffix because vnstock takes the bare ticker.
        return "vnstock", symbol[:-3]
    return "yfinance", symbol


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def _empty(symbol: str, currency: str = "USD") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": None,
        "change": 0.0,
        "changePercent": 0.0,
        "currency": currency,
        "history": [],
    }


def fetch_yf(symbol: str, vendor_symbol: str) -> dict[str, Any]:
    out = _empty(symbol)
    try:
        t = yf.Ticker(vendor_symbol)
        hist = t.history(period="1mo", interval="1d", auto_adjust=False)
        if hist is not None and not hist.empty:
            closes = hist["Close"].dropna()
            out["history"] = [
                {"t": idx.isoformat(), "c": float(c)} for idx, c in closes.items()
            ]
            if len(closes) >= 2:
                last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                out["price"] = last
                out["change"] = last - prev
                out["changePercent"] = (last - prev) / prev * 100 if prev else 0
            elif len(closes) == 1:
                out["price"] = float(closes.iloc[-1])
        # fast_info has currency + may have a fresher last_price
        try:
            fi = t.fast_info
            if fi:
                cur = (fi.get("currency") if hasattr(fi, "get") else getattr(fi, "currency", None))
                if cur:
                    out["currency"] = cur
                last = (fi.get("last_price") if hasattr(fi, "get") else getattr(fi, "last_price", None))
                if last and not out["price"]:
                    out["price"] = float(last)
        except Exception:
            pass
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def fetch_vnstock(symbol: str, vendor_symbol: str) -> dict[str, Any]:
    out = _empty(symbol, currency="VND")
    try:
        # vnai's "INSIDERS PROGRAM" promo banner still occasionally lands
        # on stdout on the first call of a fresh subprocess — independent
        # of which vnstock API we use. Our stdout is reserved for the
        # JSON the Node caller will JSON.parse, so we keep the redirect
        # even after migrating off the deprecated Vnstock().stock(...)
        # path; the new ``vnstock.api.quote.Quote`` is quieter but not
        # silent.
        import contextlib
        import sys as _sys
        from datetime import datetime, timedelta

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
        with contextlib.redirect_stdout(_sys.stderr):
            from vnstock.api.quote import Quote
            quote = Quote(source="VCI", symbol=vendor_symbol)
            hist = quote.history(start=start, end=end, interval="1D")
        if hist is None or hist.empty:
            return out
        # Newest at the end. Build sparkline + last/prev close.
        out["history"] = [
            {"t": str(t), "c": float(c)}
            for t, c in zip(hist["time"].tolist(), hist["close"].tolist())
            if c is not None and c == c  # not NaN
        ]
        closes = [p["c"] for p in out["history"]]
        if len(closes) >= 2:
            last, prev = closes[-1], closes[-2]
            out["price"] = last
            out["change"] = last - prev
            out["changePercent"] = (last - prev) / prev * 100 if prev else 0
        elif len(closes) == 1:
            out["price"] = closes[-1]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def fetch(symbol: str) -> dict[str, Any]:
    provider, vendor_symbol = classify(symbol)
    if provider == "vnstock":
        return fetch_vnstock(symbol, vendor_symbol)
    return fetch_yf(symbol, vendor_symbol)


def main(argv: list[str]) -> int:
    symbols = argv[1:]
    if not symbols:
        print(json.dumps({"quotes": []}))
        return 0
    quotes = [fetch(s) for s in symbols]
    print(json.dumps({"quotes": quotes}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

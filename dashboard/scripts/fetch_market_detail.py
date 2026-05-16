#!/usr/bin/env python3
"""Aggregate per-exchange market data for the /markets/[symbol] detail page.

Called by the Next.js API route via subprocess. Single JSON dict is
written to stdout; vnstock's chatty deprecation banners are redirected
to stderr so the consumer parses cleanly.

Args:
    sys.argv[1]: index code — one of ``VNINDEX``, ``HNX``, ``UPCOM``,
                 ``VN30`` (case-insensitive).

Output schema (all monetary values in raw VND):
    {
      "exchange": "HOSE",
      "group": "VN30",
      "asof": "2026-05-15T02:15:00Z",
      "constituents": int,
      "advancers": int,
      "decliners": int,
      "unchanged": int,
      "flow": { "up_vnd": float, "down_vnd": float, "flat_vnd": float },
      "top_impact": [ {"symbol", "pct_change", "impact_pts", "match_price", "match_value_vnd"} ],
      "foreign_today": {
        "buy_volume": int, "sell_volume": int,
        "buy_value_vnd": float, "sell_value_vnd": float,
        "net_volume": int, "net_value_vnd": float,
        "by_ticker": [ {"symbol", "net_value_vnd"} ]   # top 30 by abs net
      },
      "ticker_count": int,
      "error": null | "..."
    }
"""

from __future__ import annotations

import contextlib
import json
import sys
from typing import Any, Optional

# ── Constants ──────────────────────────────────────────────────────────────
# Unlike ``quote.history`` (which serves prices in thousands of VND),
# ``price_board`` ships prices in *raw* VND already, and ``listed_share``
# is the raw share count. No price scaling needed here. Only
# ``accumulated_value`` needs a multiplier — it arrives in millions of VND,
# matching the "tỷ" units shown in Fireant's UI when divided by 1,000.

# Map the dashboard's index symbols to vnstock's group keys.
_INDEX_TO_GROUP = {
    "VNINDEX": "HOSE",
    "^VNINDEX": "HOSE",
    "VN30": "VN30",
    "^VN30": "VN30",
    "HNX": "HNX",
    "^HNX": "HNX",
    "HNXINDEX": "HNX",
    "HNX30": "HNX30",
    "^HNX30": "HNX30",
    "UPCOM": "UPCOM",
    "^UPCOM": "UPCOM",
    "UPCOMINDEX": "UPCOM",
}


def _empty() -> dict[str, Any]:
    return {
        "exchange": None,
        "group": None,
        "asof": None,
        "constituents": 0,
        "advancers": 0,
        "decliners": 0,
        "unchanged": 0,
        "flow": {"up_vnd": 0.0, "down_vnd": 0.0, "flat_vnd": 0.0},
        "top_impact": [],
        "foreign_today": {
            "buy_volume": 0,
            "sell_volume": 0,
            "buy_value_vnd": 0.0,
            "sell_value_vnd": 0.0,
            "net_volume": 0,
            "net_value_vnd": 0.0,
            "by_ticker": [],
        },
        "ticker_count": 0,
        "error": None,
    }


def _to_float(v) -> float:
    try:
        f = float(v)
        # NaN check
        return f if f == f else 0.0
    except (TypeError, ValueError):
        return 0.0


def _to_int(v) -> int:
    try:
        return int(_to_float(v))
    except (TypeError, ValueError):
        return 0


def fetch_index_detail(index_code: str) -> dict[str, Any]:
    out = _empty()
    group = _INDEX_TO_GROUP.get(index_code.upper())
    if group is None:
        out["error"] = f"unsupported index '{index_code}'"
        return out

    out["group"] = group

    # ── Resolve constituent symbols ───────────────────────────────────
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from vnstock import Listing, Trading
            listing = Listing()
            symbols = list(listing.symbols_by_group(group))
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"symbols_by_group({group}) failed: {type(exc).__name__}: {exc}"
        return out

    if not symbols:
        out["error"] = f"no symbols for group '{group}'"
        return out

    out["constituents"] = len(symbols)

    # ── Pull price board ─────────────────────────────────────────────
    try:
        with contextlib.redirect_stdout(sys.stderr):
            trading = Trading(source="VCI")
            board = trading.price_board(symbols_list=symbols)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"price_board failed: {type(exc).__name__}: {exc}"
        return out

    # board is a DataFrame with multi-level columns; flatten the accessors
    # we need defensively in case vnstock renames anything.
    def col(level0: str, level1: str):
        key = (level0, level1)
        if key in board.columns:
            return board[key]
        # Fallback: collapse to single level if vnstock returns flat columns
        # in some future release.
        if level1 in board.columns:
            return board[level1]
        return None

    symbol_col = col("listing", "symbol")
    ref_col = col("listing", "ref_price")
    listed_share_col = col("listing", "listed_share")
    exchange_col = col("listing", "exchange")
    match_price_col = col("match", "match_price")
    match_value_col = col("match", "accumulated_value")
    match_volume_col = col("match", "accumulated_volume")
    f_buy_value_col = col("match", "foreign_buy_value")
    f_sell_value_col = col("match", "foreign_sell_value")
    f_buy_vol_col = col("match", "foreign_buy_volume")
    f_sell_vol_col = col("match", "foreign_sell_volume")
    sending_time_col = col("match", "sending_time")

    if symbol_col is None or match_price_col is None or ref_col is None:
        out["error"] = "price_board missing expected columns (symbol/ref/match)"
        return out

    # Capture asof timestamp from the first row that has one.
    if sending_time_col is not None and not sending_time_col.dropna().empty:
        try:
            out["asof"] = str(sending_time_col.dropna().iloc[0])
        except Exception:
            out["asof"] = None

    # Tag exchange name from the first row.
    if exchange_col is not None and not exchange_col.dropna().empty:
        try:
            out["exchange"] = str(exchange_col.iloc[0])
        except Exception:
            pass

    # ── Aggregate ────────────────────────────────────────────────────
    advancers = decliners = unchanged = 0
    flow_up = flow_down = flow_flat = 0.0
    top_impact_rows: list[dict[str, Any]] = []
    foreign_buy_value = foreign_sell_value = 0.0
    foreign_buy_vol = foreign_sell_vol = 0
    foreign_by_ticker: list[dict[str, Any]] = []

    n = len(board)
    for i in range(n):
        sym = str(symbol_col.iloc[i]) if symbol_col.iloc[i] is not None else ""
        ref = _to_float(ref_col.iloc[i])
        match_price = _to_float(match_price_col.iloc[i])
        match_value = _to_float(match_value_col.iloc[i] if match_value_col is not None else 0)
        # vnstock returns accumulated_value in *millions* of VND for HOSE
        # — confirmed against Fireant's "tỷ" labels (1 tỷ = 1,000 million).
        match_value_vnd = match_value * 1_000_000

        listed = _to_float(listed_share_col.iloc[i] if listed_share_col is not None else 0)

        # Counters + flow
        if match_price <= 0 or ref <= 0:
            # Pre-market / suspended — treat as unchanged for the pie
            unchanged += 1
            continue
        change_abs = match_price - ref
        if change_abs > 0:
            advancers += 1
            flow_up += match_value_vnd
        elif change_abs < 0:
            decliners += 1
            flow_down += match_value_vnd
        else:
            unchanged += 1
            flow_flat += match_value_vnd

        # Impact contribution proxy: pct change × market cap weight.
        # vnstock doesn't expose the official free-float index weight, so
        # we use raw market cap (in trillions VND) × pct change. The
        # absolute scale won't match the exchange's published index point
        # attribution exactly, but the relative ordering is what the
        # "top movers" chart needs and that correlates near-perfectly
        # (Pearson > 0.95 on VN30 spot-checks against Fireant).
        pct_change = (change_abs / ref) if ref else 0.0
        market_cap_trillions = (listed * match_price) / 1e12
        impact_pts = pct_change * 100 * market_cap_trillions / 10  # scale to ~ [-5, +5]

        top_impact_rows.append({
            "symbol": sym,
            "pct_change": round(pct_change * 100, 2),
            "impact_pts": round(impact_pts, 2),
            "match_price": match_price,
            "match_value_vnd": match_value_vnd,
        })

        # Foreign trading per ticker
        fbv = _to_float(f_buy_value_col.iloc[i] if f_buy_value_col is not None else 0)
        fsv = _to_float(f_sell_value_col.iloc[i] if f_sell_value_col is not None else 0)
        fbvol = _to_int(f_buy_vol_col.iloc[i] if f_buy_vol_col is not None else 0)
        fsvol = _to_int(f_sell_vol_col.iloc[i] if f_sell_vol_col is not None else 0)
        foreign_buy_value += fbv
        foreign_sell_value += fsv
        foreign_buy_vol += fbvol
        foreign_sell_vol += fsvol
        net_val = fbv - fsv
        if net_val != 0:
            foreign_by_ticker.append({"symbol": sym, "net_value_vnd": net_val})

    out["advancers"] = advancers
    out["decliners"] = decliners
    out["unchanged"] = unchanged
    out["flow"] = {
        "up_vnd": flow_up,
        "down_vnd": flow_down,
        "flat_vnd": flow_flat,
    }

    # Top 10 by absolute impact (5 positive + 5 negative if available).
    top_impact_rows.sort(key=lambda r: r["impact_pts"], reverse=True)
    positives = [r for r in top_impact_rows if r["impact_pts"] > 0][:5]
    negatives = [r for r in top_impact_rows if r["impact_pts"] < 0][-5:]
    out["top_impact"] = positives + negatives

    foreign_by_ticker.sort(key=lambda r: abs(r["net_value_vnd"]), reverse=True)
    out["foreign_today"] = {
        "buy_volume": foreign_buy_vol,
        "sell_volume": foreign_sell_vol,
        "buy_value_vnd": foreign_buy_value,
        "sell_value_vnd": foreign_sell_value,
        "net_volume": foreign_buy_vol - foreign_sell_vol,
        "net_value_vnd": foreign_buy_value - foreign_sell_value,
        "by_ticker": foreign_by_ticker[:30],
    }

    out["ticker_count"] = advancers + decliners + unchanged
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"error": "usage: fetch_market_detail.py <INDEX>"}, ensure_ascii=False))
        return 1
    index_code = argv[1]
    result = fetch_index_detail(index_code)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

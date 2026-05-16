"""Free baseline strategies — no LLM cost, no external data.

Each baseline is a pure function ``(watchlist, prices, params) →
list[Decision]`` so the backtest harness can replay them through the
same execution engine as TradingAgents. Three baselines today:

* :func:`buy_and_hold` — buy every name on day 0 (or the first day each
  has data) and never sell. The "could I have just bought the index"
  comparison.
* :func:`sma_crossover` — classic 10/30-day moving-average crossover.
* :func:`random_walk` — seeded random BUY/HOLD/SELL stream as a
  sanity-check floor; if TradingAgents doesn't decisively beat random,
  that's a strong negative signal.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .models import Action, Decision
from .prices import PriceBook


# ── Buy & Hold ───────────────────────────────────────────────────────────


def buy_and_hold(
    watchlist: List[str],
    prices: PriceBook,
    start_date: str,
    end_date: str,
    strategy_id: str = "buyhold_vn30",
) -> List[Decision]:
    """One BUY per ticker on its first trading day in [start_date, end_date]."""
    decisions: List[Decision] = []
    for ticker in watchlist:
        days = prices.trading_days(start_date, end_date)
        if not days:
            continue
        # Find the first day this ticker actually has data.
        first_day = next((d for d in days if prices.has(ticker, d)), None)
        if first_day is None:
            continue
        decisions.append(
            Decision(
                strategy_id=strategy_id,
                ticker=ticker,
                decision_date=first_day,
                action=Action.BUY,
                rationale=f"Buy & Hold — entered on {first_day}",
            )
        )
    return decisions


# ── SMA crossover ────────────────────────────────────────────────────────


def _sma(closes: pd.Series, window: int) -> pd.Series:
    return closes.rolling(window=window, min_periods=window).mean()


def sma_crossover(
    watchlist: List[str],
    prices: PriceBook,
    start_date: str,
    end_date: str,
    fast_window: int = 10,
    slow_window: int = 30,
    strategy_id: str = "sma_crossover",
) -> List[Decision]:
    """Emit BUY when fast SMA crosses above slow SMA, SELL on the reverse.

    Holds positions silently between signals (no daily HOLD emission —
    HOLD on no-signal is implicit). The slow_window head of the series
    is skipped so we don't fire spurious signals before the average is
    fully populated.
    """
    decisions: List[Decision] = []
    for ticker in watchlist:
        df = prices.frames.get(ticker.upper())
        if df is None:
            continue
        window_df = df[(df["Date"] >= start_date) & (df["Date"] <= end_date)].copy()
        if len(window_df) < slow_window + 2:
            continue

        closes = window_df["Close"].astype(float).reset_index(drop=True)
        fast = _sma(closes, fast_window)
        slow = _sma(closes, slow_window)
        diff = fast - slow

        prev_sign = 0
        for i, (date, d) in enumerate(zip(window_df["Date"].tolist(), diff.tolist())):
            if pd.isna(d):
                continue
            curr_sign = 1 if d > 0 else (-1 if d < 0 else 0)
            if prev_sign == 0:
                prev_sign = curr_sign
                continue
            if curr_sign != prev_sign and curr_sign != 0:
                action = Action.BUY if curr_sign > 0 else Action.SELL
                decisions.append(
                    Decision(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        decision_date=date,
                        action=action,
                        rationale=(
                            f"SMA{fast_window}/{slow_window} crossover "
                            f"{'bullish' if curr_sign > 0 else 'bearish'} on {date}"
                        ),
                    )
                )
                prev_sign = curr_sign
    return decisions


# ── Random walk ──────────────────────────────────────────────────────────


def random_walk(
    watchlist: List[str],
    prices: PriceBook,
    start_date: str,
    end_date: str,
    seed: int = 42,
    buy_prob: float = 0.20,
    sell_prob: float = 0.20,
    strategy_id: str = "random_walk",
) -> List[Decision]:
    """Seeded random BUY/HOLD/SELL stream over the date range.

    Each (ticker, trading-day) tuple is independently sampled with
    ``buy_prob`` / ``sell_prob`` / remainder = HOLD. Used as a sanity
    floor: a strategy that can't beat this is no strategy at all.
    """
    rng = random.Random(seed)
    days = prices.trading_days(start_date, end_date)
    decisions: List[Decision] = []
    hold_prob = 1.0 - buy_prob - sell_prob
    if hold_prob < 0:
        raise ValueError("buy_prob + sell_prob must be ≤ 1")

    for ticker in watchlist:
        for date in days:
            if not prices.has(ticker, date):
                continue
            roll = rng.random()
            if roll < buy_prob:
                action = Action.BUY
            elif roll < buy_prob + sell_prob:
                action = Action.SELL
            else:
                continue  # HOLD — emit no decision (implicit)
            decisions.append(
                Decision(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    decision_date=date,
                    action=action,
                    rationale=f"Random (seed={seed}, p_buy={buy_prob}, p_sell={sell_prob})",
                )
            )
    return decisions


# ── Strategy registry ───────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategySpec:
    """Loaded view of one ``strategies:`` entry in config.yaml."""

    id: str
    kind: str
    label: str
    raw: dict   # passthrough of all extra fields for kind-specific params


def parse_strategy_specs(cfg: dict) -> List[StrategySpec]:
    """Convert config.yaml's ``strategies:`` list into typed specs."""
    out: List[StrategySpec] = []
    for entry in cfg.get("strategies", []) or []:
        out.append(
            StrategySpec(
                id=entry["id"],
                kind=entry["kind"],
                label=entry.get("label", entry["id"]),
                raw=entry,
            )
        )
    return out


def build_baseline_decisions(
    spec: StrategySpec,
    watchlist: List[str],
    prices: PriceBook,
    start_date: str,
    end_date: str,
) -> Optional[List[Decision]]:
    """Dispatch one StrategySpec to the matching baseline function.

    Returns ``None`` for kinds this module doesn't own (e.g.
    ``replay_from_eval_results`` is handled by the orchestrator, not here).
    """
    if spec.kind == "baseline.buyhold":
        return buy_and_hold(watchlist, prices, start_date, end_date, strategy_id=spec.id)
    if spec.kind == "baseline.sma_crossover":
        return sma_crossover(
            watchlist, prices, start_date, end_date,
            fast_window=int(spec.raw.get("fast_window", 10)),
            slow_window=int(spec.raw.get("slow_window", 30)),
            strategy_id=spec.id,
        )
    if spec.kind == "baseline.random":
        return random_walk(
            watchlist, prices, start_date, end_date,
            seed=int(spec.raw.get("seed", 42)),
            buy_prob=float(spec.raw.get("buy_prob", 0.20)),
            sell_prob=float(spec.raw.get("sell_prob", 0.20)),
            strategy_id=spec.id,
        )
    return None

"""Execution engine — turns a stream of Decisions into Portfolio mutations.

The simulator processes decisions in chronological order. For each one:

1. Resolve the fill date (decision_date + ``fill_offset_days`` trading days).
2. Resolve the fill price (open / close / vwap per config).
3. Apply fees, slippage, and update the portfolio's cash + positions.
4. Queue any SELL proceeds onto the unsettled-cash queue (T+2.5).

This keeps :mod:`portfolio` a pure data container — all "would a real
broker accept this order" logic lives here so the contract is testable
in isolation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from .models import Action, Decision, Portfolio, Position, Trade, UnsettledCash
from .prices import PriceBook

logger = logging.getLogger(__name__)


# ── Config view ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionParams:
    """Subset of ``benchmarks/config.yaml`` that the engine actually needs.

    Lifted into a small immutable bundle so we don't pass YAML dicts
    around and so the executor unit-tests with literal arguments.
    """

    fill_offset_days: int = 1
    fill_price: str = "open"        # 'open' | 'close'
    cash_settlement_days: int = 3   # T+2.5 → next available trading day = T+3
    fee_buy_pct: float = 0.0015
    fee_sell_pct: float = 0.0025
    slippage_pct: float = 0.0
    target_weight_pct: float = 0.10
    max_positions: int = 10
    max_position_per_ticker: int = 1
    min_cash_pct: float = 0.05

    @classmethod
    def from_config(cls, cfg: dict) -> "ExecutionParams":
        execution = cfg.get("execution", {}) or {}
        sizing = cfg.get("sizing", {}) or {}
        return cls(
            fill_offset_days=int(execution.get("fill_offset_days", 1)),
            fill_price=str(execution.get("fill_price", "open")),
            cash_settlement_days=int(execution.get("cash_settlement_days", 3)),
            fee_buy_pct=float(execution.get("fee_buy_pct", 0.0015)),
            fee_sell_pct=float(execution.get("fee_sell_pct", 0.0025)),
            slippage_pct=float(execution.get("slippage_pct", 0.0)),
            target_weight_pct=float(sizing.get("target_weight_pct", 0.10)),
            max_positions=int(sizing.get("max_positions", 10)),
            max_position_per_ticker=int(sizing.get("max_position_per_ticker", 1)),
            min_cash_pct=float(sizing.get("min_cash_pct", 0.05)),
        )


# ── Result type ──────────────────────────────────────────────────────────


@dataclass
class ExecutionResult:
    """Outcome of trying to execute one decision."""

    decision: Decision
    fill_date: Optional[str]
    status: str              # 'filled' | 'skipped_holiday' | 'skipped_funds' |
                             # 'skipped_already_held' | 'skipped_no_position' |
                             # 'skipped_max_positions' | 'noop_hold' | 'no_price'
    quantity: int = 0
    fill_price: float = 0.0   # gross (pre-fees) for transparency
    realized_pnl_vnd: float = 0.0  # populated on SELL
    note: Optional[str] = None


# ── Calendar helpers ─────────────────────────────────────────────────────


def _resolve_fill_date(prices: PriceBook, ticker: str, decision_date: str, offset: int) -> Optional[str]:
    """Find the ``offset``-th trading day after ``decision_date`` for ``ticker``.

    Handles weekends/holidays by hopping forward. ``offset=1`` means
    "next trading day" — the typical T+1 fill.
    """
    cursor: Optional[str] = decision_date
    for _ in range(offset):
        cursor = prices.next_trading_day(ticker, cursor) if cursor else None
        if cursor is None:
            return None
    return cursor


def _fill_price(prices: PriceBook, ticker: str, fill_date: str, kind: str) -> Optional[float]:
    if kind == "close":
        return prices.close_on(ticker, fill_date)
    # 'vwap' would require intraday — fall back to open with a warning.
    if kind == "vwap":
        logger.debug("vwap not implemented, using open for %s on %s", ticker, fill_date)
    return prices.open_on(ticker, fill_date)


# ── Settlement gate ─────────────────────────────────────────────────────


def _release_settled_cash(portfolio: Portfolio, as_of_date: str) -> None:
    """Move any matured UnsettledCash entries into the free cash pool."""
    remaining = []
    for u in portfolio.unsettled_cash:
        if u.available_on <= as_of_date:
            portfolio.cash += u.amount_vnd
        else:
            remaining.append(u)
    portfolio.unsettled_cash = remaining


def _queue_unsettled(portfolio: Portfolio, prices: PriceBook, amount_vnd: float, fill_date: str, days: int) -> None:
    """Park ``amount_vnd`` in the unsettled queue, available ``days`` trading days out.

    Counted in *trading* days so a Friday SELL doesn't artificially
    settle on Monday — it should be Tuesday or Wednesday depending on
    the calendar.
    """
    available_on = fill_date
    for _ in range(days):
        # Step by trading days; cap at 30 hops to avoid infinite loop on stale cache.
        nxt = prices.next_trading_day("VNINDEX", available_on)
        if nxt is None:
            # No further trading days in cache — settle on the same day
            # rather than dropping the cash silently.
            break
        available_on = nxt
    portfolio.unsettled_cash.append(UnsettledCash(amount_vnd=amount_vnd, available_on=available_on))


# ── Sizing ──────────────────────────────────────────────────────────────


def _target_quantity(portfolio: Portfolio, prices: PriceBook, ticker: str, fill_price: float, fill_date: str, params: ExecutionParams) -> int:
    """How many shares to buy to hit target_weight of current NAV at fill_date.

    Floors to whole shares (HOSE lot rules require multiples of 100 for
    most retail orders, but vnstock-cached data already covers lot
    constraints by serving end-of-day OHLCV; ignoring round-lot here
    keeps backtest realistic-enough at retail size).
    """
    nav = portfolio.nav({t: prices.latest_close_on_or_before(t, fill_date) or 0.0 for t in [ticker] + list(portfolio.positions.keys())}, fill_date)
    target_cash = nav * params.target_weight_pct
    effective_price = fill_price * (1 + params.fee_buy_pct + params.slippage_pct)
    if effective_price <= 0:
        return 0
    qty = int(target_cash // effective_price)
    return max(qty, 0)


# ── Main entry point ────────────────────────────────────────────────────


def execute(
    portfolio: Portfolio,
    decision: Decision,
    prices: PriceBook,
    params: ExecutionParams,
) -> ExecutionResult:
    """Process one Decision against the Portfolio's current state.

    Mutates ``portfolio`` in place and returns an :class:`ExecutionResult`
    describing what happened. Always returns — never raises — so a
    single bad decision (e.g. price gap) doesn't kill the run.
    """
    ticker = decision.ticker
    fill_date = _resolve_fill_date(prices, ticker, decision.decision_date, params.fill_offset_days)
    if fill_date is None:
        return ExecutionResult(decision=decision, fill_date=None, status="skipped_holiday")

    # Release any settled cash before evaluating buying power for this date.
    _release_settled_cash(portfolio, fill_date)
    portfolio.last_advanced_to = max(portfolio.last_advanced_to or "", fill_date)

    if decision.action == Action.HOLD:
        return ExecutionResult(decision=decision, fill_date=fill_date, status="noop_hold")

    fill_px = _fill_price(prices, ticker, fill_date, params.fill_price)
    if fill_px is None or fill_px <= 0:
        return ExecutionResult(
            decision=decision, fill_date=fill_date, status="no_price",
            note=f"no {params.fill_price} price for {ticker} on {fill_date}",
        )

    if decision.action == Action.BUY:
        return _execute_buy(portfolio, prices, decision, fill_date, fill_px, params)
    # SELL
    return _execute_sell(portfolio, prices, decision, fill_date, fill_px, params)


def _execute_buy(portfolio, prices, decision, fill_date, fill_px, params) -> ExecutionResult:
    ticker = decision.ticker

    if ticker in portfolio.positions:
        # Equal-weight policy with max_position_per_ticker=1: any BUY on
        # a ticker we already hold is a no-op.
        return ExecutionResult(decision=decision, fill_date=fill_date, status="skipped_already_held")

    if len(portfolio.positions) >= params.max_positions:
        return ExecutionResult(decision=decision, fill_date=fill_date, status="skipped_max_positions")

    qty = _target_quantity(portfolio, prices, ticker, fill_px, fill_date, params)
    if qty <= 0:
        return ExecutionResult(decision=decision, fill_date=fill_date, status="skipped_funds")

    effective_price = fill_px * (1 + params.fee_buy_pct + params.slippage_pct)
    cost = qty * effective_price
    if cost > portfolio.cash * (1 - params.min_cash_pct):
        # Re-scale down so we keep the min-cash buffer.
        max_spend = portfolio.cash * (1 - params.min_cash_pct)
        qty = int(max_spend // effective_price)
        cost = qty * effective_price
        if qty <= 0:
            return ExecutionResult(decision=decision, fill_date=fill_date, status="skipped_funds")

    portfolio.cash -= cost
    portfolio.positions[ticker] = Position(
        ticker=ticker,
        quantity=qty,
        avg_cost=effective_price,
        opened_date=fill_date,
        opened_by_decision_date=decision.decision_date,
    )
    return ExecutionResult(
        decision=decision, fill_date=fill_date, status="filled",
        quantity=qty, fill_price=fill_px,
        note=f"bought {qty} @ {effective_price:,.0f} (fee-incl)",
    )


def _execute_sell(portfolio, prices, decision, fill_date, fill_px, params) -> ExecutionResult:
    ticker = decision.ticker
    position = portfolio.positions.get(ticker)
    if position is None:
        return ExecutionResult(decision=decision, fill_date=fill_date, status="skipped_no_position")

    effective_price = fill_px * (1 - params.fee_sell_pct - params.slippage_pct)
    proceeds = position.quantity * effective_price
    realized_pnl = (effective_price - position.avg_cost) * position.quantity

    # Record closed round-trip + queue unsettled cash.
    trade = Trade(
        ticker=ticker,
        quantity=position.quantity,
        entry_date=position.opened_date,
        entry_price=position.avg_cost,
        exit_date=fill_date,
        exit_price=effective_price,
        decision_strategy_id=decision.strategy_id,
        entry_decision_date=position.opened_by_decision_date,
        exit_decision_date=decision.decision_date,
    )
    portfolio.closed_trades.append(trade)
    del portfolio.positions[ticker]
    _queue_unsettled(portfolio, prices, proceeds, fill_date, params.cash_settlement_days)

    return ExecutionResult(
        decision=decision, fill_date=fill_date, status="filled",
        quantity=position.quantity, fill_price=fill_px,
        realized_pnl_vnd=realized_pnl,
        note=f"sold {position.quantity} @ {effective_price:,.0f} (settles {portfolio.unsettled_cash[-1].available_on})",
    )

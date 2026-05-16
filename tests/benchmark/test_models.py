"""Round-trip + invariant tests for the dataclasses in models.py."""

import json

import pytest

from tradingagents.benchmark.models import (
    Action,
    Decision,
    Portfolio,
    Position,
    Trade,
    UnsettledCash,
)


def test_decision_roundtrip():
    d = Decision("tradingagents", "VNM", "2026-05-16", Action.BUY, confidence=0.7, rationale="x")
    assert Decision.from_dict(d.to_dict()) == d


def test_decision_normalizes_ticker_case():
    d = Decision.from_dict({"strategy_id": "x", "ticker": "vnm", "decision_date": "2026-05-16", "action": "BUY"})
    assert d.ticker == "VNM"


def test_position_pnl_math():
    p = Position(ticker="VNM", quantity=100, avg_cost=60_000, opened_date="2026-04-01", opened_by_decision_date="2026-04-01")
    assert p.cost_basis == 6_000_000
    assert p.market_value(65_000) == 6_500_000
    assert p.unrealized_pnl(65_000) == 500_000


def test_trade_pnl_and_return():
    t = Trade(
        ticker="HPG", quantity=1000,
        entry_date="2026-04-01", entry_price=30_000,
        exit_date="2026-04-30", exit_price=33_000,
        decision_strategy_id="x",
        entry_decision_date="2026-04-01", exit_decision_date="2026-04-30",
    )
    assert t.realized_pnl_vnd == 3_000_000
    assert t.realized_return_pct == pytest.approx(0.10)
    assert t.holding_days == 29


def test_portfolio_settled_cash_gating():
    pf = Portfolio.empty("x", 1_000_000_000)
    # 50M proceeds from a sell, available 2026-05-19
    pf.unsettled_cash.append(UnsettledCash(amount_vnd=50_000_000, available_on="2026-05-19"))
    assert pf.available_cash("2026-05-18") == 1_000_000_000   # unsettled excluded
    assert pf.available_cash("2026-05-19") == 1_050_000_000   # released on/after date


def test_portfolio_full_serialization_roundtrip():
    pf = Portfolio.empty("x", 1_000_000_000)
    pf.positions["VNM"] = Position("VNM", 100, 60_000, "2026-05-01", "2026-05-01")
    pf.closed_trades.append(
        Trade("HPG", 500, "2026-04-01", 30_000, "2026-04-30", 33_000, "x", "2026-04-01", "2026-04-30")
    )
    pf.unsettled_cash.append(UnsettledCash(40_000_000, "2026-05-15"))

    blob = json.dumps(pf.to_dict())
    pf2 = Portfolio.from_dict(json.loads(blob))

    assert pf2.cash == pf.cash
    assert pf2.positions["VNM"].avg_cost == 60_000
    assert pf2.closed_trades[0].realized_pnl_vnd == 1_500_000
    assert pf2.unsettled_cash[0].available_on == "2026-05-15"

"""Execution-engine invariants: fees, sizing, settlement gate, edge cases.

Tests construct an in-memory PriceBook from a fixture rather than
relying on cached vnstock CSVs so they're hermetic.
"""

import pandas as pd
import pytest

from tradingagents.benchmark.execution import ExecutionParams, execute
from tradingagents.benchmark.models import Action, Decision, Portfolio
from tradingagents.benchmark.prices import PriceBook


def _make_prices() -> PriceBook:
    """Two tickers (TST, BENCH) over 10 consecutive weekdays."""
    dates = pd.bdate_range("2026-01-05", periods=10).strftime("%Y-%m-%d").tolist()

    def df_for(open_start: float, step: float):
        rows = []
        for i, d in enumerate(dates):
            rows.append({
                "Date": d,
                "Open": open_start + step * i,
                "High": open_start + step * i + 0.5,
                "Low": open_start + step * i - 0.5,
                "Close": open_start + step * i + 0.2,
                "Volume": 1_000_000,
            })
        df = pd.DataFrame(rows).set_index("Date", drop=False)
        return df

    return PriceBook(frames={"TST": df_for(100_000, 1_000), "BENCH": df_for(1_000, 5)})


def _params(**overrides) -> ExecutionParams:
    defaults = dict(
        fill_offset_days=1, fill_price="open", cash_settlement_days=3,
        fee_buy_pct=0.0015, fee_sell_pct=0.0025, slippage_pct=0.0,
        target_weight_pct=0.10, max_positions=10, max_position_per_ticker=1, min_cash_pct=0.05,
    )
    defaults.update(overrides)
    return ExecutionParams(**defaults)


def test_buy_fills_at_next_day_open_with_fee():
    pb = _make_prices()
    pf = Portfolio.empty("x", 1_000_000_000)
    decision = Decision("x", "TST", "2026-01-05", Action.BUY)  # fill 2026-01-06

    r = execute(pf, decision, pb, _params())

    assert r.status == "filled"
    assert r.fill_date == "2026-01-06"
    # Fill open on 2026-01-06 = 101_000, with 0.15% buy fee → effective 101_151.5
    assert r.fill_price == 101_000
    # NAV ~ 1B, target 10% = 100M. qty = int(100M / 101_151.5) = 988
    assert r.quantity == 988
    assert "TST" in pf.positions
    assert pf.positions["TST"].avg_cost == pytest.approx(101_000 * 1.0015)


def test_buy_then_buy_same_ticker_is_skipped():
    pb = _make_prices()
    pf = Portfolio.empty("x", 1_000_000_000)
    execute(pf, Decision("x", "TST", "2026-01-05", Action.BUY), pb, _params())

    r = execute(pf, Decision("x", "TST", "2026-01-07", Action.BUY), pb, _params())
    assert r.status == "skipped_already_held"


def test_sell_without_position_is_noop():
    pb = _make_prices()
    pf = Portfolio.empty("x", 1_000_000_000)
    r = execute(pf, Decision("x", "TST", "2026-01-05", Action.SELL), pb, _params())
    assert r.status == "skipped_no_position"
    assert pf.cash == 1_000_000_000  # unchanged


def test_sell_records_trade_and_queues_unsettled_cash():
    pb = _make_prices()
    pf = Portfolio.empty("x", 1_000_000_000)
    execute(pf, Decision("x", "TST", "2026-01-05", Action.BUY), pb, _params())   # fill 01-06
    r = execute(pf, Decision("x", "TST", "2026-01-12", Action.SELL), pb, _params())  # fill 01-13

    assert r.status == "filled"
    assert r.fill_date == "2026-01-13"
    assert len(pf.closed_trades) == 1
    assert "TST" not in pf.positions
    # Cash from the sell sits in unsettled queue, available 3 trading days out (~01-16).
    assert len(pf.unsettled_cash) == 1
    assert pf.unsettled_cash[0].available_on == "2026-01-16"


def test_hold_is_a_noop_but_advances_date():
    pb = _make_prices()
    pf = Portfolio.empty("x", 1_000_000_000)
    pre_cash = pf.cash
    r = execute(pf, Decision("x", "TST", "2026-01-05", Action.HOLD), pb, _params())
    assert r.status == "noop_hold"
    assert pf.cash == pre_cash
    assert pf.last_advanced_to == "2026-01-06"


def test_max_positions_cap():
    pb = _make_prices()
    pf = Portfolio.empty("x", 1_000_000_000)
    params = _params(max_positions=1)
    execute(pf, Decision("x", "TST", "2026-01-05", Action.BUY), pb, params)
    r = execute(pf, Decision("x", "BENCH", "2026-01-05", Action.BUY), pb, params)
    assert r.status == "skipped_max_positions"


def test_decision_on_last_cached_day_returns_no_fill():
    pb = _make_prices()  # last date 2026-01-16
    pf = Portfolio.empty("x", 1_000_000_000)
    r = execute(pf, Decision("x", "TST", "2026-01-16", Action.BUY), pb, _params())
    # No T+1 available in cache → skipped_holiday status
    assert r.status == "skipped_holiday"
    assert r.fill_date is None

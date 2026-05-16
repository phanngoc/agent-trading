"""Pure-math tests for the metrics module.

Each test compares against a hand-computed expected value or a textbook
identity so a regression in the math is immediately visible.
"""

import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.benchmark.metrics import (
    alpha_beta,
    annualized_return,
    annualized_volatility,
    avg_r_multiple,
    daily_returns,
    hit_rate,
    max_drawdown,
    paired_t_test,
    profit_factor,
    sharpe_ratio,
    total_return_pct,
)


def test_total_return_simple():
    curve = pd.Series([100, 105, 110])
    assert total_return_pct(curve) == pytest.approx(0.10)


def test_total_return_empty_handles_gracefully():
    assert total_return_pct(pd.Series([], dtype=float)) == 0.0
    assert total_return_pct(pd.Series([100])) == 0.0


def test_annualized_return_one_year():
    # 252 days, ending at 1.10x — annualized should be 10%
    curve = pd.Series([100 + i * (10 / 252) for i in range(253)])
    assert annualized_return(curve) == pytest.approx(0.10, rel=0.02)


def test_max_drawdown_known_curve():
    curve = pd.Series([100, 105, 110, 95, 88, 102])
    # Peak 110, trough 88 → -20%
    assert max_drawdown(curve) == pytest.approx(-0.20)


def test_max_drawdown_monotonic_up_is_zero():
    curve = pd.Series([100, 101, 102, 103])
    assert max_drawdown(curve) == pytest.approx(0.0)


def test_hit_rate():
    assert hit_rate([10, -5, 3, -2, 8]) == pytest.approx(0.60)
    assert hit_rate([]) == 0.0


def test_profit_factor():
    # Wins: 10+3+8 = 21. Losses: 5+2 = 7. PF = 3.0
    assert profit_factor([10, -5, 3, -2, 8]) == pytest.approx(3.0)


def test_profit_factor_no_losses_returns_inf():
    assert math.isinf(profit_factor([10, 20]))
    assert profit_factor([-10, -20]) == 0.0   # only losses → no wins / losses = 0


def test_sharpe_known_series():
    """Use a *deterministic* series so the formula is hand-checkable.

    Five days with returns [0.02, -0.01, 0.03, 0.0, 0.01]: mean=0.01,
    sd(ddof=1)=0.01581. Daily rf for 4% annual ≈ 0.0001587. Sharpe
    annualized ≈ (0.01 - 0.0001587)/0.01581 × sqrt(252) ≈ 9.87. We give
    the range some slack to absorb floating-point.
    """
    r = pd.Series([0.02, -0.01, 0.03, 0.0, 0.01])
    sharpe = sharpe_ratio(r, risk_free_annual=0.04)
    assert sharpe == pytest.approx(9.87, abs=0.05)


def test_alpha_beta_recovers_known_relation():
    rng = np.random.default_rng(7)
    x = pd.Series(rng.normal(0.0005, 0.012, 200))
    y = 0.0008 + 0.9 * x + pd.Series(rng.normal(0, 0.001, 200))
    ab = alpha_beta(y, x)
    assert ab.beta == pytest.approx(0.9, abs=0.02)
    assert ab.alpha_daily == pytest.approx(0.0008, abs=0.0002)
    assert 0.90 < ab.r_squared < 1.0


def test_paired_t_test_significant_outperformance():
    rng = np.random.default_rng(11)
    # Strategy out-performs by 0.1% daily, low noise → very significant
    bench = pd.Series(rng.normal(0.0005, 0.01, 100))
    strat = bench + pd.Series(rng.normal(0.001, 0.002, 100))
    tt = paired_t_test(strat, bench)
    assert tt.p_value < 0.01
    assert tt.t_stat > 2.5
    assert tt.n_observations == 100


def test_paired_t_test_returns_neutral_on_tiny_sample():
    tt = paired_t_test(pd.Series([0.01, 0.02]), pd.Series([0.005, 0.01]))
    assert tt.p_value == 1.0
    assert tt.t_stat == 0.0


def test_daily_returns_first_is_nan():
    curve = pd.Series([100, 110, 99])
    r = daily_returns(curve)
    assert pd.isna(r.iloc[0])
    assert r.iloc[1] == pytest.approx(0.10)
    assert r.iloc[2] == pytest.approx(-0.10)

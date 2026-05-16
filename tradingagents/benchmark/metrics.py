"""Performance metrics — pure functions over equity curves.

The scorecard answers two questions:

1. **Did this strategy make money?** (returns, Sharpe, max drawdown)
2. **Did it beat the benchmark?** (alpha, beta, paired t-test on daily
   returns vs the benchmark's daily returns)

Every function here takes plain pandas Series / numpy arrays so the
module has zero coupling to Portfolio / Decision / config. That makes
unit tests trivial — feed in literal series and assert against known
results from textbooks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# 252 trading days approximates the VN exchange calendar (~248-252
# trading days per year). Used to annualize Sharpe and returns.
TRADING_DAYS_PER_YEAR = 252


# ── Equity-curve → return series ─────────────────────────────────────────


def daily_returns(equity_curve: pd.Series) -> pd.Series:
    """Convert an NAV / level series into a simple daily return series.

    First entry is NaN (no prior day), the rest are
    ``(today / yesterday) - 1``. Aligned to the same index as input.
    """
    return equity_curve.astype(float).pct_change()


# ── Headline numbers ────────────────────────────────────────────────────


def total_return_pct(equity_curve: pd.Series) -> float:
    """Cumulative return from first to last NAV, as a decimal (0.052 = +5.2%)."""
    series = equity_curve.dropna()
    if len(series) < 2:
        return 0.0
    return float(series.iloc[-1] / series.iloc[0] - 1.0)


def annualized_return(equity_curve: pd.Series) -> float:
    """Geometric annualization of the total return over the observed window."""
    series = equity_curve.dropna()
    n = len(series)
    if n < 2:
        return 0.0
    total = series.iloc[-1] / series.iloc[0]
    years = (n - 1) / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return 0.0
    return float(total ** (1.0 / years) - 1.0)


def annualized_volatility(returns: pd.Series) -> float:
    """sqrt(252) × stdev of daily returns; degenerates to 0 if <2 points."""
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    return float(r.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))


def sharpe_ratio(returns: pd.Series, risk_free_annual: float = 0.04) -> float:
    """Annualized Sharpe ratio. ``risk_free_annual`` is the per-year
    risk-free rate (e.g. 0.04 = 4% on 5y VN gov bond).
    """
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    rf_daily = risk_free_annual / TRADING_DAYS_PER_YEAR
    excess = r - rf_daily
    sd = excess.std(ddof=1)
    if sd == 0:
        return 0.0
    return float((excess.mean() / sd) * math.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Worst peak-to-trough decline expressed as a negative decimal.

    Returns 0.0 if the curve never draws down (e.g. monotonic up) or
    has fewer than two points.
    """
    series = equity_curve.dropna()
    if len(series) < 2:
        return 0.0
    running_peak = series.cummax()
    drawdowns = (series / running_peak) - 1.0
    return float(drawdowns.min())


# ── Trade-quality metrics ───────────────────────────────────────────────


def hit_rate(realized_pnls: list[float]) -> float:
    """Fraction of trades with positive P&L. 0 trades → 0."""
    if not realized_pnls:
        return 0.0
    wins = sum(1 for p in realized_pnls if p > 0)
    return wins / len(realized_pnls)


def avg_r_multiple(realized_returns: list[float]) -> float:
    """Mean realized return per trade (already a multiple — e.g. 0.07 = +7%)."""
    if not realized_returns:
        return 0.0
    return float(np.mean(realized_returns))


def profit_factor(realized_pnls: list[float]) -> float:
    """Sum of winning P&L divided by absolute sum of losing P&L.

    Returns ``float('inf')`` if there are no losing trades and at least
    one winning trade — caller should clamp for display.
    """
    wins = sum(p for p in realized_pnls if p > 0)
    losses = -sum(p for p in realized_pnls if p < 0)
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


# ── Benchmark comparison ────────────────────────────────────────────────


@dataclass(frozen=True)
class AlphaResult:
    """OLS regression result of strategy returns on benchmark returns.

    ``alpha`` is the daily intercept; ``alpha_annualized`` scales by
    252 trading days. ``beta`` is the slope (sensitivity to benchmark).
    Standard errors are conditional on the OLS assumptions but useful
    for sanity checking — a strategy with alpha=0.001 ± 0.002 is noise.
    """

    alpha_daily: float
    alpha_annualized: float
    beta: float
    r_squared: float
    n_observations: int


def alpha_beta(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> AlphaResult:
    """Single-factor CAPM regression: r_strat = α + β r_bench + ε.

    Aligns the two series by index, drops NaNs, fits via numpy lstsq.
    Returns zeros if there isn't enough overlap.
    """
    df = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(df) < 5:
        return AlphaResult(0.0, 0.0, 0.0, 0.0, len(df))
    y = df.iloc[:, 0].to_numpy()
    x = df.iloc[:, 1].to_numpy()
    # Design matrix [1, x] for intercept + slope.
    X = np.column_stack([np.ones_like(x), x])
    coeffs, residuals, _, _ = np.linalg.lstsq(X, y, rcond=None)
    alpha_daily, beta = float(coeffs[0]), float(coeffs[1])
    y_pred = X @ coeffs
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return AlphaResult(
        alpha_daily=alpha_daily,
        alpha_annualized=alpha_daily * TRADING_DAYS_PER_YEAR,
        beta=beta,
        r_squared=r2,
        n_observations=len(df),
    )


@dataclass(frozen=True)
class TTestResult:
    """Paired t-test on (strategy − benchmark) daily returns.

    Null hypothesis: the mean daily out-performance is zero. A small
    ``p_value`` (< 0.05) means we can reject the null with reasonable
    confidence — the strategy *probably* has real alpha rather than
    noise. Sample-size warning: with <30 observations the t-distribution
    assumption gets shaky; treat the p_value as indicative only.
    """

    mean_diff_daily: float
    t_stat: float
    p_value: float
    n_observations: int


def paired_t_test(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> TTestResult:
    """Compute paired Welch-style t-stat for daily out-performance.

    Implementation note: uses the one-sample t-statistic on the
    difference series, which is the standard paired-test form. We
    return the two-sided p-value via the survival function of the
    t-distribution.
    """
    df = pd.concat([strategy_returns, benchmark_returns], axis=1, join="inner").dropna()
    if len(df) < 5:
        return TTestResult(0.0, 0.0, 1.0, len(df))
    diff = (df.iloc[:, 0] - df.iloc[:, 1]).to_numpy()
    n = len(diff)
    mean = float(diff.mean())
    sd = float(diff.std(ddof=1))
    if sd == 0:
        return TTestResult(mean, 0.0, 1.0, n)
    t_stat = mean / (sd / math.sqrt(n))

    # Two-sided p-value via scipy if available, manual fallback otherwise.
    try:
        from scipy import stats  # type: ignore

        p_value = float(2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1)))
    except ImportError:
        # Crude normal approximation — fine for n >= 30.
        p_value = float(2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0)))))

    return TTestResult(mean_diff_daily=mean, t_stat=float(t_stat), p_value=p_value, n_observations=n)


# ── Roll-up ─────────────────────────────────────────────────────────────


@dataclass
class Scorecard:
    """Bundled metrics for one strategy across one evaluation window."""

    strategy_id: str
    n_days: int
    total_return_pct: float
    annualized_return_pct: float
    annualized_vol_pct: float
    sharpe: float
    max_drawdown_pct: float
    n_trades: int
    hit_rate: float
    avg_return_per_trade: float
    profit_factor: float
    alpha_annualized_pct: Optional[float]
    beta: Optional[float]
    r_squared: Optional[float]
    t_stat: Optional[float]
    p_value: Optional[float]

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "n_days": self.n_days,
            "total_return_pct": round(self.total_return_pct * 100, 3),
            "annualized_return_pct": round(self.annualized_return_pct * 100, 3),
            "annualized_vol_pct": round(self.annualized_vol_pct * 100, 3),
            "sharpe": round(self.sharpe, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 3),
            "n_trades": self.n_trades,
            "hit_rate": round(self.hit_rate, 3),
            "avg_return_per_trade_pct": round(self.avg_return_per_trade * 100, 3),
            "profit_factor": round(self.profit_factor, 3) if math.isfinite(self.profit_factor) else "inf",
            "alpha_annualized_pct": round(self.alpha_annualized_pct * 100, 3) if self.alpha_annualized_pct is not None else None,
            "beta": round(self.beta, 3) if self.beta is not None else None,
            "r_squared": round(self.r_squared, 3) if self.r_squared is not None else None,
            "t_stat": round(self.t_stat, 3) if self.t_stat is not None else None,
            "p_value": round(self.p_value, 4) if self.p_value is not None else None,
        }


def compute_scorecard(
    strategy_id: str,
    equity_curve: pd.Series,
    realized_pnls: list[float],
    realized_returns: list[float],
    risk_free_annual: float = 0.04,
    benchmark_returns: Optional[pd.Series] = None,
) -> Scorecard:
    """Roll up every metric into a single Scorecard.

    ``equity_curve`` is the strategy's NAV indexed by ISO date.
    ``realized_pnls`` / ``realized_returns`` are per-closed-trade.
    ``benchmark_returns`` is optional; when provided we compute α, β,
    and the paired t-test.
    """
    r = daily_returns(equity_curve)
    alpha = beta = r2 = t = p = None
    if benchmark_returns is not None and len(benchmark_returns.dropna()) >= 5:
        ab = alpha_beta(r, benchmark_returns)
        tt = paired_t_test(r, benchmark_returns)
        alpha, beta, r2 = ab.alpha_annualized, ab.beta, ab.r_squared
        t, p = tt.t_stat, tt.p_value

    return Scorecard(
        strategy_id=strategy_id,
        n_days=int(equity_curve.dropna().shape[0]),
        total_return_pct=total_return_pct(equity_curve),
        annualized_return_pct=annualized_return(equity_curve),
        annualized_vol_pct=annualized_volatility(r),
        sharpe=sharpe_ratio(r, risk_free_annual),
        max_drawdown_pct=max_drawdown(equity_curve),
        n_trades=len(realized_pnls),
        hit_rate=hit_rate(realized_pnls),
        avg_return_per_trade=avg_r_multiple(realized_returns),
        profit_factor=profit_factor(realized_pnls),
        alpha_annualized_pct=alpha,
        beta=beta,
        r_squared=r2,
        t_stat=t,
        p_value=p,
    )

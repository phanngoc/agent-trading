"""Backtest runner — replay every strategy over the cached window.

For each strategy in ``benchmarks/config.yaml``:

1. Build a Decision stream (either by parsing ``eval_results/`` for
   TradingAgents, or by running the baseline function for everyone else).
2. Replay those decisions through a fresh Portfolio using the same
   execution engine and config.
3. Mark-to-market daily to produce an equity curve.
4. Compute a Scorecard against the benchmark.

Outputs:

* ``benchmarks/daily/<run_date>/scorecard.json`` — machine-readable summary.
* ``benchmarks/daily/<run_date>/report.md`` — human-readable summary.
* ``benchmarks/daily/<run_date>/equity_curves.csv`` — one column per strategy.
* ``benchmarks/daily/<run_date>/decisions/<strategy>.json`` — full decision logs.

Usage::

    venv/bin/python -m scripts.benchmark.run_backtest
    venv/bin/python -m scripts.benchmark.run_backtest --start 2026-03-01 --end 2026-05-15
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tradingagents.benchmark.baselines import (
    StrategySpec,
    build_baseline_decisions,
    parse_strategy_specs,
)
from tradingagents.benchmark.eval_results_reader import load_decisions
from tradingagents.benchmark.execution import ExecutionParams, execute
from tradingagents.benchmark.metrics import compute_scorecard, daily_returns
from tradingagents.benchmark.models import Decision, Portfolio
from tradingagents.benchmark.prices import PriceBook

logger = logging.getLogger("run_backtest")


# ── Config loader ───────────────────────────────────────────────────────


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Per-strategy replay ─────────────────────────────────────────────────


def _decisions_for_strategy(
    spec: StrategySpec,
    watchlist: List[str],
    prices: PriceBook,
    start_date: str,
    end_date: str,
    eval_results_dir: str,
) -> List[Decision]:
    """Source the decision stream for one strategy.

    Dispatches by ``spec.kind``: ``replay_from_eval_results`` parses the
    JSON logs TradingAgents already wrote; everything else falls through
    to :mod:`baselines`.
    """
    if spec.kind == "replay_from_eval_results":
        all_decisions = load_decisions(
            eval_results_dir=eval_results_dir,
            strategy_id=spec.id,
            tickers=watchlist,
        )
        return [d for d in all_decisions if start_date <= d.decision_date <= end_date]

    baseline_decisions = build_baseline_decisions(spec, watchlist, prices, start_date, end_date)
    if baseline_decisions is None:
        logger.warning("Unknown strategy kind '%s' for %s — skipping", spec.kind, spec.id)
        return []
    return baseline_decisions


def _build_equity_curve(
    portfolio: Portfolio,
    decisions: List[Decision],
    prices: PriceBook,
    params: ExecutionParams,
    trading_days: List[str],
) -> Tuple[pd.Series, List[dict]]:
    """Walk one strategy through the trading window and emit a daily NAV series.

    Decisions are bucketed by decision_date so we can apply them in
    chronological order while still snapshotting NAV at the end of each
    trading day for the equity curve.
    """
    decisions_by_date: Dict[str, List[Decision]] = defaultdict(list)
    for d in decisions:
        decisions_by_date[d.decision_date].append(d)

    nav_series: Dict[str, float] = {}
    execution_log: List[dict] = []

    # Pre-warm: any decision with date < first trading day is invalid lookahead;
    # we just ignore those and start clean.
    for day in trading_days:
        # Mark-to-market BEFORE applying today's decisions, so the NAV
        # reflects yesterday's close plus today's settlement releases.
        prices_today = {
            t: prices.latest_close_on_or_before(t, day) or 0.0
            for t in list(portfolio.positions.keys())
        }
        nav_series[day] = portfolio.nav(prices_today, day)

        # Execute decisions that were made on this day (fills on T+1 per execution).
        for decision in decisions_by_date.get(day, []):
            result = execute(portfolio, decision, prices, params)
            execution_log.append({
                "decision_date": decision.decision_date,
                "ticker": decision.ticker,
                "action": decision.action.value,
                "fill_date": result.fill_date,
                "status": result.status,
                "quantity": result.quantity,
                "fill_price": result.fill_price,
                "realized_pnl_vnd": result.realized_pnl_vnd,
                "note": result.note,
            })

    return pd.Series(nav_series).sort_index(), execution_log


# ── Reporting ───────────────────────────────────────────────────────────


def _format_pct(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{decimals}f}%"


def _render_markdown_report(
    run_date: str,
    start_date: str,
    end_date: str,
    watchlist: List[str],
    scorecards: List[dict],
    benchmark_id: str,
) -> str:
    rows = []
    rows.append(f"# Benchmark Report — {run_date}")
    rows.append("")
    rows.append(f"**Window**: {start_date} → {end_date}  ")
    rows.append(f"**Universe**: {', '.join(watchlist)} ({len(watchlist)} tickers)  ")
    rows.append(f"**Benchmark**: {benchmark_id}  ")
    rows.append("")
    rows.append("## Strategy comparison")
    rows.append("")
    headers = [
        "Strategy", "Total %", "Annualized %", "Sharpe", "Max DD %",
        "Trades", "Hit", "Avg/Trade %", "α (annual) %", "β", "t-stat", "p-value",
    ]
    rows.append("| " + " | ".join(headers) + " |")
    rows.append("|" + "|".join(["---"] * len(headers)) + "|")
    for sc in scorecards:
        rows.append(
            "| "
            + " | ".join(
                str(x)
                for x in [
                    sc["strategy_id"],
                    _format_pct(sc["total_return_pct"]),
                    _format_pct(sc["annualized_return_pct"]),
                    f"{sc['sharpe']:.2f}",
                    _format_pct(sc["max_drawdown_pct"]),
                    sc["n_trades"],
                    f"{sc['hit_rate']:.2f}",
                    _format_pct(sc["avg_return_per_trade_pct"]),
                    _format_pct(sc["alpha_annualized_pct"]),
                    sc["beta"] if sc["beta"] is not None else "—",
                    sc["t_stat"] if sc["t_stat"] is not None else "—",
                    sc["p_value"] if sc["p_value"] is not None else "—",
                ]
            )
            + " |"
        )
    rows.append("")
    rows.append("## Interpretation guide")
    rows.append("")
    rows.append(
        "- **α (annual)** > 0 means the strategy out-performed the benchmark on a risk-adjusted basis."
    )
    rows.append(
        "- **p-value** < 0.05 supports the claim that alpha is statistically real, not noise. "
        "Needs ≥30 daily observations for the t-distribution assumption to be robust."
    )
    rows.append(
        "- **Sharpe** above 1.0 is good, above 2.0 is rare. Both are annualized at "
        "252 trading days, risk-free 4%."
    )
    rows.append(
        "- **Hit rate** alone is misleading without **avg/trade** — a strategy can win 80% of "
        "trades but still lose money if losing trades are large."
    )
    return "\n".join(rows)


# ── Main entry ──────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="benchmarks/config.yaml")
    parser.add_argument("--cache-dir", default="benchmarks/state/prices")
    parser.add_argument("--eval-results-dir", default="eval_results")
    parser.add_argument("--out-dir", default="benchmarks/daily")
    parser.add_argument("--start", default=None, help="Window start (ISO date); defaults to lookback_days before today")
    parser.add_argument("--end", default=None, help="Window end (ISO date); defaults to today")
    parser.add_argument(
        "--run-date",
        default=None,
        help="Label this run with a specific date (subdir under --out-dir); defaults to today",
    )
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    watchlist: List[str] = list(cfg.get("watchlist", []))
    benchmark_id: str = cfg.get("benchmark_ticker", "VNINDEX")
    initial_capital = float(cfg.get("initial_capital_vnd", 1_000_000_000))
    risk_free = float(cfg.get("risk_free_rate_annual", 0.04))

    end_date = args.end or date.today().isoformat()
    if args.start:
        start_date = args.start
    else:
        lookback = int(cfg.get("backtest_lookback_days", 180))
        start_date = (datetime.strptime(end_date, "%Y-%m-%d").date() - timedelta(days=lookback)).isoformat()

    params = ExecutionParams.from_config(cfg)
    prices = PriceBook.load(args.cache_dir, watchlist + [benchmark_id])
    trading_days = prices.trading_days(start_date, end_date)
    if not trading_days:
        logger.error("No trading days in window %s → %s; run seed_history first.", start_date, end_date)
        return 1

    # Benchmark equity curve = the index level itself, scaled to 1B notional
    # so it's directly comparable with the strategy NAV series. We use the
    # benchmark's daily returns for alpha/beta computation.
    bench_df = prices.frames.get(benchmark_id.upper())
    if bench_df is None or bench_df.empty:
        logger.error("Benchmark %s missing from price cache", benchmark_id)
        return 1
    bench_window = bench_df[(bench_df["Date"] >= start_date) & (bench_df["Date"] <= end_date)].copy()
    bench_level = bench_window.set_index("Date")["Close"].astype(float)
    bench_equity = bench_level / bench_level.iloc[0] * initial_capital
    bench_returns = daily_returns(bench_equity)

    run_date = args.run_date or date.today().isoformat()
    run_dir = os.path.join(args.out_dir, run_date)
    os.makedirs(os.path.join(run_dir, "decisions"), exist_ok=True)

    strategies = parse_strategy_specs(cfg)
    scorecards_payload: List[dict] = []
    equity_curves: Dict[str, pd.Series] = {benchmark_id + " (B&H)": bench_equity}

    for spec in strategies:
        print(f"\n=== {spec.id} ({spec.kind}) ===")
        decisions = _decisions_for_strategy(spec, watchlist, prices, start_date, end_date, args.eval_results_dir)
        print(f"  {len(decisions)} decisions in window")

        portfolio = Portfolio.empty(spec.id, initial_capital)
        equity_curve, execution_log = _build_equity_curve(
            portfolio, decisions, prices, params, trading_days
        )

        realized_pnls = [t.realized_pnl_vnd for t in portfolio.closed_trades]
        realized_returns = [t.realized_return_pct for t in portfolio.closed_trades]

        scorecard = compute_scorecard(
            strategy_id=spec.id,
            equity_curve=equity_curve,
            realized_pnls=realized_pnls,
            realized_returns=realized_returns,
            risk_free_annual=risk_free,
            benchmark_returns=bench_returns,
        )
        scorecards_payload.append(scorecard.to_dict())
        equity_curves[spec.id] = equity_curve

        print(
            f"  final NAV: {equity_curve.iloc[-1]:,.0f}  "
            f"({(equity_curve.iloc[-1]/initial_capital - 1)*100:+.2f}%)"
        )
        print(
            f"  trades closed: {len(portfolio.closed_trades)}  "
            f"hit_rate: {scorecard.hit_rate:.2f}  Sharpe: {scorecard.sharpe:.2f}"
        )

        # Persist per-strategy artifacts.
        with open(os.path.join(run_dir, "decisions", f"{spec.id}.json"), "w") as f:
            json.dump(
                {
                    "strategy_id": spec.id,
                    "kind": spec.kind,
                    "decisions": [d.to_dict() for d in decisions],
                    "execution_log": execution_log,
                    "final_portfolio": portfolio.to_dict(),
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    # Write the cross-strategy roll-up.
    with open(os.path.join(run_dir, "scorecard.json"), "w") as f:
        json.dump(
            {
                "run_date": run_date,
                "window": {"start": start_date, "end": end_date, "n_trading_days": len(trading_days)},
                "benchmark": benchmark_id,
                "initial_capital_vnd": initial_capital,
                "strategies": scorecards_payload,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    eq_df = pd.DataFrame(equity_curves).round(2)
    eq_df.to_csv(os.path.join(run_dir, "equity_curves.csv"))

    report = _render_markdown_report(run_date, start_date, end_date, watchlist, scorecards_payload, benchmark_id)
    with open(os.path.join(run_dir, "report.md"), "w") as f:
        f.write(report)

    print(f"\n→ Wrote {run_dir}/{{report.md, scorecard.json, equity_curves.csv, decisions/*.json}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

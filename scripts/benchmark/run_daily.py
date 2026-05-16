"""Daily orchestrator — TradingAgents runs + backtest refresh + daily brief.

Run by local cron once per trading day (typically 17:00 ICT after HOSE
close). Steps:

1. Trading-day gate — exit early on weekends / VN holidays.
2. Acquire PID lock so cron + manual triggers don't double up.
3. For each watchlist ticker missing today's ``full_states_log_*.json``,
   spawn ``main.py`` to produce a fresh agent run. Sequential to keep
   under vnstock and Anthropic rate limits.
4. Backfill today's prices into the cache (best-effort; not fatal).
5. Re-run :mod:`scripts.benchmark.run_backtest` so the scorecard reflects
   the new decisions.
6. Compose ``daily_brief.md`` for the human reader: user-portfolio
   signals, watchlist recommendations, scorecard delta, P&L line.
7. Release lock.

Usage::

    venv/bin/python -m scripts.benchmark.run_daily
    venv/bin/python -m scripts.benchmark.run_daily --date 2026-05-15 --force
    venv/bin/python -m scripts.benchmark.run_daily --skip-agent      # test loop sans LLM
    venv/bin/python -m scripts.benchmark.run_daily --dry-run         # plan only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from tradingagents.benchmark.calendar import is_trading_day, latest_trading_day
from tradingagents.benchmark.eval_results_reader import load_decisions
from tradingagents.benchmark.lockfile import LockBusy, acquire
from tradingagents.benchmark.models import Action, Decision
from tradingagents.benchmark.prices import PriceBook
from tradingagents.benchmark.user_portfolio import UserPortfolio, cross_reference
from tradingagents.dataflows.vnstock_api import is_vn_ticker

logger = logging.getLogger("run_daily")

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LOCK_PATH = os.path.join(_REPO_ROOT, "benchmarks", "state", "run_daily.lock")
_DEFAULT_CONFIG = os.path.join(_REPO_ROOT, "benchmarks", "config.yaml")
_AGENT_TIMEOUT_SEC = 15 * 60   # 15 min hard cap per ticker
_INTER_TICKER_SLEEP_SEC = 5    # space requests out to be polite to vnstock


# ── Helpers ─────────────────────────────────────────────────────────────


def _load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _agent_log_already_exists(ticker: str, run_date: str) -> bool:
    path = os.path.join(
        _REPO_ROOT,
        "eval_results",
        ticker.upper(),
        "TradingAgentsStrategy_logs",
        f"full_states_log_{run_date}.json",
    )
    return os.path.exists(path)


def _python_executable() -> str:
    """Pick the venv python so the subprocess sees the same deps."""
    venv_py = os.path.join(_REPO_ROOT, "venv", "bin", "python")
    if os.path.exists(venv_py):
        return venv_py
    return sys.executable


def _spawn_agent_run(ticker: str, run_date: str, log_path: str, analysts: str) -> Tuple[int, str]:
    """Run ``main.py`` for one (ticker, date) and tee output to ``log_path``.

    Returns ``(exit_code, summary)`` where summary is a one-liner suitable
    for the daily-brief table. Subprocess inherits the parent env so
    Anthropic OAuth and vnstock state carry through.
    """
    py = _python_executable()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Same region-language wiring as the dashboard trigger route.
    if is_vn_ticker(ticker):
        env["TRADINGAGENTS_OUTPUT_LANGUAGE"] = "Vietnamese"
    else:
        env["TRADINGAGENTS_OUTPUT_LANGUAGE"] = "English"

    cmd = [
        py, "-u", "main.py",
        "--ticker", ticker,
        "--date", run_date,
        "--provider", "anthropic",
        "--deep-model", "claude-haiku-4-5",
        "--quick-model", "claude-haiku-4-5",
        "--analysts", analysts,
    ]

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    started = time.time()
    with open(log_path, "ab") as logf:
        logf.write(f"[run_daily] command: {' '.join(cmd)}\n".encode())
        proc = subprocess.Popen(
            cmd, cwd=_REPO_ROOT, env=env, stdout=logf, stderr=subprocess.STDOUT
        )
        try:
            exit_code = proc.wait(timeout=_AGENT_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return 124, f"timeout after {_AGENT_TIMEOUT_SEC}s"
    elapsed = time.time() - started
    return exit_code, f"exit={exit_code} ({elapsed:.0f}s)"


def _refresh_price_cache(watchlist: List[str], benchmark_ticker: str) -> None:
    """Pull today's prices in front of the backtest re-run.

    Failures here are non-fatal — the backtest will just use yesterday's
    NAV as today's mark-to-market, which is correct on weekends/holidays
    and a small lag otherwise.
    """
    cmd = [
        _python_executable(),
        "-m", "scripts.benchmark.seed_history",
        "--days", "7",   # short window, cheap top-up
    ]
    logger.info("Refreshing price cache: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        logger.warning("seed_history exit=%s\n%s", proc.returncode, proc.stdout[-1500:])


def _run_backtest(out_dir_root: str, run_date: str) -> Optional[dict]:
    """Re-run the backtest and return the parsed scorecard.

    Pins ``--run-date`` so the output subdir matches the orchestrator's
    ``run_date`` even when wall-clock today differs (e.g. backfilling a
    skipped session). Without this, the scorecard would land in
    ``benchmarks/daily/<today>/`` while the brief goes to
    ``benchmarks/daily/<run_date>/``.
    """
    cmd = [
        _python_executable(),
        "-m", "scripts.benchmark.run_backtest",
        "--out-dir", out_dir_root,
        "--end", run_date,
        "--run-date", run_date,
    ]
    logger.info("Running backtest: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        logger.warning("backtest failed exit=%s\n%s", proc.returncode, proc.stdout[-2000:])
        return None
    scorecard_path = os.path.join(out_dir_root, run_date, "scorecard.json")
    if not os.path.exists(scorecard_path):
        return None
    with open(scorecard_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _today_prices(watchlist: List[str], cache_dir: str, run_date: str) -> Dict[str, Optional[float]]:
    pb = PriceBook.load(cache_dir, watchlist)
    out: Dict[str, Optional[float]] = {}
    for tkr in watchlist:
        out[tkr.upper()] = pb.latest_close_on_or_before(tkr, run_date)
    return out


# ── Daily-brief renderer ────────────────────────────────────────────────


def _fmt_vnd(v: float) -> str:
    return f"{v:,.0f} VND"


def _truncate(text: Optional[str], limit: int) -> str:
    if not text:
        return ""
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "…"


def _render_brief(
    run_date: str,
    watchlist: List[str],
    user_portfolio: UserPortfolio,
    decisions_today: List[Decision],
    prices_today: Dict[str, Optional[float]],
    agent_status: Dict[str, str],
    scorecard: Optional[dict],
) -> str:
    rows: List[str] = []
    rows.append(f"# Daily Brief — {run_date}")
    rows.append("")
    if not decisions_today:
        rows.append("> ⚠ Không có decision nào của TradingAgents cho ngày này. Kiểm tra agent log.")
        rows.append("")

    # ── Section 1: User's actual positions ─────────────────────────
    if user_portfolio.positions:
        rows.append("## 🎯 Danh mục của bạn")
        rows.append("")
        actions = cross_reference(user_portfolio, decisions_today, prices_today, run_date)
        # Order: sell signals first (act), then hold, then stale
        order = {"act": 0, "noop": 1, "ok": 2, "stale": 3}
        actions = sorted(actions, key=lambda a: order.get(a.urgency, 99))

        rows.append("| Ticker | Số CP | Giá vào | Giá hiện tại | P&L | Tín hiệu hôm nay | Lý do (rút gọn) |")
        rows.append("|---|---:|---:|---:|---:|:---:|---|")
        for a in actions:
            p = a.position
            now = a.today_close_vnd
            if now is not None:
                pnl_pct = p.unrealized_return_pct(now) * 100
                pnl_str = f"{pnl_pct:+.2f}%"
                price_str = _fmt_vnd(now)
            else:
                pnl_str = "—"
                price_str = "—"
            signal = a.action.value if a.action else "—"
            badge = {"SELL": "🔴 SELL", "BUY": "🟢 BUY", "HOLD": "🟡 HOLD"}.get(signal, signal)
            rationale = _truncate(a.decision.rationale if a.decision else None, 120)
            rows.append(
                f"| {p.ticker} | {p.quantity:,} | {_fmt_vnd(p.entry_price)} | {price_str} "
                f"| {pnl_str} | {badge} | {rationale} |"
            )
        rows.append("")

        sell_signals = [a for a in actions if a.action == Action.SELL]
        if sell_signals:
            rows.append("⚠️ **Cần chú ý**: " + ", ".join(a.position.ticker for a in sell_signals) + " có signal SELL.")
            rows.append("")
    else:
        rows.append("## 🎯 Danh mục của bạn")
        rows.append("")
        rows.append("> Chưa có dữ liệu. Tạo `benchmarks/state/user_portfolio.json` để hiển thị "
                    "P&L + signal cho positions thật.")
        rows.append("")

    # ── Section 2: Watchlist signals (entry opportunities) ──────────
    held = set(user_portfolio.tickers)
    watch_decisions = [d for d in decisions_today if d.ticker not in held]
    if watch_decisions:
        rows.append("## 📡 Watchlist — cơ hội mới")
        rows.append("")
        rows.append("| Ticker | Action | Giá đóng | Lý do (rút gọn) | Agent log |")
        rows.append("|---|:---:|---:|---|:---|")
        action_priority = {Action.BUY: 0, Action.SELL: 1, Action.HOLD: 2}
        watch_decisions.sort(key=lambda d: action_priority.get(d.action, 9))
        for d in watch_decisions:
            badge = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}.get(d.action.value, d.action.value)
            price = prices_today.get(d.ticker)
            price_str = _fmt_vnd(price) if price else "—"
            status_str = agent_status.get(d.ticker, "ok")
            rows.append(
                f"| {d.ticker} | {badge} | {price_str} "
                f"| {_truncate(d.rationale, 140)} | {status_str} |"
            )
        rows.append("")

    # ── Section 3: Strategy scorecard ──────────────────────────────
    if scorecard and scorecard.get("strategies"):
        rows.append("## 📊 Bảng điểm chiến lược")
        rows.append("")
        rows.append(
            f"Window: {scorecard['window']['start']} → {scorecard['window']['end']} "
            f"({scorecard['window']['n_trading_days']} phiên giao dịch)"
        )
        rows.append("")
        rows.append("| Strategy | Total % | Sharpe | Trades | α annual % | p-value |")
        rows.append("|---|---:|---:|---:|---:|---:|")
        for s in scorecard["strategies"]:
            rows.append(
                f"| {s['strategy_id']} | {s['total_return_pct']:+.2f}% | {s['sharpe']:.2f} "
                f"| {s['n_trades']} "
                f"| {(s['alpha_annualized_pct'] or 0):+.2f}% "
                f"| {s.get('p_value', '—')} |"
            )
        rows.append("")
        rows.append("Diễn giải: p-value < 0.05 ⇒ alpha có ý nghĩa thống kê. "
                    "Cần ≥30 phiên để kết luận tin cậy.")
        rows.append("")

    # ── Section 4: Agent run status (debugging aid) ─────────────────
    rows.append("## 🔧 Trạng thái agent run hôm nay")
    rows.append("")
    rows.append("| Ticker | Trạng thái |")
    rows.append("|---|:---|")
    for tkr in watchlist:
        rows.append(f"| {tkr} | {agent_status.get(tkr.upper(), 'skipped (already had log)')} |")
    rows.append("")

    return "\n".join(rows)


# ── Main ────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=_DEFAULT_CONFIG)
    parser.add_argument("--date", default=None, help="ISO date to run for (default: latest trading day)")
    parser.add_argument("--analysts", default="market,news,fundamentals", help="Analyst set passed to main.py")
    parser.add_argument("--force", action="store_true", help="Run even on a non-trading day")
    parser.add_argument("--skip-agent", action="store_true", help="Skip TradingAgents subprocess — use existing logs")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip the backtest re-run")
    parser.add_argument("--dry-run", action="store_true", help="Plan only — don't spawn agents or write files")
    args = parser.parse_args(argv)

    cfg = _load_config(args.config)
    watchlist: List[str] = list(cfg.get("watchlist", []))
    benchmark_ticker: str = cfg.get("benchmark_ticker", "VNINDEX")

    run_date = args.date or latest_trading_day() or date.today().isoformat()
    if not args.force and not is_trading_day(run_date):
        logger.info("Skipping: %s is not a HOSE trading day (use --force to override).", run_date)
        return 0

    out_dir_root = os.path.join(_REPO_ROOT, "benchmarks", "daily")
    day_dir = os.path.join(out_dir_root, run_date)
    agent_log_dir = os.path.join(day_dir, "_agent_logs")
    os.makedirs(agent_log_dir, exist_ok=True)

    logger.info("Run date: %s", run_date)
    logger.info("Watchlist: %s", ", ".join(watchlist))

    if args.dry_run:
        missing = [t for t in watchlist if not _agent_log_already_exists(t, run_date)]
        logger.info("Would spawn agent for %d tickers: %s", len(missing), ", ".join(missing))
        return 0

    try:
        with acquire(_LOCK_PATH):
            # ── Step 1: spawn agent runs ────────────────────────────
            agent_status: Dict[str, str] = {}
            if args.skip_agent:
                logger.info("--skip-agent: not spawning any TradingAgents runs")
                for t in watchlist:
                    if _agent_log_already_exists(t, run_date):
                        agent_status[t.upper()] = "reused existing log"
                    else:
                        agent_status[t.upper()] = "missing (skipped)"
            else:
                for idx, tkr in enumerate(watchlist):
                    if _agent_log_already_exists(tkr, run_date):
                        agent_status[tkr.upper()] = "reused existing log"
                        continue
                    if idx > 0:
                        time.sleep(_INTER_TICKER_SLEEP_SEC)
                    log_path = os.path.join(agent_log_dir, f"{tkr.upper()}.log")
                    logger.info("Spawning agent for %s → %s", tkr, log_path)
                    code, summary = _spawn_agent_run(tkr, run_date, log_path, args.analysts)
                    agent_status[tkr.upper()] = ("ok " if code == 0 else "FAILED ") + summary

            # ── Step 2: refresh prices ──────────────────────────────
            _refresh_price_cache(watchlist, benchmark_ticker)

            # ── Step 3: backtest ────────────────────────────────────
            scorecard = None if args.skip_backtest else _run_backtest(out_dir_root, run_date)

            # ── Step 4: compose brief ──────────────────────────────
            cache_dir = os.path.join(_REPO_ROOT, "benchmarks", "state", "prices")
            prices_today = _today_prices(watchlist, cache_dir, run_date)
            decisions_today = [
                d for d in load_decisions(strategy_id="tradingagents", tickers=watchlist)
                if d.decision_date == run_date
            ]
            user_portfolio = UserPortfolio.load()
            brief = _render_brief(
                run_date=run_date,
                watchlist=watchlist,
                user_portfolio=user_portfolio,
                decisions_today=decisions_today,
                prices_today=prices_today,
                agent_status=agent_status,
                scorecard=scorecard,
            )
            brief_path = os.path.join(day_dir, "daily_brief.md")
            with open(brief_path, "w", encoding="utf-8") as f:
                f.write(brief)

            logger.info("Wrote %s (%d chars)", brief_path, len(brief))
            print(f"\n→ Daily brief ready: {brief_path}")
            return 0

    except LockBusy as exc:
        logger.error("Lock held by another run: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())

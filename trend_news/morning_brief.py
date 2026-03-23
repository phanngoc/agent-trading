"""
TrendRadar Morning Brief Runner

Chạy mỗi ngày lúc 6:00 AM để:
  1. Fetch fresh data (main.py pipeline)
  2. Generate morning brief (IntelligenceAgent)
  3. Send to Telegram
  4. Save report to DB

Usage:
    # Standalone
    python trend_news/morning_brief.py

    # With options
    python trend_news/morning_brief.py --watchlist VCB HPG VIC GAS VNM --skip-fetch

    # Cron (6:00 AM daily)
    0 6 * * * cd /path/to/TradingAgents && \
        GROQ_API_KEY=... TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... \
        python trend_news/morning_brief.py >> logs/morning_brief.log 2>&1

Environment variables:
    GROQ_API_KEY          — required for LLM synthesis
    TELEGRAM_BOT_TOKEN    — optional, for delivery
    TELEGRAM_CHAT_ID      — optional, for delivery
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent.absolute()
sys.path.insert(0, str(_HERE))

_DB_PATH = str(_HERE / "output" / "trend_news.db")
_PYTHON  = sys.executable
_LOG_DIR = _HERE / "logs"


def _run_fetch() -> bool:
    """Run main.py to fetch fresh data."""
    print("\n[MorningBrief] Step 1: Fetching fresh data...")
    result = subprocess.run(
        [_PYTHON, str(_HERE / "main.py")],
        cwd=str(_HERE),
        env={**os.environ},
    )
    if result.returncode != 0:
        print(f"[MorningBrief] ⚠ Fetch step exited with code {result.returncode} (non-fatal)")
        return False
    print("[MorningBrief] ✓ Fetch complete")
    return True


def _generate_report(watchlist: list[str]) -> dict:
    """Generate morning brief via IntelligenceAgent."""
    print("\n[MorningBrief] Step 2: Generating report...")
    from src.core.intelligence_agent import IntelligenceAgent

    agent = IntelligenceAgent(
        db_path=_DB_PATH,
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
    )
    report = agent.run_morning_brief(watchlist=watchlist or None)
    report_id = agent.save_report(report)
    print(f"[MorningBrief] ✓ Report saved (id={report_id})")
    return report, agent


def _send_telegram(report, agent) -> bool:
    """Send report to Telegram if configured."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id   = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not bot_token or not chat_id:
        print("[MorningBrief] ⚠ TELEGRAM_BOT_TOKEN/CHAT_ID not set — skipping delivery")
        return False

    print(f"\n[MorningBrief] Step 3: Sending to Telegram (chat={chat_id})...")
    ok = agent.send_telegram(report, bot_token=bot_token, chat_id=chat_id)
    if ok:
        print("[MorningBrief] ✓ Telegram delivered")
    else:
        print("[MorningBrief] ✗ Telegram delivery failed")
    return ok


def _print_summary(report) -> None:
    """Print a brief summary to stdout/logs."""
    print("\n" + "="*60)
    print(f"[MorningBrief] REPORT SUMMARY — {report.report_date}")
    print("="*60)
    print(f"  Market outlook : {report.market_outlook} (score={report.market_score:+.3f})")
    print(f"  Global risk    : {report.global_risk} ({report.critical_events} critical)")
    if report.synthesis:
        print(f"  AI synthesis   : {report.synthesis[:150]}")
    if report.top_picks:
        print(f"  Top picks      : {', '.join(t.ticker for t in report.top_picks[:5])}")
    if report.risk_alerts:
        print(f"  Risk alerts    : {', '.join(t.ticker for t in report.risk_alerts[:3])}")
    print("="*60)


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendRadar Morning Brief")
    parser.add_argument(
        "--watchlist", nargs="+", metavar="TICKER",
        help="Tickers to analyze (default: VN30 core)"
    )
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="Skip data fetch step (use existing DB data)"
    )
    parser.add_argument(
        "--no-telegram", action="store_true",
        help="Skip Telegram delivery"
    )
    args = parser.parse_args()

    start = time.time()
    print(f"[MorningBrief] Starting — {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Ensure log dir exists
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch (optional)
    if not args.skip_fetch:
        _run_fetch()
    else:
        print("[MorningBrief] Step 1: Skipped (--skip-fetch)")

    # Step 2: Generate
    report, agent = _generate_report(args.watchlist)
    _print_summary(report)

    # Step 3: Telegram
    if not args.no_telegram:
        _send_telegram(report, agent)

    elapsed = time.time() - start
    print(f"\n[MorningBrief] Done in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

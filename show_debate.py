#!/usr/bin/env python3
"""
show_debate.py — Human-readable debate log viewer for TradingAgents.

Usage:
    python show_debate.py HPG 2026-03-06
    python show_debate.py HPG 2026-03-06 --section all
    python show_debate.py HPG 2026-03-06 --section investment
    python show_debate.py HPG 2026-03-06 --section risk
    python show_debate.py HPG 2026-03-06 --section reports
    python show_debate.py HPG 2026-03-06 --section final
    python show_debate.py HPG 2026-03-06 --export debate_HPG.md
"""

import json
import argparse
import textwrap
from pathlib import Path


DIVIDER = "=" * 80
SECTION  = "-" * 60


def wrap(text: str, indent: int = 2, width: int = 100) -> str:
    prefix = " " * indent
    lines = text.strip().split("\n")
    result = []
    for line in lines:
        if len(line) <= width:
            result.append(prefix + line)
        else:
            wrapped = textwrap.wrap(line, width=width - indent)
            result.extend(prefix + l for l in wrapped)
    return "\n".join(result)


def print_section(title: str, content: str, color: str = ""):
    COLORS = {
        "bull":   "\033[92m",   # green
        "bear":   "\033[91m",   # red
        "judge":  "\033[93m",   # yellow
        "risk":   "\033[95m",   # magenta
        "report": "\033[96m",   # cyan
        "final":  "\033[1;93m", # bold yellow
        "":       "",
    }
    RESET = "\033[0m"
    c = COLORS.get(color, "")
    print(f"\n{c}{DIVIDER}")
    print(f"  {title}")
    print(f"{DIVIDER}{RESET}")
    print(wrap(content))


def split_speakers(history: str) -> list[dict]:
    """Split combined debate history into per-turn entries."""
    turns = []
    current_speaker = None
    current_lines = []

    for line in history.strip().split("\n"):
        # Detect speaker changes
        if line.startswith("Bull Analyst:"):
            if current_speaker:
                turns.append({"speaker": current_speaker, "text": "\n".join(current_lines).strip()})
            current_speaker = "Bull Analyst"
            current_lines = [line[len("Bull Analyst:"):].strip()]
        elif line.startswith("Bear Analyst:"):
            if current_speaker:
                turns.append({"speaker": current_speaker, "text": "\n".join(current_lines).strip()})
            current_speaker = "Bear Analyst"
            current_lines = [line[len("Bear Analyst:"):].strip()]
        else:
            current_lines.append(line)

    if current_speaker and current_lines:
        turns.append({"speaker": current_speaker, "text": "\n".join(current_lines).strip()})

    return turns


def split_risk_speakers(history: str) -> list[dict]:
    """Split risk debate history by risk analysts."""
    turns = []
    current_speaker = None
    current_lines = []

    SPEAKERS = ["Aggressive Analyst:", "Conservative Analyst:", "Neutral Analyst:"]

    for line in history.strip().split("\n"):
        matched = None
        for sp in SPEAKERS:
            if line.startswith(sp):
                matched = sp.rstrip(":")
                break

        if matched:
            if current_speaker:
                turns.append({"speaker": current_speaker, "text": "\n".join(current_lines).strip()})
            current_speaker = matched
            current_lines = [line[len(matched) + 1:].strip()]
        else:
            current_lines.append(line)

    if current_speaker and current_lines:
        turns.append({"speaker": current_speaker, "text": "\n".join(current_lines).strip()})

    return turns


def show_reports(state: dict):
    print_section("📊 MARKET REPORT", state.get("market_report", ""), "report")
    print_section("📰 NEWS REPORT", state.get("news_report", ""), "report")
    print_section("💬 SENTIMENT REPORT", state.get("sentiment_report", ""), "report")
    print_section("📈 FUNDAMENTALS REPORT", state.get("fundamentals_report", ""), "report")


def show_investment_debate(state: dict):
    inv = state["investment_debate_state"]
    turns = split_speakers(inv["history"])

    print(f"\n\033[1m{'=' * 80}\033[0m")
    print(f"  💬 INVESTMENT DEBATE  ({len(turns)} turns)")
    print(f"{'=' * 80}\033[0m")

    SPEAKER_COLOR = {
        "Bull Analyst": "\033[92m",  # green
        "Bear Analyst": "\033[91m",  # red
    }
    RESET = "\033[0m"

    for i, turn in enumerate(turns, 1):
        sp = turn["speaker"]
        color = SPEAKER_COLOR.get(sp, "")
        emoji = "🐂" if "Bull" in sp else "🐻"
        print(f"\n{color}{SECTION}")
        print(f"  {emoji} Turn {i}: {sp}")
        print(f"{SECTION}{RESET}")
        print(wrap(turn["text"]))

    print_section("⚖️  RESEARCH MANAGER DECISION", inv["judge_decision"], "judge")


def show_risk_debate(state: dict):
    risk = state["risk_debate_state"]
    turns = split_risk_speakers(risk["history"])

    print(f"\n\033[1m{'=' * 80}\033[0m")
    print(f"  ⚠️  RISK DEBATE  ({len(turns)} turns)")
    print(f"{'=' * 80}\033[0m")

    SPEAKER_COLOR = {
        "Aggressive Analyst":   "\033[91m",   # red
        "Conservative Analyst": "\033[94m",   # blue
        "Neutral Analyst":      "\033[93m",   # yellow
    }
    RESET = "\033[0m"

    for i, turn in enumerate(turns, 1):
        sp = turn["speaker"]
        color = SPEAKER_COLOR.get(sp, "")
        emoji = {"Aggressive Analyst": "🔴", "Conservative Analyst": "🔵", "Neutral Analyst": "🟡"}.get(sp, "⚪")
        print(f"\n{color}{SECTION}")
        print(f"  {emoji} Turn {i}: {sp}")
        print(f"{SECTION}{RESET}")
        print(wrap(turn["text"]))

    print_section("🏛️  RISK JUDGE DECISION", risk["judge_decision"], "risk")


def show_final(state: dict):
    print_section("📋 TRADER INVESTMENT PLAN", state.get("trader_investment_decision", ""), "judge")
    print_section("🎯 FINAL TRADE DECISION", state.get("final_trade_decision", ""), "final")

    # Extract the BUY/SELL/HOLD signal
    final = state.get("final_trade_decision", "")
    for line in final.split("\n"):
        if "FINAL TRANSACTION PROPOSAL" in line or line.strip() in ("BUY", "SELL", "HOLD"):
            print(f"\n\033[1;93m{'=' * 80}")
            print(f"  SIGNAL: {line.strip()}")
            print(f"{'=' * 80}\033[0m\n")
            break


def export_markdown(state: dict, output_path: str):
    """Export full debate to markdown file."""
    lines = []
    ticker = state.get("company_of_interest", "")
    date   = state.get("trade_date", "")
    lines.append(f"# TradingAgents Debate Log — {ticker} ({date})\n")

    def add_section(title, content):
        lines.append(f"\n## {title}\n")
        lines.append(content.strip())
        lines.append("")

    add_section("Market Report", state.get("market_report", ""))
    add_section("News Report", state.get("news_report", ""))
    add_section("Sentiment Report", state.get("sentiment_report", ""))
    add_section("Fundamentals Report", state.get("fundamentals_report", ""))

    # Investment debate
    lines.append("\n## Investment Debate\n")
    inv = state["investment_debate_state"]
    turns = split_speakers(inv["history"])
    for i, turn in enumerate(turns, 1):
        sp = turn["speaker"]
        emoji = "🐂" if "Bull" in sp else "🐻"
        lines.append(f"\n### {emoji} Turn {i}: {sp}\n")
        lines.append(turn["text"])
        lines.append("")

    add_section("Research Manager Decision", inv["judge_decision"])
    add_section("Trader Investment Plan", state.get("trader_investment_decision", ""))

    # Risk debate
    lines.append("\n## Risk Debate\n")
    risk = state["risk_debate_state"]
    turns = split_risk_speakers(risk["history"])
    for i, turn in enumerate(turns, 1):
        sp = turn["speaker"]
        emoji = {"Aggressive Analyst": "🔴", "Conservative Analyst": "🔵", "Neutral Analyst": "🟡"}.get(sp, "⚪")
        lines.append(f"\n### {emoji} Turn {i}: {sp}\n")
        lines.append(turn["text"])
        lines.append("")

    add_section("Risk Judge Decision", risk["judge_decision"])
    add_section("Final Trade Decision", state.get("final_trade_decision", ""))

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ Exported to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Show TradingAgents debate log")
    parser.add_argument("ticker", help="Ticker symbol, e.g. HPG")
    parser.add_argument("date",   help="Trade date, e.g. 2026-03-06")
    parser.add_argument("--section", default="all",
                        choices=["all", "reports", "investment", "risk", "final"],
                        help="Which section to show")
    parser.add_argument("--export", default=None, metavar="FILE.md",
                        help="Export full debate to markdown file")
    args = parser.parse_args()

    log_path = Path(f"eval_results/{args.ticker}/TradingAgentsStrategy_logs/full_states_log_{args.date}.json")
    if not log_path.exists():
        print(f"❌ Log not found: {log_path}")
        return

    with open(log_path) as f:
        data = json.load(f)

    if args.date not in data:
        print(f"❌ Date {args.date} not in log. Available: {list(data.keys())}")
        return

    state = data[args.date]

    print(f"\n\033[1m{'=' * 80}\033[0m")
    print(f"  🤖 TradingAgents Debate — {state['company_of_interest']} @ {state['trade_date']}")
    print(f"\033[1m{'=' * 80}\033[0m")

    if args.export:
        export_markdown(state, args.export)
        return

    if args.section in ("all", "reports"):
        show_reports(state)
    if args.section in ("all", "investment"):
        show_investment_debate(state)
    if args.section in ("all", "risk"):
        show_risk_debate(state)
    if args.section in ("all", "final"):
        show_final(state)


if __name__ == "__main__":
    main()

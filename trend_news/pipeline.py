"""
Production Sentiment Pipeline

Orchestrates all three batches in sequence:

  Batch 1 (fetch):  main.py — crawl news from all sources, save to DB
  Batch 2 (llm):    batch_llm_eval.py — LLM evaluates high-uncertainty articles,
                    syncs results into sentiment_feedback to improve keyword_suggestions
  Batch 3 (score):  batch_sentiment.py — lexicon-score all unscored rows using the
                    auto-learned lexicon, persists sentiment_score/sentiment_label to DB

Run via cron/supercronic or manually:
    python trend_news/pipeline.py

Skip flags:
    --skip-fetch    Skip Batch 1 (run only on existing DB data)
    --skip-llm      Skip Batch 2 (e.g. no LLM API key configured)
    --skip-score    Skip Batch 3

Other options:
    --mode STR          Report mode passed to main.py (default: daily)
    --db-path STR       Path to SQLite DB (default: output/trend_news.db)
    --days-back INT     Days back for LLM evaluation (default: 7)
    --llm-provider STR  openai|anthropic (default: openai)
    --llm-model STR     Override LLM model name
    --dry-run           Pass --dry-run to Batches 2 and 3 (no DB writes)
"""
import argparse
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB = os.path.join(_HERE, "output", "trend_news.db")
_PYTHON = sys.executable


def _run(cmd: list, step_name: str) -> int:
    """Run a subprocess, stream its output, and return the exit code."""
    print(f"\n{'=' * 60}")
    print(f"[Pipeline] {step_name}")
    print(f"{'=' * 60}")
    result = subprocess.run(cmd, cwd=_HERE)
    if result.returncode != 0:
        print(f"[Pipeline] {step_name} FAILED (exit code {result.returncode})")
    else:
        print(f"[Pipeline] {step_name} OK")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="TrendRadar Sentiment Pipeline")
    parser.add_argument("--skip-fetch",   action="store_true",
                        help="Skip Batch 1 news fetch")
    parser.add_argument("--skip-llm",     action="store_true",
                        help="Skip Batch 2 LLM evaluation")
    parser.add_argument("--skip-score",   action="store_true",
                        help="Skip Batch 3 lexicon scoring")
    parser.add_argument("--mode",         type=str, default="daily",
                        choices=["daily", "incremental", "current"],
                        help="Report mode for Batch 1 (default: daily)")
    parser.add_argument("--db-path",      type=str, default=_DEFAULT_DB)
    parser.add_argument("--days-back",    type=int, default=7,
                        help="Days back for LLM evaluation (default: 7)")
    parser.add_argument("--llm-provider", type=str, default="openai",
                        choices=["openai", "anthropic"])
    parser.add_argument("--llm-model",    type=str, default=None)
    parser.add_argument("--dry-run",      action="store_true",
                        help="Pass --dry-run to Batches 2 and 3")
    args = parser.parse_args()

    print("[Pipeline] TrendRadar Sentiment Pipeline starting...")
    print(f"  Fetch:    {'skip' if args.skip_fetch else 'enabled'}")
    print(f"  LLM:      {'skip' if args.skip_llm else f'enabled ({args.llm_provider})'}")
    print(f"  Score:    {'skip' if args.skip_score else 'enabled'}")
    print(f"  Dry run:  {args.dry_run}")

    # ------------------------------------------------------------------
    # Batch 1: Crawl and save news
    # ------------------------------------------------------------------
    if not args.skip_fetch:
        rc = _run(
            [_PYTHON, os.path.join(_HERE, "main.py")],
            "Batch 1: News Fetch",
        )
        if rc != 0:
            print("[Pipeline] Aborting: Batch 1 failed.")
            return rc
    else:
        print("\n[Pipeline] Skipping Batch 1 (--skip-fetch)")

    # ------------------------------------------------------------------
    # Batch 2: LLM evaluation (non-fatal — may not have API key)
    # ------------------------------------------------------------------
    if not args.skip_llm:
        cmd = [
            _PYTHON, os.path.join(_HERE, "batch_llm_eval.py"),
            "--days-back", str(args.days_back),
            "--provider",  args.llm_provider,
            "--db-path",   args.db_path,
        ]
        if args.llm_model:
            cmd += ["--model", args.llm_model]
        if args.dry_run:
            cmd.append("--dry-run")
        rc = _run(cmd, "Batch 2: LLM Evaluation")
        if rc != 0:
            print("[Pipeline] Warning: Batch 2 failed. Continuing to Batch 3.")
    else:
        print("\n[Pipeline] Skipping Batch 2 (--skip-llm)")

    # ------------------------------------------------------------------
    # Batch 3: Lexicon scoring (fatal on failure)
    # ------------------------------------------------------------------
    if not args.skip_score:
        cmd = [
            _PYTHON, os.path.join(_HERE, "batch_sentiment.py"),
            "--db-path", args.db_path,
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        rc = _run(cmd, "Batch 3: Lexicon Sentiment Scoring")
        if rc != 0:
            print("[Pipeline] Batch 3 failed.")
            return rc
    else:
        print("\n[Pipeline] Skipping Batch 3 (--skip-score)")

    print(f"\n{'=' * 60}")
    print("[Pipeline] All batches complete.")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

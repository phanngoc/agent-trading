"""
Batch 2: Claude-backed sentiment evaluation.

Pulls high-uncertainty articles from DB, scores them via Claude
(hybrid sync/batch), persists into sentiment_llm_evaluations, and
optionally promotes high-confidence evaluations into sentiment_feedback
so Batch 3 (sentiment learning) can use them.

Credential discovery (in order):
  1. CLAUDE_CODE_OAUTH_TOKEN (long-lived OAuth from `claude setup-token`)
  2. ANTHROPIC_API_KEY

Usage:
    python trend_news/batch_llm_eval.py [options]

Options:
    --days-back INT         Days of articles to evaluate (default: 7)
    --min-uncertainty FLOAT Minimum uncertainty threshold (default: 0.35)
    --limit INT             Max articles per run (default: 100)
    --min-confidence FLOAT  Min Claude confidence for feedback sync (default: 0.6)
    --model STR             Override model (default: claude-haiku-4-5)
    --db-path STR           Path to SQLite DB (default: output/trend_news.db)
    --dry-run               Evaluate but do not sync to sentiment_feedback
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from src.core.claude_client import ClaudeAuthError, ClaudeClient
from src.core.claude_sentiment import ClaudeSentiment

_DEFAULT_DB = os.path.join(_HERE, "output", "trend_news.db")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch 2: Claude Sentiment Evaluation")
    parser.add_argument("--days-back",       type=int,   default=7)
    parser.add_argument("--min-uncertainty", type=float, default=0.35)
    parser.add_argument("--limit",           type=int,   default=100)
    parser.add_argument("--min-confidence",  type=float, default=0.6)
    parser.add_argument("--model",           type=str,   default=None)
    parser.add_argument("--db-path",         type=str,   default=_DEFAULT_DB)
    parser.add_argument("--dry-run",         action="store_true")
    args = parser.parse_args()

    print("[Batch 2] Claude Sentiment Evaluation starting...")
    print(f"  DB:              {args.db_path}")
    print(f"  Days back:       {args.days_back}")
    print(f"  Min uncertainty: {args.min_uncertainty}")
    print(f"  Limit:           {args.limit}")
    print(f"  Dry run:         {args.dry_run}")

    try:
        client = ClaudeClient(model=args.model) if args.model else ClaudeClient()
    except ClaudeAuthError as e:
        print(f"[Batch 2] ERROR: {e}")
        return 1

    print(f"  Auth:            {client.auth_kind}")
    print(f"  Model:           {client.model}")

    scorer = ClaudeSentiment(client=client, db_path=args.db_path)
    summary = scorer.evaluate_high_uncertainty_articles(
        days_back=args.days_back,
        min_uncertainty=args.min_uncertainty,
        limit=args.limit,
    )

    print(
        f"[Batch 2] Evaluated: {summary['evaluated']} | "
        f"Failed: {summary['failed']} | "
        f"Model: {summary['model_used']}"
    )

    if args.dry_run:
        print("[Batch 2] Dry-run mode: skipping feedback sync.")
        return 0

    synced = scorer.sync_llm_feedback_to_learning(min_confidence=args.min_confidence)
    print(f"[Batch 2] Synced {synced} high-confidence evaluations → sentiment_feedback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

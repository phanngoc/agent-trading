"""
Batch 2: LLM Sentiment Evaluation

Evaluates high-uncertainty articles using an LLM (OpenAI or Anthropic),
then syncs high-confidence results into sentiment_feedback to improve
keyword_suggestions and the auto-learned lexicon used by Batch 3.

Usage:
    python trend_news/batch_llm_eval.py [options]

Options:
    --days-back INT         Days of articles to evaluate (default: 7)
    --min-uncertainty FLOAT Minimum uncertainty threshold (default: 0.35)
    --limit INT             Max articles to evaluate per run (default: 100)
    --min-confidence FLOAT  Min LLM confidence for feedback sync (default: 0.6)
    --provider STR          LLM provider: openai|anthropic (default: openai)
    --model STR             Override model name
    --db-path STR           Path to SQLite DB (default: output/trend_news.db)
    --dry-run               Evaluate but do not sync to sentiment_feedback
"""
import argparse
import os
import sys

# Allow running from project root or from trend_news/
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from src.core.llm_sentiment_evaluator import LLMSentimentEvaluator

_DEFAULT_DB = os.path.join(_HERE, "output", "trend_news.db")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch 2: LLM Sentiment Evaluation")
    parser.add_argument("--days-back",       type=int,   default=7)
    parser.add_argument("--min-uncertainty", type=float, default=0.35)
    parser.add_argument("--limit",           type=int,   default=100)
    parser.add_argument("--min-confidence",  type=float, default=0.6)
    parser.add_argument("--provider",        type=str,   default="openai",
                        choices=["openai", "anthropic"])
    parser.add_argument("--model",           type=str,   default=None)
    parser.add_argument("--db-path",         type=str,   default=_DEFAULT_DB)
    parser.add_argument("--dry-run",         action="store_true")
    args = parser.parse_args()

    print("[Batch 2] LLM Sentiment Evaluation starting...")
    print(f"  DB:              {args.db_path}")
    print(f"  Provider:        {args.provider}")
    print(f"  Days back:       {args.days_back}")
    print(f"  Min uncertainty: {args.min_uncertainty}")
    print(f"  Limit:           {args.limit}")
    print(f"  Dry run:         {args.dry_run}")

    try:
        evaluator = LLMSentimentEvaluator(
            db_path=args.db_path,
            model_provider=args.provider,
            model_name=args.model,
            uncertainty_threshold=args.min_uncertainty,
        )
    except (ImportError, ValueError) as e:
        print(f"[Batch 2] Cannot initialize LLM evaluator: {e}")
        return 1

    result = evaluator.evaluate_high_uncertainty_articles(
        days_back=args.days_back,
        min_uncertainty=args.min_uncertainty,
        limit=args.limit,
    )

    print(
        f"[Batch 2] Evaluated: {result.evaluated} | "
        f"Cached: {result.skipped_cached} | "
        f"Failed: {result.failed} | "
        f"Model: {result.model_used}"
    )

    if args.dry_run:
        print("[Batch 2] Dry-run mode: skipping feedback sync.")
        return 0

    synced = evaluator.sync_llm_feedback_to_learning(
        min_confidence=args.min_confidence
    )
    print(f"[Batch 2] Synced {synced} high-confidence evaluations to sentiment_feedback.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Batch 3: Lexicon Sentiment Scorer

Refreshes the auto-learned lexicon cache (picking up any improvements
from Batch 2), then fetches all articles where sentiment_score IS NULL
and bulk-updates the DB with pre-computed scores.

Run this after batch_llm_eval.py so the latest keyword_suggestions
are included in the scoring.

Usage:
    python trend_news/batch_sentiment.py [options]

Options:
    --chunk-size INT   Articles per fetch+update cycle (default: 500)
    --db-path STR      Path to SQLite DB (default: output/trend_news.db)
    --dry-run          Score articles but do not write to DB
"""
import argparse
import os
import sys
from typing import List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from src.core.database import DatabaseManager
from src.utils.sentiment import get_sentiment, refresh_auto_learned_cache

_DEFAULT_DB = os.path.join(_HERE, "output", "trend_news.db")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch 3: Lexicon Sentiment Scorer")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--db-path",    type=str, default=_DEFAULT_DB)
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    print("[Batch 3] Lexicon Sentiment Scorer starting...")
    print(f"  DB:         {args.db_path}")
    print(f"  Chunk size: {args.chunk_size}")
    print(f"  Dry run:    {args.dry_run}")

    # Refresh auto-learned lexicon once before the loop so all chunks use
    # the latest keyword_suggestions (including anything synced by Batch 2).
    print("[Batch 3] Refreshing auto-learned lexicon cache...")
    refresh_auto_learned_cache()

    db = DatabaseManager(args.db_path)

    total_scored = 0
    total_failed = 0
    chunk_number = 0

    while True:
        chunk_number += 1
        unscored = db.get_unscored_news(limit=args.chunk_size)

        if not unscored:
            print(f"[Batch 3] No unscored articles found. Done after {chunk_number - 1} chunk(s).")
            break

        print(f"[Batch 3] Chunk {chunk_number}: scoring {len(unscored)} articles...")

        updates: List[Tuple[int, float, str]] = []
        for article in unscored:
            article_id = article["id"]
            title = article.get("title", "")
            try:
                score, label = get_sentiment(title)
                updates.append((article_id, score, label))
            except Exception as e:
                print(f"[Batch 3] Failed to score article id={article_id}: {e}")
                total_failed += 1

        if updates and not args.dry_run:
            db.batch_update_news_sentiment(updates)

        total_scored += len(updates)
        chunk_failed = len(unscored) - len(updates)
        if chunk_failed:
            print(f"[Batch 3] Chunk {chunk_number}: {len(updates)} scored, {chunk_failed} failed.")
        else:
            print(f"[Batch 3] Chunk {chunk_number}: {len(updates)} scored.")

        # If the DB returned fewer rows than the chunk size, there are no more unscored rows.
        if len(unscored) < args.chunk_size:
            break

    print(f"[Batch 3] Complete. Total scored: {total_scored}, total failed: {total_failed}.")
    if args.dry_run:
        print("[Batch 3] Dry-run mode: no DB writes were made.")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

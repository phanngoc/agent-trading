"""
Relabel all news_articles with the current sentiment engine.

Strategy:
- Re-score every article that has a title using the current engine
- Update both sentiment_score and sentiment_label in DB
- Skip articles where title is NULL or too short
- Run in batches to avoid memory issues
- Print progress + before/after distribution

Usage:
    python scripts/relabel_sentiment.py [--dry-run] [--vi-only] [--limit N]
"""
import sys, sqlite3, argparse, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.sentiment import get_sentiment

DB_PATH = Path(__file__).parent.parent / "output" / "trend_news.db"
BATCH_SIZE = 500


def relabel(dry_run: bool = False, vi_only: bool = False, limit: int = 0):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # Fetch all articles with title
    query = "SELECT id, title, sentiment_score, sentiment_label FROM news_articles WHERE title IS NOT NULL AND LENGTH(title) > 10"
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(query).fetchall()
    print(f"Total articles to process: {len(rows)}")

    if vi_only:
        from src.utils.sentiment import _is_vietnamese
        rows = [(id_, t, s, l) for id_, t, s, l in rows if _is_vietnamese(t)]
        print(f"VI-only filter: {len(rows)} articles")

    # Before distribution
    before = {}
    for _, _, _, label in rows:
        before[label] = before.get(label, 0) + 1
    print("\nBefore distribution:")
    for label in sorted(before, key=lambda x: x or ""): print(f"  {label or 'NULL':>20}: {before[label]:>5}")

    # Process in batches
    updates = []
    changed = 0
    t0 = time.time()

    for i, (id_, title, old_score, old_label) in enumerate(rows):
        try:
            new_score, new_label = get_sentiment(title)
        except Exception as e:
            print(f"  Error on id={id_}: {e}")
            continue

        if new_label != old_label or (old_score is None) or abs(new_score - float(old_score or 0)) > 0.01:
            updates.append((new_score, new_label, id_))
            changed += 1

        if (i + 1) % BATCH_SIZE == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(rows) - i - 1) / rate
            print(f"  {i+1}/{len(rows)} processed | {changed} changes | {rate:.0f}/s | ETA {eta:.0f}s")

            if not dry_run and updates:
                conn.executemany(
                    "UPDATE news_articles SET sentiment_score=?, sentiment_label=? WHERE id=?",
                    updates
                )
                conn.commit()
                updates = []

    # Final batch
    if not dry_run and updates:
        conn.executemany(
            "UPDATE news_articles SET sentiment_score=?, sentiment_label=? WHERE id=?",
            updates
        )
        conn.commit()

    print(f"\nTotal processed: {len(rows)} | Changed: {changed} ({changed/len(rows)*100:.1f}%)")
    print(f"Time: {time.time()-t0:.1f}s")

    # After distribution
    after_rows = conn.execute(
        "SELECT sentiment_label, COUNT(*) FROM news_articles WHERE title IS NOT NULL AND LENGTH(title)>10 GROUP BY sentiment_label"
    ).fetchall()
    print("\nAfter distribution (full DB):")
    for label, count in sorted(after_rows, key=lambda x: x[0] or ""): print(f"  {label or 'NULL':>20}: {count:>5}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--vi-only", action="store_true", help="Only relabel Vietnamese articles")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of articles")
    args = parser.parse_args()
    relabel(dry_run=args.dry_run, vi_only=args.vi_only, limit=args.limit)

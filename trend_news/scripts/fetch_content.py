"""
Batch fetch full article content for existing DB records.

Usage:
    python scripts/fetch_content.py [--limit 500] [--sources cafef,vnexpress] [--concurrency 5]

Updates news_articles.content for articles that have a URL but no content yet.
"""
import argparse
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from src.utils.content_fetcher import ContentFetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch fetch article content")
    parser.add_argument("--limit", type=int, default=500, help="Max articles to process")
    parser.add_argument("--sources", type=str, default="", help="Comma-separated source_ids (default: all)")
    parser.add_argument("--concurrency", type=int, default=5, help="Parallel requests")
    parser.add_argument("--db-path", type=str, default="output/trend_news.db")
    args = parser.parse_args()

    db = sqlite3.connect(args.db_path)
    c = db.cursor()

    # Ensure column exists
    cols = [r[1] for r in c.execute("PRAGMA table_info(news_articles)").fetchall()]
    if "content" not in cols:
        c.execute("ALTER TABLE news_articles ADD COLUMN content TEXT")
        db.commit()
        print("✅ Added content column")

    # Query articles without content
    where = "url IS NOT NULL AND url != '' AND (content IS NULL OR content = '') AND LENGTH(url) > 10"
    params: list = []
    if args.sources:
        source_list = [s.strip() for s in args.sources.split(",")]
        placeholders = ",".join("?" * len(source_list))
        where += f" AND source_id IN ({placeholders})"
        params.extend(source_list)

    rows = c.execute(
        f"SELECT id, url, source_id FROM news_articles WHERE {where} ORDER BY crawled_at DESC LIMIT ?",
        params + [args.limit],
    ).fetchall()

    total = len(rows)
    if total == 0:
        print("✅ No articles need content fetching")
        db.close()
        return

    print(f"Fetching content for {total} articles (concurrency={args.concurrency})...")
    t0 = time.time()

    fetcher = ContentFetcher()
    articles = [(r[0], r[1], r[2]) for r in rows]

    results = asyncio.run(fetcher.fetch_batch(articles, concurrency=args.concurrency))

    # Batch update DB
    updates = [(content, aid) for aid, content in results.items() if content]
    if updates:
        c.executemany("UPDATE news_articles SET content=? WHERE id=?", updates)
        db.commit()

    elapsed = time.time() - t0
    success = len(updates)
    failed = total - success
    speed = total / elapsed if elapsed > 0 else 0

    print(f"\n✅ Done in {elapsed:.1f}s ({speed:.0f} articles/sec)")
    print(f"   Fetched: {success}/{total} | Failed/empty: {failed}")

    # Sample output
    if updates:
        sample_id = updates[0][1]
        sample = c.execute("SELECT title, content FROM news_articles WHERE id=?", (sample_id,)).fetchone()
        if sample:
            print(f"\nSample:")
            print(f"  Title:   {sample[0][:70]}")
            print(f"  Content: {sample[1][:150]}...")

    db.close()


if __name__ == "__main__":
    main()

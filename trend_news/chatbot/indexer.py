"""
Cognee News Indexer
-------------------
Incrementally syncs news_articles from the existing SQLite DB into a Cognee
knowledge graph with Kuzu backend. Tracks progress via a `chatbot_sync` watermark table.

Usage:
    # First-time or full reset
    python -m trend_news.chatbot.indexer --full-reindex

    # Incremental (index only new articles since last run)
    python -m trend_news.chatbot.indexer

    # Background daemon (loops every INDEXER_RUN_INTERVAL seconds)
    python -m trend_news.chatbot.indexer --daemon

    # Quick smoke test (index 3 articles only)
    python -m chatbot.indexer --test --limit 3

    # Test with specific number of articles
    python -m chatbot.indexer --full-reindex --limit 3
"""

import asyncio
import sqlite3
import sys
import os
import time
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

# Ensure trend_news is importable
_TREND_NEWS_DIR = os.path.dirname(os.path.dirname(__file__))
if _TREND_NEWS_DIR not in sys.path:
    sys.path.insert(0, _TREND_NEWS_DIR)

from chatbot.config import (
    DB_PATH,
    COGNEE_DB_PATH,
    COGNEE_LLM_CONFIG,
    COGNEE_EMBEDDING_ENV,
    INDEXER_BATCH_SIZE,
    INDEXER_RUN_INTERVAL,
    NEWS_DAYS_LOOKBACK,
    setup_cognee_paths,
)


def _setup_cognee():
    """Configure Cognee: DB paths (before import), embedding env vars, LLM config."""
    # Set DB path env vars BEFORE cognee loads its pydantic-settings config
    setup_cognee_paths()
    # Set embedding env vars
    for key, value in COGNEE_EMBEDDING_ENV.items():
        os.environ.setdefault(key, value)

    import cognee

    # Set graph database provider to Kuzu (must use API method, not env var)
    cognee.config.set_graph_database_provider("kuzu")
    cognee.config.set_llm_config(COGNEE_LLM_CONFIG)
    
    print(f"[Indexer] Graph DB Provider: kuzu (via set_graph_database_provider)")
    print(f"[Indexer] Note: Cognee 0.5.x stores Kuzu graph in .pkl file (serialized)")


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_sync_table(db_path: str):
    """Create chatbot_sync watermark table if it does not exist."""
    conn = _get_connection(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chatbot_sync (
                id               INTEGER PRIMARY KEY,
                last_indexed_id  INTEGER DEFAULT 0,
                last_indexed_at  TIMESTAMP,
                total_indexed    INTEGER DEFAULT 0
            )
        """)
        conn.execute("INSERT OR IGNORE INTO chatbot_sync (id, last_indexed_id, total_indexed) VALUES (1, 0, 0)")
        conn.commit()
    finally:
        conn.close()


def _get_watermark(db_path: str) -> int:
    conn = _get_connection(db_path)
    try:
        row = conn.execute("SELECT last_indexed_id FROM chatbot_sync WHERE id=1").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _update_watermark(db_path: str, new_id: int, count: int):
    conn = _get_connection(db_path)
    try:
        conn.execute(
            "UPDATE chatbot_sync SET last_indexed_id=?, last_indexed_at=?, total_indexed=total_indexed+? WHERE id=1",
            (new_id, datetime.now().isoformat(), count),
        )
        conn.commit()
    finally:
        conn.close()


def _reset_watermark(db_path: str):
    conn = _get_connection(db_path)
    try:
        conn.execute("UPDATE chatbot_sync SET last_indexed_id=0, total_indexed=0, last_indexed_at=NULL WHERE id=1")
        conn.commit()
    finally:
        conn.close()


def _fetch_new_articles(db_path: str, since_id: int, limit: int, days_limit: int = 30) -> List[Dict]:
    """Fetch articles newer than since_id, limited to recent days."""
    cutoff_date = (datetime.now() - timedelta(days=days_limit)).strftime("%Y-%m-%d")
    conn = _get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, source_id, title, url, crawled_at,
                   sentiment_score, sentiment_label, crawl_date
            FROM news_articles
            WHERE id > ?
              AND crawl_date >= ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (since_id, cutoff_date, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _format_article(article: Dict) -> str:
    """
    Format an article as structured text for Cognee entity extraction.
    The structured format helps Cognee identify: stocks, companies, events.
    """
    sentiment_label = article.get("sentiment_label") or "Neutral"
    try:
        sentiment_score = float(article.get("sentiment_score") or 0.0)
    except (TypeError, ValueError):
        sentiment_score = 0.0

    return (
        f"TIN TỨC TÀI CHÍNH: [{article['source_id']}] {article['crawl_date']}\n"
        f"Tiêu đề: {article['title']}\n"
        f"Cảm xúc thị trường: {sentiment_label} ({sentiment_score:+.2f})\n"
        f"Nguồn: {article.get('url') or 'N/A'}\n"
    )


async def index_articles_sequential(
    articles: List[Dict], 
    add_timeout: int = 60,
    verbose: bool = True
) -> int:
    """
    Add articles to Cognee SEQUENTIALLY to avoid Kuzu lock issues.
    
    Kuzu doesn't support concurrent writes, so we add one article at a time
    and run cognify after each one.
    
    Returns: number of successfully indexed articles
    """
    import cognee

    if verbose:
        print(f"[Indexer] Adding {len(articles)} articles sequentially (Kuzu-safe mode)...")

    indexed_count = 0
    
    for i, article in enumerate(articles, 1):
        text = _format_article(article)
        if verbose:
            print(f"[Indexer] [{i}/{len(articles)}] Processing article ID {article['id']}: {article['title'][:50]}...")
        
        try:
            # Add single article
            await asyncio.wait_for(cognee.add(text), timeout=add_timeout)
            
            # Run cognify immediately after each add to build graph incrementally
            # This avoids concurrent access to Kuzu
            await asyncio.wait_for(cognee.cognify(), timeout=120)
            
            indexed_count += 1
            if verbose:
                print(f"[Indexer]   ✅ Article {article['id']} indexed successfully")
                
        except asyncio.TimeoutError:
            print(f"[Indexer]   ⚠️ Timeout after {add_timeout}s — skipping article {article['id']}")
            continue
        except Exception as exc:
            print(f"[Indexer]   ⚠️ Error (skipping article {article['id']}): {exc}")
            continue

    if verbose:
        print(f"[Indexer] ✅ Indexed {indexed_count}/{len(articles)} articles")
        
        # Verify Kuzu database location (Cognee 0.5.x stores in .pkl file)
        db_path = Path(COGNEE_DB_PATH) / "databases"
        if db_path.exists():
            try:
                pkl_files = list(db_path.rglob("*.pkl"))
                if pkl_files:
                    total_size = sum(f.stat().st_size for f in pkl_files)
                    print(f"[Indexer] 📁 Kuzu graph DB (.pkl): {len(pkl_files)} file(s), {total_size / 1024 / 1024:.1f} MB")
                    for f in pkl_files[:3]:
                        size_mb = f.stat().st_size / 1024 / 1024
                        print(f"[Indexer]    - {f.parent.name}/{f.name} ({size_mb:.1f} MB)")
                else:
                    print(f"[Indexer] ⚠️ No .pkl files found in {db_path}")
            except Exception as e:
                print(f"[Indexer] ⚠️ Could not list DB files: {e}")
    
    return indexed_count


async def run_incremental_sync(
    db_path: str = DB_PATH, 
    test_mode: bool = False,
    max_articles: Optional[int] = None
):
    """Main sync: fetch new articles → index → update watermark."""
    _ensure_sync_table(db_path)
    watermark = _get_watermark(db_path)
    
    if max_articles and max_articles > 0:
        print(f"[Indexer] 🧪 TEST MODE: Will index maximum {max_articles} articles")
    
    print(f"[Indexer] Starting incremental sync from article id > {watermark}")

    total = 0
    max_id = watermark
    batch_limit = 10 if test_mode else INDEXER_BATCH_SIZE
    if max_articles and max_articles < batch_limit:
        batch_limit = max_articles
    days = NEWS_DAYS_LOOKBACK

    while True:
        remaining = max_articles - total if max_articles else None
        if remaining is not None and remaining <= 0:
            print(f"[Indexer] Reached max_articles limit ({max_articles}). Stopping.")
            break
            
        current_limit = min(batch_limit, remaining) if remaining else batch_limit
        batch = _fetch_new_articles(db_path, since_id=max_id, limit=current_limit, days_limit=days)
        
        if not batch:
            print("[Indexer] No more articles to index.")
            break

        try:
            indexed = await index_articles_sequential(batch)
            if indexed > 0:
                max_id = max(a["id"] for a in batch)
                total += indexed
                _update_watermark(db_path, max_id, indexed)
                print(f"[Indexer] ✅ Batch complete: {indexed} articles. Total: {total}. Latest id: {max_id}")
            else:
                print(f"[Indexer] ❌ No articles indexed in this batch")
                break
        except Exception as exc:
            print(f"[Indexer] ❌ Batch failed at id {max_id}: {exc}")
            import traceback
            traceback.print_exc()
            break  # resume from watermark on next run

        if test_mode or (max_articles and total >= max_articles):
            print(f"[Indexer] Test mode completed. Indexed {total} articles.")
            break  # only one batch in test mode

    print(f"[Indexer] Done. Indexed {total} articles this run.")
    return total


async def run_full_reindex(db_path: str = DB_PATH, max_articles: Optional[int] = None):
    """Prune Cognee data, reset watermark, and re-index from scratch."""
    import cognee
    import shutil

    print("[Indexer] Full reindex: cleaning up old data...")
    
    # Clean up Kuzu directory manually to avoid lock issues
    kuzu_path = Path(COGNEE_DB_PATH) / "kuzu"
    if kuzu_path.exists():
        try:
            shutil.rmtree(kuzu_path)
            kuzu_path.mkdir(parents=True, exist_ok=True)
            print(f"[Indexer] ✅ Cleaned Kuzu directory: {kuzu_path}")
        except Exception as exc:
            print(f"[Indexer] ⚠️ Could not clean Kuzu directory: {exc}")
    
    # Try to prune cognee data
    try:
        await cognee.prune.prune_data()
        await cognee.prune.prune_system(metadata=True)
        print("[Indexer] ✅ Pruned cognee data")
    except Exception as exc:
        print(f"[Indexer] ⚠️ Prune warning (non-fatal): {exc}")

    _ensure_sync_table(db_path)
    _reset_watermark(db_path)
    print("[Indexer] Watermark reset. Starting full index...")
    
    if max_articles:
        print(f"[Indexer] 🧪 Limited to {max_articles} articles for testing")
    
    return await run_incremental_sync(db_path, max_articles=max_articles)


async def run_daemon(db_path: str = DB_PATH):
    """Loop forever, running incremental sync every INDEXER_RUN_INTERVAL seconds."""
    print(f"[Indexer] Daemon started. Interval: {INDEXER_RUN_INTERVAL}s")
    while True:
        try:
            await run_incremental_sync(db_path)
        except Exception as exc:
            print(f"[Indexer] Daemon error (will retry): {exc}")
        await asyncio.sleep(INDEXER_RUN_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="Cognee news indexer with Kuzu graph backend")
    parser.add_argument("--full-reindex", action="store_true", help="Prune and re-index all articles")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--test", action="store_true", help="Index in test mode (single batch)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of articles to index (for testing)")
    args = parser.parse_args()

    _setup_cognee()

    if args.full_reindex:
        total = asyncio.run(run_full_reindex(max_articles=args.limit))
        print(f"\n{'='*50}")
        print(f"[Indexer] Full reindex complete: {total} articles indexed")
        print(f"{'='*50}")
    elif args.daemon:
        asyncio.run(run_daemon())
    elif args.test:
        total = asyncio.run(run_incremental_sync(test_mode=True, max_articles=args.limit or 3))
        print(f"\n{'='*50}")
        print(f"[Indexer] Test complete: {total} articles indexed")
        print(f"{'='*50}")
    else:
        total = asyncio.run(run_incremental_sync(max_articles=args.limit))
        print(f"\n{'='*50}")
        print(f"[Indexer] Incremental sync complete: {total} articles indexed")
        print(f"{'='*50}")


if __name__ == "__main__":
    main()

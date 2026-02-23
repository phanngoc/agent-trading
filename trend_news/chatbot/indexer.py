"""
Cognee News Indexer
-------------------
Incrementally syncs news_articles from the existing SQLite DB into a Cognee
knowledge graph. Tracks progress via a `chatbot_sync` watermark table.

Usage:
    # First-time or full reset
    python -m trend_news.chatbot.indexer --full-reindex

    # Incremental (index only new articles since last run)
    python -m trend_news.chatbot.indexer

    # Background daemon (loops every INDEXER_RUN_INTERVAL seconds)
    python -m trend_news.chatbot.indexer --daemon

    # Quick smoke test (index 10 articles)
    python -m trend_news.chatbot.indexer --test
"""

import asyncio
import sqlite3
import sys
import os
import time
import argparse
from datetime import datetime, timedelta
from typing import List, Dict

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

    cognee.config.set_llm_config(COGNEE_LLM_CONFIG)


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


async def index_batch(articles: List[Dict], add_timeout: int = 30, cognify_timeout: int = 300) -> bool:
    """Add a batch of articles to Cognee and build the knowledge graph.

    Articles are added one-at-a-time to avoid internal SQLite lock contention:
    cognee.add([N texts]) spawns N concurrent pipeline tasks that all write to
    the same SQLite DB simultaneously, causing 'database is locked' errors.
    """
    import cognee

    for article in articles:
        text = _format_article(article)
        try:
            await asyncio.wait_for(cognee.add(text), timeout=add_timeout)
        except asyncio.TimeoutError:
            print(f"[Indexer] cognee.add() timed out after {add_timeout}s — skipping article")
            continue
        except Exception as exc:
            print(f"[Indexer] cognee.add() error (skipping): {exc}")
            continue

    try:
        await asyncio.wait_for(cognee.cognify(), timeout=cognify_timeout)
    except asyncio.TimeoutError:
        print(f"[Indexer] cognee.cognify() timed out after {cognify_timeout}s — partial index")
        return False
    except Exception as exc:
        print(f"[Indexer] cognee.cognify() error: {exc}")
        return False
    return True


async def run_incremental_sync(db_path: str = DB_PATH, test_mode: bool = False):
    """Main sync: fetch new articles → index → update watermark."""
    _ensure_sync_table(db_path)
    watermark = _get_watermark(db_path)
    print(f"[Indexer] Starting incremental sync from article id > {watermark}")

    total = 0
    max_id = watermark
    batch_limit = 10 if test_mode else INDEXER_BATCH_SIZE
    days = NEWS_DAYS_LOOKBACK

    while True:
        batch = _fetch_new_articles(db_path, since_id=max_id, limit=batch_limit, days_limit=days)
        if not batch:
            break

        try:
            await index_batch(batch)
            max_id = max(a["id"] for a in batch)
            total += len(batch)
            _update_watermark(db_path, max_id, len(batch))
            print(f"[Indexer] Indexed {len(batch)} articles. Latest id: {max_id}")
        except Exception as exc:
            print(f"[Indexer] Batch failed at id {max_id}: {exc}")
            break  # resume from watermark on next run

        if test_mode:
            break  # only one batch in test mode

    print(f"[Indexer] Done. Indexed {total} articles this run.")


async def run_full_reindex(db_path: str = DB_PATH):
    """Prune Cognee data, reset watermark, and re-index from scratch."""
    import cognee

    print("[Indexer] Full reindex: pruning cognee data...")
    try:
        await cognee.prune.prune_data()
        await cognee.prune.prune_system(metadata=True)
    except Exception as exc:
        print(f"[Indexer] Prune warning (non-fatal): {exc}")

    _ensure_sync_table(db_path)
    _reset_watermark(db_path)
    print("[Indexer] Watermark reset. Starting full index...")
    await run_incremental_sync(db_path)


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
    parser = argparse.ArgumentParser(description="Cognee news indexer")
    parser.add_argument("--full-reindex", action="store_true", help="Prune and re-index all articles")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--test", action="store_true", help="Index 10 articles and exit")
    args = parser.parse_args()

    _setup_cognee()

    if args.full_reindex:
        asyncio.run(run_full_reindex())
    elif args.daemon:
        asyncio.run(run_daemon())
    elif args.test:
        asyncio.run(run_incremental_sync(test_mode=True))
    else:
        asyncio.run(run_incremental_sync())


if __name__ == "__main__":
    main()

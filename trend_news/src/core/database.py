import sqlite3
import datetime
from typing import Dict, List, Optional, Tuple
import os


class DatabaseManager:
    """
    Manages SQLite database interactions for storing news data.
    """

    def __init__(self, db_path: str = "trend_news.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        """Get a database connection."""
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize database tables and run migrations if needed."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            self._ensure_schema(cursor)
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self, cursor):
        """
        Create or migrate the news_articles table.

        Migration strategy:
        - If table doesn't exist: create with full schema including UNIQUE constraint.
        - If table exists but is old (no crawl_date column): migrate data into new
          schema, deduplicating in the process.
        - If table exists with new schema: do nothing.
        Always ensures FTS5 index is present.
        """
        # Check if table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_articles'"
        )
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            self._create_fresh_table(cursor)
        else:
            # Check if new schema is already in place (crawl_date column)
            cursor.execute("PRAGMA table_info(news_articles)")
            columns = {row[1] for row in cursor.fetchall()}

            if "crawl_date" not in columns:
                # Old schema detected — migrate
                self._migrate_to_dedup_schema(cursor)
            else:
                # Already migrated, ensure indexes exist
                self._create_indexes(cursor)

        # Always ensure FTS5 index is present (idempotent)
        self._ensure_fts_index(cursor)

    def _create_fresh_table(self, cursor):
        """Create news_articles table with dedup schema from scratch."""
        cursor.execute("""
            CREATE TABLE news_articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                url         TEXT DEFAULT '',
                mobile_url  TEXT DEFAULT '',
                ranks       TEXT,
                crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                crawl_date  TEXT NOT NULL
            )
        """)
        self._create_indexes(cursor)

    def _create_indexes(self, cursor):
        """Create performance and dedup indexes."""
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_news
            ON news_articles(source_id, title, crawl_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_crawled_at
            ON news_articles(crawled_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_source
            ON news_articles(source_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_crawl_date
            ON news_articles(crawl_date)
        """)

    def _create_fts_index(self, cursor):
        """
        Create FTS5 virtual table as a content table on news_articles.title.

        Uses content=news_articles so title text is NOT duplicated on disk.
        Triggers keep the FTS index in sync automatically on INSERT/DELETE/UPDATE.
        Existing rows are bulk-inserted into the index on first creation.
        """
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
                title,
                content='news_articles',
                content_rowid='id',
                tokenize='unicode61 remove_diacritics 0'
            )
        """)

        # Populate FTS from all existing rows
        cursor.execute("""
            INSERT INTO news_fts(rowid, title)
            SELECT id, title FROM news_articles
        """)

        # AFTER INSERT: add new row to FTS
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS news_articles_ai
            AFTER INSERT ON news_articles BEGIN
                INSERT INTO news_fts(rowid, title) VALUES (new.id, new.title);
            END
        """)

        # AFTER DELETE: remove row from FTS
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS news_articles_ad
            AFTER DELETE ON news_articles BEGIN
                INSERT INTO news_fts(news_fts, rowid, title)
                VALUES ('delete', old.id, old.title);
            END
        """)

        # AFTER UPDATE: replace row in FTS
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS news_articles_au
            AFTER UPDATE ON news_articles BEGIN
                INSERT INTO news_fts(news_fts, rowid, title)
                VALUES ('delete', old.id, old.title);
                INSERT INTO news_fts(rowid, title) VALUES (new.id, new.title);
            END
        """)

    def _ensure_fts_index(self, cursor):
        """
        Ensure FTS5 index exists. Creates it if not present.
        Called during _ensure_schema so every startup is covered.
        """
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_fts'"
        )
        if cursor.fetchone() is None:
            self._create_fts_index(cursor)

    def rebuild_fts_index(self):
        """
        Rebuild FTS5 index from scratch (public utility).

        Call this if the index becomes inconsistent, e.g. after a bulk
        import that bypassed the triggers.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS news_fts")
            # Also drop triggers so they don't conflict on re-creation
            for trigger in ("news_articles_ai", "news_articles_ad", "news_articles_au"):
                cursor.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            self._create_fts_index(cursor)
            # Integrity check
            cursor.execute("INSERT INTO news_fts(news_fts) VALUES ('integrity-check')")
            conn.commit()
            cursor.execute("SELECT COUNT(*) FROM news_fts")
            count = cursor.fetchone()[0]
            print(f"✅ FTS5 index rebuilt: {count} documents indexed")
        except Exception as e:
            conn.rollback()
            print(f"❌ FTS5 rebuild failed: {e}")
            raise
        finally:
            conn.close()

    def _migrate_to_dedup_schema(self, cursor):
        """
        Migrate old schema (no crawl_date, no UNIQUE) to new schema.
        Deduplicates data by keeping the latest row per (source_id, title, date).
        """
        print("⚙ DB migration: adding dedup schema to news_articles...")

        # Create new table
        cursor.execute("""
            CREATE TABLE news_articles_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                url         TEXT DEFAULT '',
                mobile_url  TEXT DEFAULT '',
                ranks       TEXT,
                crawled_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                crawl_date  TEXT NOT NULL
            )
        """)

        # Create unique index on new table
        cursor.execute("""
            CREATE UNIQUE INDEX idx_unique_news_new
            ON news_articles_new(source_id, title, crawl_date)
        """)

        # Migrate data, deduplicating by keeping latest crawled_at per group
        cursor.execute("""
            INSERT OR IGNORE INTO news_articles_new
                (source_id, title, url, mobile_url, ranks, crawled_at, crawl_date)
            SELECT source_id, title, url, mobile_url, ranks, crawled_at,
                   DATE(crawled_at) AS crawl_date
            FROM news_articles
            ORDER BY crawled_at DESC
        """)

        cursor.execute("SELECT COUNT(*) FROM news_articles")
        old_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM news_articles_new")
        new_count = cursor.fetchone()[0]

        # Swap tables
        cursor.execute("DROP TABLE news_articles")
        cursor.execute("ALTER TABLE news_articles_new RENAME TO news_articles")

        # Re-create remaining indexes (UNIQUE index already exists, renamed)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_crawled_at
            ON news_articles(crawled_at)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_source
            ON news_articles(source_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_crawl_date
            ON news_articles(crawl_date)
        """)
        # Rename the unique index to standard name
        # SQLite doesn't support RENAME INDEX, but the index works correctly

        print(f"✅ DB migration complete: {old_count} → {new_count} records (deduped)")

    def save_news(self, results: Dict, id_to_name: Dict) -> int:
        """
        Save crawled news results to the database.

        Uses INSERT OR IGNORE with UNIQUE(source_id, title, crawl_date) to prevent
        duplicate entries for the same article on the same day.

        Args:
            results: {source_id: {title: {url, ranks, mobileUrl}}}
            id_to_name: Mapping of source IDs to names (unused in DB)

        Returns:
            int: Number of new records actually inserted.
        """
        if not results:
            return 0

        conn = self._get_connection()
        count = 0
        try:
            cursor = conn.cursor()

            current_time = datetime.datetime.now().isoformat()
            crawl_date = datetime.date.today().isoformat()  # YYYY-MM-DD

            data_to_insert = []
            for source_id, items in results.items():
                for title, info in items.items():
                    url = info.get("url", "")
                    mobile_url = info.get("mobileUrl", "")
                    ranks = info.get("ranks", [])
                    ranks_str = ",".join(map(str, ranks))

                    data_to_insert.append((
                        source_id,
                        title,
                        url,
                        mobile_url,
                        ranks_str,
                        current_time,
                        crawl_date,
                    ))

            cursor.executemany("""
                INSERT OR IGNORE INTO news_articles
                    (source_id, title, url, mobile_url, ranks, crawled_at, crawl_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, data_to_insert)

            conn.commit()
            count = cursor.rowcount  # rows actually inserted (IGNORE skips duplicates)
            skipped = len(data_to_insert) - count
            print(f"✅ Saved {count} news records to database. ({skipped} duplicates skipped)")

        except Exception as e:
            print(f"❌ Error saving to database: {e}")
            conn.rollback()
        finally:
            conn.close()

        return count

    def get_latest_news(self, limit: int = 50) -> List[Dict]:
        """Retrieve latest news from the database."""
        conn = self._get_connection()
        results = []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT source_id, title, url, ranks, crawled_at, mobile_url
                FROM news_articles
                ORDER BY crawled_at DESC
                LIMIT ?
            """, (limit,))
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
        finally:
            conn.close()
        return results

    def get_filtered_news(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        source_id: Optional[str] = None,
        tickers: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """
        Retrieve news with optional filters.

        When *tickers* is supplied the query uses the FTS5 index on
        news_articles.title for fast full-text search with BM25 ranking.
        Falls back to LIKE-based search if FTS5 is unavailable.

        Args:
            start_date: ISO format start (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
            end_date:   ISO format end
            source_id:  Filter by exact source ID (e.g. 'cafef', '24hmoney')
            tickers:    Comma-separated stock ticker(s) searched in titles
                        via alias expansion, e.g. 'VIC' or 'VIC,HPG'
            limit:      Max records to return
        """
        from src.core.ticker_mapper import build_fts_match_query, build_title_conditions

        conn = self._get_connection()
        results = []
        try:
            cursor = conn.cursor()

            if tickers:
                results = self._fts_search(
                    cursor, tickers, start_date, end_date, source_id, limit,
                    build_fts_match_query, build_title_conditions,
                )
            else:
                results = self._plain_search(
                    cursor, start_date, end_date, source_id, limit,
                )

        finally:
            conn.close()
        return results

    # ------------------------------------------------------------------
    # Internal search helpers
    # ------------------------------------------------------------------

    def _fts_search(
        self,
        cursor,
        tickers: str,
        start_date: Optional[str],
        end_date: Optional[str],
        source_id: Optional[str],
        limit: int,
        build_fts_match_query,
        build_title_conditions,
    ) -> List[Dict]:
        """
        FTS5-powered ticker search with BM25 relevance ranking.

        bm25() returns negative values; we negate to get a positive score
        where higher = more relevant.
        """
        match_expr = build_fts_match_query(tickers)
        if not match_expr:
            return []

        params: List = []
        where_parts: List[str] = ["news_fts MATCH ?"]
        params.append(match_expr)

        if start_date:
            if len(start_date) == 10:
                start_date += "T00:00:00"
            where_parts.append("a.crawled_at >= ?")
            params.append(start_date)

        if end_date:
            if len(end_date) == 10:
                end_date += "T23:59:59"
            where_parts.append("a.crawled_at <= ?")
            params.append(end_date)

        if source_id:
            where_parts.append("a.source_id = ?")
            params.append(source_id)

        params.append(limit)

        query = f"""
            SELECT a.source_id, a.title, a.url, a.mobile_url, a.ranks, a.crawled_at,
                   CAST((-bm25(news_fts)) * 100 AS INTEGER) AS relevance_score
            FROM news_fts
            JOIN news_articles a ON news_fts.rowid = a.id
            WHERE {" AND ".join(where_parts)}
            ORDER BY relevance_score DESC, a.crawled_at DESC
            LIMIT ?
        """

        try:
            cursor.execute(query, tuple(params))
        except Exception:
            # FTS5 not available or index inconsistent — fall back to LIKE
            conds, like_params = build_title_conditions(tickers)
            return self._like_search(cursor, conds, like_params, start_date, end_date, source_id, limit)

        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _plain_search(
        self,
        cursor,
        start_date: Optional[str],
        end_date: Optional[str],
        source_id: Optional[str],
        limit: int,
    ) -> List[Dict]:
        """Standard filtered query without full-text search."""
        query = """
            SELECT source_id, title, url, mobile_url, ranks, crawled_at, 1 AS relevance_score
            FROM news_articles
            WHERE 1=1
        """
        params: List = []

        if start_date:
            if len(start_date) == 10:
                start_date += "T00:00:00"
            query += " AND crawled_at >= ?"
            params.append(start_date)

        if end_date:
            if len(end_date) == 10:
                end_date += "T23:59:59"
            query += " AND crawled_at <= ?"
            params.append(end_date)

        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)

        query += " ORDER BY crawled_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _like_search(
        self,
        cursor,
        conditions: List[str],
        like_params: List[str],
        start_date: Optional[str],
        end_date: Optional[str],
        source_id: Optional[str],
        limit: int,
    ) -> List[Dict]:
        """LIKE-based fallback search (used when FTS5 is unavailable)."""
        relevance_cases = " + ".join(
            "CASE WHEN title LIKE ? THEN 1 ELSE 0 END"
            for _ in conditions
        )
        relevance_expr = f"({relevance_cases})" if relevance_cases else "1"

        query = f"""
            SELECT source_id, title, url, mobile_url, ranks, crawled_at,
                   {relevance_expr} AS relevance_score
            FROM news_articles
            WHERE 1=1
        """
        params: List = list(like_params)

        if start_date:
            query += " AND crawled_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND crawled_at <= ?"
            params.append(end_date)
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if conditions:
            query += " AND (" + " OR ".join(conditions) + ")"
            params.extend(like_params)

        query += " ORDER BY relevance_score DESC, crawled_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

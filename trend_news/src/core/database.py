import sqlite3
import datetime
from typing import Dict, List, Optional, Tuple
import os

# Sources excluded from default /api/v1/news feed (non-financial / general content)
NON_FINANCIAL_SOURCES = frozenset([
    "baidu",         # general search trending — mostly non-financial
    "producthunt",   # product launches — tech, not financial
    "hackernews",    # tech discussion — not financial
    "v2ex-share",    # Chinese tech forum
    "weibo",         # social media — mixed quality
    "solidot",       # Chinese IT news
    "zhihu",         # Q&A — mixed quality
])


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
            self._ensure_wm_schema(cursor)
            self._migrate_add_enrichment_columns(cursor)
            conn.commit()
        finally:
            conn.close()

    def _ensure_schema(self, cursor):
        """
        Create or migrate the news_articles table.

        Migration strategy:
        - If table doesn't exist: create with full schema including UNIQUE constraints.
        - Phase 1: If table exists but is old (no crawl_date column): migrate data into
          new schema, deduplicating by (source_id, title, crawl_date) in the process.
        - Phase 2: If idx_unique_url is missing: deduplicate by URL, keeping the latest
          crawled_at per URL, then add partial UNIQUE index on url WHERE url != ''.
        - If table is up-to-date: ensure all indexes exist (idempotent).
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
            # Check if Phase 1 schema is already in place (crawl_date column)
            cursor.execute("PRAGMA table_info(news_articles)")
            columns = {row[1] for row in cursor.fetchall()}

            if "crawl_date" not in columns:
                # Phase 1: Old schema — migrate to crawl_date-based dedup
                self._migrate_to_dedup_schema(cursor)

            # Phase 2: URL-based dedup migration (runs if idx_unique_url is missing)
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_unique_url'"
            )
            if cursor.fetchone() is None:
                self._migrate_to_url_dedup_schema(cursor)
            else:
                # Already fully migrated — ensure all indexes exist (idempotent)
                self._create_indexes(cursor)

        # Phase 3: pre-computed sentiment columns (idempotent)
        cursor.execute("PRAGMA table_info(news_articles)")
        columns_now = {row[1] for row in cursor.fetchall()}
        if "sentiment_score" not in columns_now:
            self._migrate_add_sentiment_columns(cursor)

        # Always ensure FTS5 index is present (idempotent)
        self._ensure_fts_index(cursor)

    def _create_fresh_table(self, cursor):
        """Create news_articles table with dedup schema from scratch."""
        cursor.execute("""
            CREATE TABLE news_articles (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id       TEXT NOT NULL,
                title           TEXT NOT NULL,
                url             TEXT DEFAULT '',
                mobile_url      TEXT DEFAULT '',
                ranks           TEXT,
                crawled_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                crawl_date      TEXT NOT NULL,
                sentiment_score REAL,
                sentiment_label TEXT
            )
        """)
        self._create_indexes(cursor)

    def _create_indexes(self, cursor):
        """Create performance and dedup indexes."""
        # Primary dedup: one row per URL (ignores empty URLs)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_url
            ON news_articles(url) WHERE url != ''
        """)
        # Fallback dedup: for articles without URL, dedup by (source, title, day)
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

    def _migrate_to_url_dedup_schema(self, cursor):
        """
        Phase 2 migration: deduplicate rows by URL, keeping the latest crawled_at
        per URL, then add a partial UNIQUE index on url WHERE url != ''.

        This prevents the same article from being stored again when the crawler
        re-crawls it on a subsequent day (cross-day duplicate problem).

        Articles with empty URL are unaffected and continue to be deduplicated
        by the existing (source_id, title, crawl_date) UNIQUE index.
        """
        print("⚙ DB migration (Phase 2): deduplicating rows by URL...")

        cursor.execute("SELECT COUNT(*) FROM news_articles")
        old_count = cursor.fetchone()[0]

        # For each URL, keep only the row with the latest crawled_at.
        # Tiebreak by MAX(id) when crawled_at is identical.
        # Uses ROW_NUMBER() window function (requires SQLite 3.25+).
        cursor.execute("""
            DELETE FROM news_articles
            WHERE url != ''
              AND id NOT IN (
                  SELECT id FROM (
                      SELECT id,
                             ROW_NUMBER() OVER (
                                 PARTITION BY url
                                 ORDER BY crawled_at DESC, id DESC
                             ) AS rn
                      FROM news_articles
                      WHERE url != ''
                  ) sub
                  WHERE rn = 1
              )
        """)

        cursor.execute("SELECT COUNT(*) FROM news_articles")
        new_count = cursor.fetchone()[0]
        removed = old_count - new_count

        # Partial UNIQUE index: one row per non-empty URL
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_url
            ON news_articles(url) WHERE url != ''
        """)
        # Ensure all other indexes exist (idempotent)
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

        print(
            f"✅ URL dedup migration complete: {old_count} → {new_count} records "
            f"({removed} cross-day duplicates removed)"
        )

    def _migrate_add_sentiment_columns(self, cursor):
        """
        Phase 3: Add pre-computed sentiment columns to news_articles.
        ALTER TABLE ADD COLUMN is safe for nullable columns in SQLite.
        Existing rows receive NULL — batch_sentiment.py will fill them.
        """
        print("DB migration (Phase 3): adding sentiment_score and sentiment_label columns...")
        cursor.execute("ALTER TABLE news_articles ADD COLUMN sentiment_score REAL")
        cursor.execute("ALTER TABLE news_articles ADD COLUMN sentiment_label TEXT")
        print("DB migration (Phase 3) complete.")

    def _migrate_add_enrichment_columns(self, cursor):
        """Phase 4: Add WM enrichment columns (idempotent)."""
        cursor.execute("PRAGMA table_info(news_articles)")
        existing = {r[1] for r in cursor.fetchall()}
        new_cols = {
            "threat_level":  "TEXT",
            "geo_relevance": "REAL DEFAULT 0.0",
            "market_signal": "TEXT",
            "wm_sources":    "TEXT",    # JSON array
        }
        for col, col_type in new_cols.items():
            if col not in existing:
                cursor.execute(f"ALTER TABLE news_articles ADD COLUMN {col} {col_type}")
                print(f"  + Added column: {col}")

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
                SELECT source_id, title, url, ranks, crawled_at, mobile_url,
                       sentiment_score, sentiment_label
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
                   a.sentiment_score, a.sentiment_label,
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
            SELECT source_id, title, url, mobile_url, ranks, crawled_at,
                   sentiment_score, sentiment_label,
                   1 AS relevance_score
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
        else:
            # Exclude non-financial sources from default feed
            placeholders = ",".join("?" * len(NON_FINANCIAL_SOURCES))
            query += f" AND source_id NOT IN ({placeholders})"
            params.extend(sorted(NON_FINANCIAL_SOURCES))

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
                   sentiment_score, sentiment_label,
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

    # ------------------------------------------------------------------
    # Batch sentiment helpers
    # ------------------------------------------------------------------

    def get_unscored_news(self, limit: int = 500) -> List[Dict]:
        """
        Return articles where sentiment_score IS NULL, ordered oldest-first.
        Used by batch_sentiment.py to find rows that still need scoring.
        """
        conn = self._get_connection()
        results = []
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, crawled_at
                FROM news_articles
                WHERE sentiment_score IS NULL
                ORDER BY crawled_at ASC
                LIMIT ?
            """, (limit,))
            columns = [col[0] for col in cursor.description]
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
        finally:
            conn.close()
        return results

    def batch_update_news_sentiment(
        self, updates: List[Tuple[int, float, str]]
    ) -> int:
        """
        Bulk-update sentiment_score and sentiment_label for a list of articles.

        Args:
            updates: List of (article_id, sentiment_score, sentiment_label)

        Returns:
            Number of rows updated.
        """
        if not updates:
            return 0
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany("""
                UPDATE news_articles
                SET sentiment_score = ?, sentiment_label = ?
                WHERE id = ?
            """, [(score, label, article_id) for article_id, score, label in updates])
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# WM (WorldMonitor) articles table — Option B implementation
# ──────────────────────────────────────────────────────────────────────────────

    def _ensure_wm_schema(self, cursor):
        """
        Create wm_articles table and indexes if they don't exist.
        Safe to call on every startup (idempotent).
        """
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wm_articles (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id        TEXT NOT NULL,
                source_name      TEXT NOT NULL,
                title            TEXT NOT NULL,
                url              TEXT DEFAULT '',
                wm_category      TEXT NOT NULL,
                threat_level     TEXT DEFAULT 'info',
                threat_category  TEXT DEFAULT 'general',
                threat_confidence REAL DEFAULT 0.5,
                geo_relevance    REAL DEFAULT 0.0,
                published_at     INTEGER,
                crawled_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                crawl_date       TEXT NOT NULL
            )
        """)
        # URL dedup (cross-day: same article won't be re-inserted)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wm_unique_url
            ON wm_articles(url) WHERE url != ''
        """)
        # Title dedup (same-day same source)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_wm_unique_title
            ON wm_articles(source_id, title, crawl_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wm_crawl_date
            ON wm_articles(crawl_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wm_category
            ON wm_articles(wm_category)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wm_threat
            ON wm_articles(threat_level)
        """)
        # FTS5 for semantic search across WM titles
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='wm_articles_fts'"
        )
        if cursor.fetchone() is None:
            cursor.execute("""
                CREATE VIRTUAL TABLE wm_articles_fts USING fts5(
                    title,
                    content='wm_articles',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 0'
                )
            """)
            cursor.execute("""
                INSERT INTO wm_articles_fts(rowid, title)
                SELECT id, title FROM wm_articles
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS wm_articles_ai
                AFTER INSERT ON wm_articles BEGIN
                    INSERT INTO wm_articles_fts(rowid, title)
                    VALUES (new.id, new.title);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS wm_articles_ad
                AFTER DELETE ON wm_articles BEGIN
                    INSERT INTO wm_articles_fts(wm_articles_fts, rowid, title)
                    VALUES ('delete', old.id, old.title);
                END
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS wm_articles_au
                AFTER UPDATE ON wm_articles BEGIN
                    INSERT INTO wm_articles_fts(wm_articles_fts, rowid, title)
                    VALUES ('delete', old.id, old.title);
                    INSERT INTO wm_articles_fts(rowid, title)
                    VALUES (new.id, new.title);
                END
            """)

    def save_wm_articles(self, wm_articles: List[Dict]) -> int:
        """
        Save WorldMonitor articles to wm_articles table.

        Uses INSERT OR IGNORE with:
          - UNIQUE(url) WHERE url != ''         → cross-day URL dedup
          - UNIQUE(source_id, title, crawl_date) → same-day title dedup

        Args:
            wm_articles: List of article dicts from WorldMonitorFetcher.fetch_flat()

        Returns:
            Number of new records inserted.
        """
        if not wm_articles:
            return 0

        import datetime
        conn = self._get_connection()
        count = 0
        try:
            cursor = conn.cursor()
            # Ensure wm_articles table exists
            self._ensure_wm_schema(cursor)

            current_time = datetime.datetime.now().isoformat()
            crawl_date = datetime.date.today().isoformat()

            data = []
            for a in wm_articles:
                data.append((
                    a.get("source", "unknown").lower().replace(" ", "-"),  # source_id
                    a.get("source", "Unknown"),                             # source_name
                    a.get("title", ""),                                    # title
                    a.get("url", ""),                                      # url
                    a.get("wm_category", "general"),                       # wm_category
                    a.get("threat_level", "info"),                         # threat_level
                    a.get("threat_category", "general"),                   # threat_category
                    a.get("threat_confidence", 0.5),                       # threat_confidence
                    a.get("geo_relevance", 0.0),                           # geo_relevance
                    a.get("published_at"),                                 # published_at
                    current_time,                                          # crawled_at
                    crawl_date,                                            # crawl_date
                ))

            cursor.executemany("""
                INSERT OR IGNORE INTO wm_articles
                    (source_id, source_name, title, url, wm_category,
                     threat_level, threat_category, threat_confidence,
                     geo_relevance, published_at, crawled_at, crawl_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)

            conn.commit()
            count = cursor.rowcount
            skipped = len(data) - count
            print(f"  ✓ WM DB: saved {count} articles ({skipped} duplicates skipped)")
        except Exception as e:
            conn.rollback()
            print(f"  ✗ WM DB save error: {e}")
        finally:
            conn.close()
        return count

    def get_wm_articles(
        self,
        crawl_date: str = None,
        category: str = None,
        threat_levels: List[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        Query WM articles with optional filters.

        Args:
            crawl_date:    'YYYY-MM-DD' — defaults to today
            category:      'asia' | 'vietnam' | 'finance' | 'geopolitical' | 'tech'
            threat_levels: e.g. ['critical', 'high']
            limit:         max rows

        Returns:
            List of article dicts.
        """
        import datetime
        if crawl_date is None:
            crawl_date = datetime.date.today().isoformat()

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wm_articles'"
            )
            if cursor.fetchone() is None:
                return []

            conditions = ["crawl_date = ?"]
            params: List = [crawl_date]

            if category:
                conditions.append("wm_category = ?")
                params.append(category)

            if threat_levels:
                placeholders = ",".join("?" * len(threat_levels))
                conditions.append(f"threat_level IN ({placeholders})")
                params.extend(threat_levels)

            where = " AND ".join(conditions)
            cursor.execute(f"""
                SELECT id, source_name, title, url, wm_category,
                       threat_level, threat_category, geo_relevance,
                       published_at, crawl_date
                FROM wm_articles
                WHERE {where}
                ORDER BY geo_relevance DESC, published_at DESC
                LIMIT ?
            """, params + [limit])

            cols = [c[0] for c in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search_wm_articles(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Full-text search across WM article titles.

        Args:
            query: Search terms (FTS5 syntax supported)
            limit: Max results

        Returns:
            List of matching article dicts.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wm_articles_fts'"
            )
            if cursor.fetchone() is None:
                return []

            cursor.execute("""
                SELECT w.id, w.source_name, w.title, w.url, w.wm_category,
                       w.threat_level, w.geo_relevance, w.crawl_date,
                       rank
                FROM wm_articles_fts f
                JOIN wm_articles w ON w.id = f.rowid
                WHERE wm_articles_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit))
            cols = [c[0] for c in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_wm_stats(self, crawl_date: str = None) -> Dict:
        """
        Get summary stats for WM articles on a given date.

        Returns:
            {total, by_category, by_threat, high_geo_relevance}
        """
        import datetime
        if crawl_date is None:
            crawl_date = datetime.date.today().isoformat()

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='wm_articles'"
            )
            if cursor.fetchone() is None:
                return {"total": 0}

            cursor.execute(
                "SELECT COUNT(*) FROM wm_articles WHERE crawl_date = ?", (crawl_date,)
            )
            total = cursor.fetchone()[0]

            cursor.execute("""
                SELECT wm_category, COUNT(*) cnt
                FROM wm_articles WHERE crawl_date = ?
                GROUP BY wm_category ORDER BY cnt DESC
            """, (crawl_date,))
            by_category = dict(cursor.fetchall())

            cursor.execute("""
                SELECT threat_level, COUNT(*) cnt
                FROM wm_articles WHERE crawl_date = ?
                GROUP BY threat_level ORDER BY cnt DESC
            """, (crawl_date,))
            by_threat = dict(cursor.fetchall())

            cursor.execute("""
                SELECT title, source_name, wm_category, threat_level, geo_relevance
                FROM wm_articles
                WHERE crawl_date = ? AND geo_relevance >= 0.4
                ORDER BY geo_relevance DESC LIMIT 5
            """, (crawl_date,))
            high_geo = [dict(zip(
                ["title", "source", "category", "threat", "geo"], row
            )) for row in cursor.fetchall()]

            return {
                "total": total,
                "by_category": by_category,
                "by_threat": by_threat,
                "high_geo_relevance": high_geo,
            }
        finally:
            conn.close()

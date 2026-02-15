import sqlite3
import datetime
from typing import Dict, List, Optional
import os
from pathlib import Path

class DatabaseManager:
    """
    Manages SQLite database interactions for storing news data.
    """
    
    def __init__(self, db_path: str = "trend_news.db"):
        """
        Initialize the database manager.
        
        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        """Initialize database tables if they don't exist."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Create news_articles table
            # distinct_id is a combination of source + url or source + title to avoid duplicates if needed
            # But for trending news, we might want to track history of ranks.
            # For now, let's just log every crawl event.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    mobile_url TEXT,
                    ranks TEXT, -- Stored as comma-separated string or JSON
                    crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create index for faster querying
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_crawled_at 
                ON news_articles(crawled_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_news_source 
                ON news_articles(source_id)
            """)
            
            conn.commit()
        finally:
            conn.close()
            
    def _get_connection(self):
        """Get a database connection."""
        # Ensure the directory exists
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        return sqlite3.connect(self.db_path)
        
    def save_news(self, results: Dict, id_to_name: Dict) -> int:
        """
        Save crawled news results to the database.
        
        Args:
            results: Dictionary of crawl results.
                     Format: {source_id: {title: {url: ..., ranks: ...}}}
            id_to_name: Dictionary mapping source IDs to names (not used in DB yet, but good for context)
            
        Returns:
            int: Number of records saved.
        """
        if not results:
            return 0
            
        conn = self._get_connection()
        count = 0
        try:
            cursor = conn.cursor()
            
            current_time = datetime.datetime.now().isoformat()
            
            # Prepare data for batch insert
            data_to_insert = []
            
            for source_id, items in results.items():
                for title, info in items.items():
                    url = info.get("url", "")
                    mobile_url = info.get("mobileUrl", "")
                    ranks = info.get("ranks", [])
                    
                    # Convert ranks list to string for simple storage
                    ranks_str = ",".join(map(str, ranks))
                    
                    data_to_insert.append((
                        source_id,
                        title,
                        url,
                        mobile_url,
                        ranks_str,
                        current_time
                    ))
            
            cursor.executemany("""
                INSERT INTO news_articles (source_id, title, url, mobile_url, ranks, crawled_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, data_to_insert)
            
            conn.commit()
            count = len(data_to_insert)
            print(f"✅ Saved {count} news records to database.")
            
        except Exception as e:
            print(f"❌ Error saving to database: {e}")
            conn.rollback()
        finally:
            conn.close()
            
        return count

    def get_latest_news(self, limit: int = 50) -> List[Dict]:
        """
        Retrieve latest news from the database (example for API).
        """
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
            
            columns = [column[0] for column in cursor.description]
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
        limit: int = 50
    ) -> List[Dict]:
        """
        Retrieve news with filters.
        
        Args:
            start_date: Start date (inclusive) in ISO format (YYYY-MM-DD or full timestamp).
            end_date: End date (inclusive) in ISO format.
            source_id: Filter by source ID.
            limit: Max records to return.
            
        Returns:
            List of news dictionaries.
        """
        conn = self._get_connection()
        results = []
        try:
            cursor = conn.cursor()
            
            query = "SELECT source_id, title, url, mobile_url, ranks, crawled_at FROM news_articles WHERE 1=1"
            params = []
            
            if start_date:
                # Assuming start_date is meant to be beginning of that day if only YYYY-MM-DD provided
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
            
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                item = dict(zip(columns, row))
                # Normalize keys to match API expectations if needed
                # For now keeping DB keys
                results.append(item)
                
        finally:
            conn.close()
        return results

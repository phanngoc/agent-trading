"""
Dynamic Sentiment Learning System

Hệ thống học sentiment từ feedback người dùng và tự động cải thiện lexicon.
"""
import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import Counter, defaultdict
import re


class SentimentLearningManager:
    """Quản lý việc học và cải thiện sentiment lexicon từ feedback"""
    
    def __init__(self, db_path: str = "trend_news.db"):
        self.db_path = db_path
        self._init_learning_tables()
    
    def _get_connection(self):
        """Get database connection"""
        return sqlite3.connect(self.db_path)
    
    def _init_learning_tables(self):
        """Khởi tạo các bảng cho learning system"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Bảng feedback người dùng
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sentiment_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER,
                    news_title TEXT NOT NULL,
                    news_url TEXT,
                    predicted_score REAL,
                    predicted_label TEXT,
                    user_score REAL,
                    user_label TEXT,
                    user_comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (news_id) REFERENCES news_articles(id)
                )
            """)
            
            # Bảng từ khóa được học
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS learned_keywords (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT UNIQUE NOT NULL,
                    sentiment_type TEXT NOT NULL, -- 'positive' or 'negative'
                    weight REAL NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    frequency INTEGER DEFAULT 1,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT DEFAULT 'user_feedback', -- 'user_feedback', 'auto_extracted', 'manual'
                    status TEXT DEFAULT 'pending' -- 'pending', 'approved', 'rejected'
                )
            """)
            
            # Bảng keyword suggestions từ data mining
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS keyword_suggestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    sentiment_type TEXT NOT NULL,
                    suggested_weight REAL,
                    co_occurrence_count INTEGER DEFAULT 1,
                    supporting_titles TEXT, -- JSON array of titles
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed BOOLEAN DEFAULT 0
                )
            """)
            
            # Bảng performance metrics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sentiment_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    total_predictions INTEGER DEFAULT 0,
                    accurate_predictions INTEGER DEFAULT 0,
                    accuracy_rate REAL,
                    avg_error REAL,
                    lexicon_version TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_created 
                ON sentiment_feedback(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_keywords_status 
                ON learned_keywords(status)
            """)
            
            conn.commit()
            print("✅ Initialized sentiment learning tables")
        finally:
            conn.close()
    
    def add_feedback(
        self, 
        news_title: str,
        predicted_score: float,
        predicted_label: str,
        user_score: float,
        user_label: str,
        news_id: Optional[int] = None,
        news_url: Optional[str] = None,
        comment: Optional[str] = None
    ) -> int:
        """
        Thêm feedback từ người dùng
        
        Returns:
            feedback_id
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sentiment_feedback 
                (news_id, news_title, news_url, predicted_score, predicted_label, 
                 user_score, user_label, user_comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (news_id, news_title, news_url, predicted_score, predicted_label,
                  user_score, user_label, comment, datetime.now().isoformat()))
            
            conn.commit()
            feedback_id = cursor.lastrowid
            
            # Auto-extract keywords nếu có difference lớn
            if feedback_id is not None and abs(user_score - predicted_score) > 0.3:
                self._extract_keywords_from_feedback(
                    feedback_id, news_title, user_score, user_label
                )
            
            return feedback_id if feedback_id is not None else 0
        finally:
            conn.close()
    
    def _extract_keywords_from_feedback(
        self,
        feedback_id: int,
        title: str,
        user_score: float,
        user_label: str
    ):
        """Tự động trích xuất từ khóa từ feedback"""
        # Lấy các từ 2-3 từ liên tiếp
        words = re.findall(r'\b\w+\b', title.lower())
        
        sentiment_type = "positive" if user_score > 0.15 else "negative" if user_score < -0.15 else None
        if not sentiment_type:
            return
        
        # Trích xuất n-grams
        potential_keywords = []
        
        # Bigrams
        for i in range(len(words) - 1):
            potential_keywords.append(" ".join(words[i:i+2]))
        
        # Trigrams
        for i in range(len(words) - 2):
            potential_keywords.append(" ".join(words[i:i+3]))
        
        # Lưu vào suggestions table
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            for keyword in potential_keywords:
                if len(keyword) > 3:  # Filter too short
                    cursor.execute("""
                        INSERT OR IGNORE INTO keyword_suggestions 
                        (keyword, sentiment_type, suggested_weight, supporting_titles)
                        VALUES (?, ?, ?, ?)
                    """, (keyword, sentiment_type, abs(user_score), json.dumps([title])))
            conn.commit()
        finally:
            conn.close()
    
    def mine_keywords_from_database(
        self, 
        min_frequency: int = 3,
        lookback_days: int = 30
    ) -> Dict[str, List[Dict]]:
        """
        Đào từ khóa từ database dựa trên patterns
        
        Returns:
            {'positive': [...], 'negative': [...]}
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Lấy feedback từ người dùng
            cursor.execute("""
                SELECT news_title, user_score, user_label
                FROM sentiment_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                AND ABS(user_score) >= 0.15
            """, (lookback_days,))
            
            feedback_data = cursor.fetchall()
            
            # Phân tích n-grams
            positive_ngrams = Counter()
            negative_ngrams = Counter()
            
            for title, score, label in feedback_data:
                words = re.findall(r'\b\w+\b', title.lower())
                
                # Extract bigrams and trigrams
                ngrams = []
                for i in range(len(words) - 1):
                    ngrams.append(" ".join(words[i:i+2]))
                for i in range(len(words) - 2):
                    ngrams.append(" ".join(words[i:i+3]))
                
                if score > 0.15:
                    positive_ngrams.update(ngrams)
                elif score < -0.15:
                    negative_ngrams.update(ngrams)
            
            # Filter by frequency
            positive_keywords = [
                {
                    'keyword': kw, 
                    'frequency': freq,
                    'suggested_weight': min(1.0, freq / 10),
                    'sentiment_type': 'positive'
                }
                for kw, freq in positive_ngrams.items() 
                if freq >= min_frequency
            ]
            
            negative_keywords = [
                {
                    'keyword': kw,
                    'frequency': freq,
                    'suggested_weight': min(1.0, freq / 10),
                    'sentiment_type': 'negative'
                }
                for kw, freq in negative_ngrams.items()
                if freq >= min_frequency
            ]
            
            return {
                'positive': sorted(positive_keywords, key=lambda x: -x['frequency']),
                'negative': sorted(negative_keywords, key=lambda x: -x['frequency'])
            }
        finally:
            conn.close()
    
    def approve_keyword(
        self, 
        keyword: str, 
        sentiment_type: str, 
        weight: float
    ) -> bool:
        """Phê duyệt keyword vào lexicon chính"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO learned_keywords 
                (keyword, sentiment_type, weight, confidence, frequency, status, last_seen)
                VALUES (?, ?, ?, 1.0, 1, 'approved', ?)
            """, (keyword, sentiment_type, weight, datetime.now().isoformat()))
            conn.commit()
            return True
        except Exception as e:
            print(f"Error approving keyword: {e}")
            return False
        finally:
            conn.close()
    
    def get_approved_keywords(self) -> Dict[str, Dict[str, float]]:
        """Lấy tất cả keywords đã được approve"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT keyword, sentiment_type, weight
                FROM learned_keywords
                WHERE status = 'approved'
                ORDER BY weight DESC
            """)
            
            results = {'positive': {}, 'negative': {}}
            for keyword, sentiment_type, weight in cursor.fetchall():
                results[sentiment_type][keyword] = weight
            
            return results
        finally:
            conn.close()
    
    def get_feedback_stats(self, days: int = 7) -> Dict:
        """Lấy thống kê feedback"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Total feedback
            cursor.execute("""
                SELECT COUNT(*), 
                       AVG(ABS(user_score - predicted_score)) as avg_error
                FROM sentiment_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
            """, (days,))
            
            total, avg_error = cursor.fetchone()
            
            # Accuracy (within 0.2 range)
            cursor.execute("""
                SELECT COUNT(*)
                FROM sentiment_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                AND ABS(user_score - predicted_score) <= 0.2
            """, (days,))
            
            accurate = cursor.fetchone()[0]
            accuracy = (accurate / total * 100) if total > 0 else 0
            
            return {
                'total_feedback': total or 0,
                'accurate_predictions': accurate or 0,
                'accuracy_rate': round(accuracy, 2),
                'avg_error': round(avg_error or 0, 3),
                'period_days': days
            }
        finally:
            conn.close()
    
    def get_pending_suggestions(self, limit: int = 50) -> List[Dict]:
        """Lấy các suggestions chờ review"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, keyword, sentiment_type, suggested_weight, 
                       co_occurrence_count, supporting_titles
                FROM keyword_suggestions
                WHERE reviewed = 0
                ORDER BY co_occurrence_count DESC
                LIMIT ?
            """, (limit,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'keyword': row[1],
                    'sentiment_type': row[2],
                    'suggested_weight': row[3],
                    'frequency': row[4],
                    'examples': json.loads(row[5]) if row[5] else []
                })
            return results
        finally:
            conn.close()


class DynamicLexiconManager:
    """Quản lý lexicon động, kết hợp static + learned keywords"""
    
    def __init__(self, learning_manager: SentimentLearningManager):
        self.learning_manager = learning_manager
        self._cache = None
        self._cache_time = None
    
    def get_combined_lexicon(self) -> Dict[str, Dict[str, float]]:
        """
        Lấy lexicon kết hợp (static + learned)
        Cache 5 phút để tối ưu performance
        """
        from src.utils.sentiment import _VI_POSITIVE, _VI_NEGATIVE
        
        # Check cache
        now = datetime.now()
        if self._cache and self._cache_time:
            if (now - self._cache_time).seconds < 300:  # 5 minutes
                return self._cache
        
        # Load learned keywords
        learned = self.learning_manager.get_approved_keywords()
        
        # Combine with static
        combined = {
            'positive': {**_VI_POSITIVE, **learned['positive']},
            'negative': {**_VI_NEGATIVE, **learned['negative']}
        }
        
        # Update cache
        self._cache = combined
        self._cache_time = now
        
        return combined
    
    def refresh_cache(self):
        """Force refresh cache"""
        self._cache = None
        self._cache_time = None

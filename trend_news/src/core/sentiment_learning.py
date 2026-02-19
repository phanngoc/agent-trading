"""  
Dynamic Sentiment Learning System

Hệ thống học sentiment từ feedback người dùng và tự động cải thiện lexicon.
"""
import os
import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import Counter, defaultdict
import re


class SentimentLearningManager:
    """Quản lý việc học và cải thiện sentiment lexicon từ feedback"""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            # Default to output/trend_news.db relative to project root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(project_root, "output", "trend_news.db")
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
    
    def get_pending_suggestions_count(self) -> int:
        """Đếm tổng số suggestions chưa review"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM keyword_suggestions WHERE reviewed = 0
            """)
            return cursor.fetchone()[0] or 0
        finally:
            conn.close()
    
    def get_pending_suggestions_paginated(
        self, 
        offset: int = 0, 
        limit: int = 20,
        sentiment_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Lấy các suggestions chờ review có phân trang
        
        Args:
            offset: Số bản ghi bỏ qua
            limit: Số bản ghi lấy
            sentiment_filter: 'positive', 'negative', hoặc None (tất cả)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            if sentiment_filter:
                cursor.execute("""
                    SELECT id, keyword, sentiment_type, suggested_weight, 
                           co_occurrence_count, supporting_titles
                    FROM keyword_suggestions
                    WHERE reviewed = 0 AND sentiment_type = ?
                    ORDER BY co_occurrence_count DESC, id ASC
                    LIMIT ? OFFSET ?
                """, (sentiment_filter, limit, offset))
            else:
                cursor.execute("""
                    SELECT id, keyword, sentiment_type, suggested_weight, 
                           co_occurrence_count, supporting_titles
                    FROM keyword_suggestions
                    WHERE reviewed = 0
                    ORDER BY co_occurrence_count DESC, id ASC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
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
    
    def reject_keyword(self, suggestion_id: int) -> bool:
        """
        Từ chối một keyword suggestion
        
        Args:
            suggestion_id: ID của suggestion trong bảng keyword_suggestions
            
        Returns:
            True nếu thành công, False nếu thất bại
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE keyword_suggestions 
                SET reviewed = 1
                WHERE id = ?
            """, (suggestion_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error rejecting keyword: {e}")
            return False
        finally:
            conn.close()
    
    def reject_keyword_by_text(self, keyword: str, sentiment_type: str) -> bool:
        """
        Từ chối tất cả suggestions có keyword và sentiment_type cụ thể
        
        Args:
            keyword: Text của keyword
            sentiment_type: 'positive' hoặc 'negative'
            
        Returns:
            True nếu thành công, False nếu thất bại
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE keyword_suggestions 
                SET reviewed = 1
                WHERE keyword = ? AND sentiment_type = ? AND reviewed = 0
            """, (keyword, sentiment_type))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error rejecting keyword: {e}")
            return False
        finally:
            conn.close()
    
    def mark_suggestion_reviewed(self, suggestion_id: int) -> bool:
        """Đánh dấu một suggestion đã được review"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE keyword_suggestions 
                SET reviewed = 1
                WHERE id = ?
            """, (suggestion_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error marking suggestion as reviewed: {e}")
            return False
        finally:
            conn.close()
    
    def get_auto_aggregated_keywords(
        self, 
        min_confidence: float = 0.3,
        min_frequency: int = 2,
        lookback_days: int = 30
    ) -> Dict[str, Dict[str, float]]:
        """
        Tự động aggregate keywords từ suggestions để dùng trong sentiment scoring.
        Không cần admin approve - tính toán dựa trên frequency và consensus.
        
        Args:
            min_confidence: Ngưỡng confidence tối thiểu (0-1)
            min_frequency: Số lần xuất hiện tối thiểu
            lookback_days: Chỉ xét suggestions trong N ngày gần nhất
            
        Returns:
            {'positive': {'keyword': weight}, 'negative': {...}}
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Aggregate keywords từ suggestions
            cursor.execute("""
                SELECT 
                    keyword,
                    sentiment_type,
                    COUNT(*) as freq,
                    AVG(suggested_weight) as avg_weight,
                    MAX(co_occurrence_count) as max_cooccur
                FROM keyword_suggestions
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                GROUP BY keyword, sentiment_type
                HAVING freq >= ?
                ORDER BY freq DESC, avg_weight DESC
            """, (lookback_days, min_frequency))
            
            results = {'positive': {}, 'negative': {}}
            
            for row in cursor.fetchall():
                keyword, sentiment_type, freq, avg_weight, max_cooccur = row
                
                # Tính confidence dựa trên frequency và consistency
                # Càng nhiều lần xuất hiện → confidence càng cao
                confidence = min(1.0, freq / 10) * min(1.0, max_cooccur / 5)
                
                if confidence >= min_confidence:
                    # Weight = avg_weight * confidence scaling
                    # Nhưng cap ở 0.8 để không vượt quá static keywords
                    weight = min(0.8, (avg_weight or 0.5) * (0.5 + confidence * 0.5))
                    results[sentiment_type][keyword] = round(weight, 3)
            
            return results
            
        finally:
            conn.close()
    
    def get_combined_auto_lexicon(
        self,
        static_positive: Dict[str, float],
        static_negative: Dict[str, float],
        min_confidence: float = 0.3,
        min_frequency: int = 2
    ) -> Dict[str, Dict[str, float]]:
        """
        Kết hợp static lexicon với auto-aggregated keywords.
        Auto keywords sẽ override static nếu có confidence cao.
        
        Returns:
            {'positive': {...}, 'negative': {...}}
        """
        auto_keywords = self.get_auto_aggregated_keywords(
            min_confidence=min_confidence,
            min_frequency=min_frequency
        )
        
        # Merge: static là base, auto keywords override nếu mạnh hơn
        combined = {
            'positive': {**static_positive, **auto_keywords['positive']},
            'negative': {**static_negative, **auto_keywords['negative']}
        }
        
        return combined

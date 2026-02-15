"""
Keyword Extractor - Tự động phát hiện từ khóa mới từ database

Phân tích patterns trong news titles để tìm từ khóa có tiềm năng
"""
import sqlite3
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Set
from datetime import datetime, timedelta
import json


class KeywordExtractor:
    """Trích xuất và phân tích từ khóa từ news database"""
    
    def __init__(self, db_path: str = "trend_news.db"):
        self.db_path = db_path
        
        # Stop words tiếng Việt
        self.stop_words = {
            'của', 'và', 'có', 'này', 'cho', 'từ', 'với', 'trong', 'là',
            'được', 'các', 'để', 'một', 'về', 'đã', 'những', 'thì', 
            'sẽ', 'như', 'trên', 'ra', 'tại', 'hay', 'theo', 'đến',
            'hôm', 'nay', 'ngày', 'tháng', 'năm', 'giờ', 'phút',
            'vn', 'việt', 'nam', 'việt nam', 'đang', 'bị', 'sau', 'trước'
        }
    
    def _get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def extract_ngrams(
        self, 
        text: str, 
        n: int = 2
    ) -> List[str]:
        """Trích xuất n-grams từ text"""
        # Lowercase và tokenize
        text = text.lower()
        # Giữ lại dấu tiếng Việt
        words = re.findall(r'\b[\w\u00C0-\u1EF9]+\b', text)
        
        # Filter stop words
        words = [w for w in words if w not in self.stop_words]
        
        ngrams = []
        for i in range(len(words) - n + 1):
            ngram = " ".join(words[i:i+n])
            if len(ngram) > 2:  # Skip very short phrases
                ngrams.append(ngram)
        
        return ngrams
    
    def analyze_sentiment_patterns(
        self,
        days: int = 30,
        min_frequency: int = 5
    ) -> Dict[str, List[Dict]]:
        """
        Phân tích patterns từ news có sentiment feedback
        
        Returns:
            Các từ khóa tiềm năng phân loại theo positive/negative
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Lấy feedback data
            cursor.execute("""
                SELECT news_title, user_score, user_label
                FROM sentiment_feedback
                WHERE created_at >= datetime('now', '-' || ? || ' days')
                AND ABS(user_score) >= 0.2
            """, (days,))
            
            feedback_data = cursor.fetchall()
            
            if not feedback_data:
                return {'positive': [], 'negative': []}
            
            # Collect ngrams theo sentiment
            positive_ngrams = Counter()
            negative_ngrams = Counter()
            
            # Track examples
            positive_examples = defaultdict(list)
            negative_examples = defaultdict(list)
            
            for title, score, label in feedback_data:
                # Extract bigrams and trigrams
                bigrams = self.extract_ngrams(title, n=2)
                trigrams = self.extract_ngrams(title, n=3)
                
                all_ngrams = bigrams + trigrams
                
                if score > 0.2:  # Positive
                    positive_ngrams.update(all_ngrams)
                    for ng in all_ngrams:
                        if len(positive_examples[ng]) < 3:
                            positive_examples[ng].append(title)
                            
                elif score < -0.2:  # Negative
                    negative_ngrams.update(all_ngrams)
                    for ng in all_ngrams:
                        if len(negative_examples[ng]) < 3:
                            negative_examples[ng].append(title)
            
            # Build results
            positive_keywords = []
            for keyword, freq in positive_ngrams.most_common(100):
                if freq >= min_frequency:
                    positive_keywords.append({
                        'keyword': keyword,
                        'frequency': freq,
                        'suggested_weight': min(1.0, 0.3 + (freq / 20)),
                        'examples': positive_examples[keyword][:3]
                    })
            
            negative_keywords = []
            for keyword, freq in negative_ngrams.most_common(100):
                if freq >= min_frequency:
                    negative_keywords.append({
                        'keyword': keyword,
                        'frequency': freq,
                        'suggested_weight': min(1.0, 0.3 + (freq / 20)),
                        'examples': negative_examples[keyword][:3]
                    })
            
            return {
                'positive': positive_keywords,
                'negative': negative_keywords
            }
            
        finally:
            conn.close()
    
    def find_cooccurring_keywords(
        self,
        known_positive: List[str],
        known_negative: List[str],
        days: int = 30,
        min_cooccurrence: int = 3
    ) -> Dict[str, List[Dict]]:
        """
        Tìm từ khóa xuất hiện cùng với các từ khóa đã biết
        Giúp mở rộng lexicon dựa trên context
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get recent news
            cursor.execute("""
                SELECT title 
                FROM news_articles
                WHERE crawled_at >= datetime('now', '-' || ? || ' days')
            """, (days,))
            
            all_titles = [row[0] for row in cursor.fetchall()]
            
            # Track co-occurrences
            positive_cooccur = Counter()
            negative_cooccur = Counter()
            
            for title in all_titles:
                title_lower = title.lower()
                ngrams = self.extract_ngrams(title, n=2) + self.extract_ngrams(title, n=3)
                
                # Check if positive keywords present
                has_positive = any(kw in title_lower for kw in known_positive)
                if has_positive:
                    positive_cooccur.update(ngrams)
                
                # Check if negative keywords present
                has_negative = any(kw in title_lower for kw in known_negative)
                if has_negative:
                    negative_cooccur.update(ngrams)
            
            # Filter out known keywords
            positive_new = [
                {'keyword': kw, 'frequency': freq}
                for kw, freq in positive_cooccur.most_common(50)
                if kw not in known_positive and freq >= min_cooccurrence
            ]
            
            negative_new = [
                {'keyword': kw, 'frequency': freq}
                for kw, freq in negative_cooccur.most_common(50)
                if kw not in known_negative and freq >= min_cooccurrence
            ]
            
            return {
                'positive': positive_new,
                'negative': negative_new
            }
            
        finally:
            conn.close()
    
    def analyze_misclassified_news(self) -> List[Dict]:
        """
        Phân tích các tin tức bị phân loại sai
        Giúp hiểu nơi model đang weak
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get significantly misclassified items
            cursor.execute("""
                SELECT 
                    news_title,
                    predicted_score,
                    predicted_label,
                    user_score,
                    user_label,
                    ABS(user_score - predicted_score) as error
                FROM sentiment_feedback
                WHERE ABS(user_score - predicted_score) > 0.4
                ORDER BY error DESC
                LIMIT 50
            """)
            
            results = []
            for row in cursor.fetchall():
                title, pred_score, pred_label, user_score, user_label, error = row
                
                # Extract potential missing keywords
                ngrams = self.extract_ngrams(title, n=2) + self.extract_ngrams(title, n=3)
                
                results.append({
                    'title': title,
                    'predicted': {'score': pred_score, 'label': pred_label},
                    'actual': {'score': user_score, 'label': user_label},
                    'error': round(error, 3),
                    'potential_keywords': ngrams[:5]
                })
            
            return results
            
        finally:
            conn.close()
    
    def suggest_improvements(self) -> Dict:
        """
        Tổng hợp các gợi ý cải thiện lexicon
        """
        # Analyze sentiment patterns
        pattern_keywords = self.analyze_sentiment_patterns(days=30, min_frequency=3)
        
        # Analyze misclassified
        misclassified = self.analyze_misclassified_news()
        
        # Get current lexicon
        from src.utils.sentiment import _VI_POSITIVE, _VI_NEGATIVE
        
        # Find co-occurring
        cooccur = self.find_cooccurring_keywords(
            list(_VI_POSITIVE.keys()),
            list(_VI_NEGATIVE.keys()),
            days=30
        )
        
        return {
            'pattern_based': pattern_keywords,
            'cooccurrence_based': cooccur,
            'misclassified_samples': misclassified[:10],
            'summary': {
                'positive_candidates': len(pattern_keywords['positive']),
                'negative_candidates': len(pattern_keywords['negative']),
                'high_error_cases': len(misclassified)
            }
        }

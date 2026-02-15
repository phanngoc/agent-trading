#!/usr/bin/env python3
"""
Demo script - Test Sentiment Learning System

Demonstrates the complete workflow:
1. Initialize learning system
2. Add sample feedback
3. Extract keywords
4. Approve keywords
5. Test improved predictions
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.sentiment_learning import SentimentLearningManager, DynamicLexiconManager
from src.core.keyword_extractor import KeywordExtractor
from src.utils.sentiment import get_sentiment

print("="*60)
print("🎯 SENTIMENT LEARNING SYSTEM - DEMO")
print("="*60)

# Initialize
db_path = os.path.join("output", "trend_news.db")
print(f"\n📁 Database: {db_path}")

learning_mgr = SentimentLearningManager(db_path)
lexicon_mgr = DynamicLexiconManager(learning_mgr)
extractor = KeywordExtractor(db_path)

print("✅ Managers initialized")

# ============================================================================
# STEP 1: Test original sentiment
# ============================================================================
print("\n" + "="*60)
print("STEP 1: Test Original Predictions")
print("="*60)

test_cases = [
    "Giá vàng SJC tăng vọt lên mức cao kỷ lục",
    "Chứng khoán đỏ sàn, nhà đầu tư hoảng loạn",
    "Bitcoin lao dốc không phanh, thị trường crypto khủng hoảng",
    "VN-Index bứt phá mạnh mẽ, cổ phiếu ngân hàng khởi sắc",
]

print("\nTesting current model:")
for title in test_cases:
    score, label = get_sentiment(title)
    print(f"\n📰 {title}")
    print(f"   Score: {score:.3f} | Label: {label}")

# ============================================================================
# STEP 2: Add sample feedback
# ============================================================================
print("\n" + "="*60)
print("STEP 2: Add Sample Feedback")
print("="*60)

feedback_samples = [
    {
        "title": "Giá vàng SJC tăng vọt lên mức cao kỷ lục",
        "user_score": 0.8,
        "user_label": "Bullish"
    },
    {
        "title": "Bitcoin lao dốc không phanh, thị trường khủng hoảng",
        "user_score": -0.7,
        "user_label": "Bearish"
    },
    {
        "title": "VN-Index bứt phá mạnh mẽ, cổ phiếu khởi sắc",
        "user_score": 0.7,
        "user_label": "Bullish"
    }
]

print("\nAdding feedback...")
for sample in feedback_samples:
    pred_score, pred_label = get_sentiment(sample["title"])
    
    feedback_id = learning_mgr.add_feedback(
        news_title=sample["title"],
        predicted_score=pred_score,
        predicted_label=pred_label,
        user_score=sample["user_score"],
        user_label=sample["user_label"]
    )
    
    error = abs(sample["user_score"] - pred_score)
    print(f"\n✅ Feedback #{feedback_id}")
    print(f"   Title: {sample['title'][:50]}...")
    print(f"   Predicted: {pred_score:.2f} → User: {sample['user_score']:.2f}")
    print(f"   Error: {error:.2f}")

# ============================================================================
# STEP 3: Extract keywords
# ============================================================================
print("\n" + "="*60)
print("STEP 3: Extract Keywords from Feedback")
print("="*60)

print("\nAnalyzing patterns...")
patterns = extractor.analyze_sentiment_patterns(days=30, min_frequency=1)

print(f"\n🟢 Positive Keywords Found: {len(patterns['positive'])}")
for item in patterns['positive'][:5]:
    print(f"   • {item['keyword']} (freq: {item['frequency']}, weight: {item['suggested_weight']:.2f})")

print(f"\n🔴 Negative Keywords Found: {len(patterns['negative'])}")
for item in patterns['negative'][:5]:
    print(f"   • {item['keyword']} (freq: {item['frequency']}, weight: {item['suggested_weight']:.2f})")

# ============================================================================
# STEP 4: Auto-approve some keywords
# ============================================================================
print("\n" + "="*60)
print("STEP 4: Approve Keywords")
print("="*60)

# Approve top keywords automatically for demo
approved_count = 0

print("\nApproving positive keywords...")
for item in patterns['positive'][:3]:
    if learning_mgr.approve_keyword(item['keyword'], 'positive', item['suggested_weight']):
        print(f"   ✅ {item['keyword']} → weight: {item['suggested_weight']:.2f}")
        approved_count += 1

print("\nApproving negative keywords...")
for item in patterns['negative'][:3]:
    if learning_mgr.approve_keyword(item['keyword'], 'negative', item['suggested_weight']):
        print(f"   ✅ {item['keyword']} → weight: {item['suggested_weight']:.2f}")
        approved_count += 1

print(f"\n📊 Total approved: {approved_count} keywords")

# Refresh cache
lexicon_mgr.refresh_cache()
print("♻️  Lexicon cache refreshed")

# ============================================================================
# STEP 5: View statistics
# ============================================================================
print("\n" + "="*60)
print("STEP 5: View Statistics")
print("="*60)

stats = learning_mgr.get_feedback_stats(days=7)
print(f"""
📊 Performance Metrics (7 days):
   • Total Feedback: {stats['total_feedback']}
   • Accurate Predictions: {stats['accurate_predictions']}
   • Accuracy Rate: {stats['accuracy_rate']}%
   • Average Error: {stats['avg_error']}
""")

learned = learning_mgr.get_approved_keywords()
print(f"""
📚 Lexicon Status:
   • Learned Positive: {len(learned['positive'])}
   • Learned Negative: {len(learned['negative'])}
   • Total Learned: {len(learned['positive']) + len(learned['negative'])}
""")

# ============================================================================
# STEP 6: Test new predictions (with learned keywords)
# ============================================================================
print("\n" + "="*60)
print("STEP 6: Re-test with Updated Lexicon")
print("="*60)

print("\nNote: New predictions may differ if learned keywords match.")
print("For significant improvements, more feedback data is needed.\n")

for title in test_cases:
    score, label = get_sentiment(title)
    print(f"📰 {title[:60]}...")
    print(f"   Score: {score:.3f} | Label: {label}")
    print()

# ============================================================================
# SUMMARY
# ============================================================================
print("="*60)
print("✅ DEMO COMPLETE")
print("="*60)

print("""
Next Steps:
1. Launch Dashboard: ./start_dashboard.sh
2. Add more feedback through UI
3. Review & approve suggested keywords
4. Monitor accuracy improvements

API Endpoints:
• Dashboard: http://localhost:8501
• API Docs: http://localhost:8000/docs
• Feedback: POST /api/v1/feedback
• Keywords: GET /api/v1/keywords/suggestions
""")

print("\n🎯 Sentiment Learning System is ready to use!")
print("="*60)

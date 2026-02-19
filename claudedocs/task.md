Refactor để đưa sản phẩm lên production, cần batch tính toán lưu score vào DB, tới API chỉ cần load ra.

## Task:

Cần tạo ra 1 pipeline.
1. Batch đầu tiên sẽ fetch news (đã có chính là trend_news/main.py)
2. Batch thứ 2 sẽ chạy llm [### Flow 5: LLM Batch Evaluator (Autonomous labeling)] , mục đích để nhận được feedback của llm cho việc cải thiện keyword_suggestion => giúp tăng tính chính xác của lexicon sentiment 
3. Batch thứ 3 sẽ tính toán sentiment cho các bài viêt mới (dựa trên _get_auto_learned_lexicons)


Cần refactor lại server.py để API lấy sentiment từ column lưu ở batch thứ 3.
---

Code reference:

```python
def _get_auto_learned_lexicons() -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
    """
    Load auto-aggregated lexicons from keyword_suggestions (no manual approval needed).
    Returns (pos, neg) with auto-calculated weights based on frequency and consensus.
    """
    global _auto_learned_cache, _auto_learned_cache_ts
    now = time.monotonic()
    if _auto_learned_cache is not None and (now - _auto_learned_cache_ts) < _AUTO_LEARNED_CACHE_TTL:
        return _auto_learned_cache

    try:
        from src.core.sentiment_learning import SentimentLearningManager
        manager = SentimentLearningManager()
        
        # Get auto-aggregated keywords (frequency-based, no manual approval)
        auto_keywords = manager.get_auto_aggregated_keywords(
            min_confidence=0.3,   # Ngưỡng confidence
            min_frequency=2,      # Xuất hiện ít nhất 2 lần
            lookback_days=30      # Trong 30 ngày gần nhất
        )
        
        pos: List[Tuple[str, float]] = []
        neg: List[Tuple[str, float]] = []
```

---

```python
    feed_items = []
    for item in raw_news:
        # Transform DB item to Alpha Vantage style NewsItem
        source_id = item.get("source_id", "Unknown")
        title = item.get("title", "")
        
        # Calculate sentiment on the fly (Level 2 Solution)
        # In a production environment, this should be pre-calculated and stored in DB
        sentiment_score, sentiment_label = get_sentiment(title)
        
        news_item = NewsItem(
            title=title,
            url=item.get("url", ""),
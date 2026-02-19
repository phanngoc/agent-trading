# Architecture: TrendNews Sentiment Analysis System

> Tài liệu này mô tả kiến trúc và luồng hoạt động của hệ thống `trend_news/` — một pipeline thu thập, phân tích cảm xúc (sentiment), học từ phản hồi, và thông báo tin tức tài chính Việt Nam.

---

## 1. Tổng quan hệ thống

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        TREND NEWS SYSTEM                                │
│                                                                         │
│  [Scrapers] → [DB] → [Sentiment] → [Labeling Queue] → [Learning Loop]  │
│                                          ↑                    ↓         │
│                               [Dashboard UI]        [LLM Evaluator]    │
│                                                                         │
│  [Notifiers] ← [Push Manager] ← [Processed News]                       │
└─────────────────────────────────────────────────────────────────────────┘
```

**Tech stack:**
- Python 3.12, SQLite (`output/trend_news.db`)
- Streamlit (dashboard)
- underthesea (NLP tiếng Việt, optional)
- LangChain + Anthropic/OpenAI (LLM evaluation, optional)
- fasttext (ML model, optional)

---

## 2. Sơ đồ module

```
trend_news/
├── main.py                        # Entry point → NewsAnalyzer
├── sentiment_dashboard.py         # Streamlit dashboard (admin UI)
└── src/
    ├── scrapers/                  # Thu thập dữ liệu từ các nguồn báo
    │   ├── base_scraper.py        # BaseScraper (abstract)
    │   ├── vnexpress_scraper.py
    │   ├── cafef_scraper.py
    │   ├── tinnhanhchungkhoan_scraper.py
    │   ├── vietnamfinance_scraper.py
    │   ├── vneconomy_scraper.py
    │   ├── baodautu_scraper.py
    │   ├── money24h_scraper.py
    │   ├── dantri_scraper.py
    │   └── vietnambiz_scraper.py
    ├── core/
    │   ├── vietnam_fetcher.py     # Orchestrates all scrapers
    │   ├── database.py            # DatabaseManager (SQLite CRUD)
    │   ├── analyzer.py            # NewsAnalyzer (main orchestrator)
    │   ├── labeling_pipeline.py   # Uncertainty scoring + labeling queue
    │   ├── sentiment_learning.py  # Learning loop từ admin feedback
    │   ├── keyword_extractor.py   # Phân tích n-gram, tìm từ khóa mới
    │   ├── llm_sentiment_evaluator.py  # Batch LLM evaluation
    │   ├── push_manager.py        # Quản lý lịch sử push notification
    │   └── ticker_mapper.py       # Map tin tức → mã cổ phiếu
    ├── utils/
    │   ├── sentiment.py           # SentimentAnalyzer singleton
    │   ├── text_utils.py
    │   ├── time_utils.py
    │   └── format_utils.py
    ├── processors/
    │   ├── data_processor.py
    │   ├── report_processor.py
    │   ├── frequency_words.py
    │   └── statistics.py
    ├── renderers/
    │   ├── base.py
    │   ├── html_renderer.py
    │   └── telegram_renderer.py
    └── notifiers/
        ├── base.py
        ├── telegram.py
        ├── email.py
        └── manager.py
```

---

## 3. Database Schema

```
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│   news_articles      │     │   labeling_queue     │     │ sentiment_feedback   │
├──────────────────────┤     ├──────────────────────┤     ├──────────────────────┤
│ id (PK)              │◄────┤ news_id (FK)         │     │ id (PK)              │
│ source_id            │     │ news_title           │────►│ news_title           │
│ title                │     │ news_url             │     │ news_id (FK)         │
│ url / mobile_url     │     │ crawl_date           │     │ predicted_score      │
│ ranks                │     │ lexicon_score        │     │ predicted_label      │
│ crawled_at           │     │ uts_label            │     │ user_score           │
│ crawl_date           │     │ final_score          │     │ user_label           │
│ sentiment_score      │     │ final_label          │     │ user_comment         │
│ sentiment_label      │     │ uncertainty_score    │     │ created_at           │
└──────────────────────┘     │ signal_conflict      │     └──────────────────────┘
                             │ magnitude_uncertainty│              │
   UNIQUE(source_id,         │ match_sparsity       │              ▼
          title,             │ queue_date           │     ┌──────────────────────┐
          crawl_date)        │ status               │     │ keyword_suggestions  │
                             │ admin_score          │     ├──────────────────────┤
                             │ admin_label          │     │ id (PK)              │
                             │ feedback_id (FK)     │     │ keyword              │
                             │ priority_rank        │     │ sentiment_type       │
                             └──────────────────────┘     │ suggested_weight     │
                                                          │ reviewed             │
                                                          └──────────┬───────────┘
                                                                     │ approve
                                                                     ▼
                             ┌──────────────────────┐     ┌──────────────────────┐
                             │ sentiment_llm_       │     │  learned_keywords    │
                             │ evaluations          │     ├──────────────────────┤
                             ├──────────────────────┤     │ id (PK)              │
                             │ id (PK)              │     │ keyword (UNIQUE)      │
                             │ news_id              │     │ sentiment_type        │
                             │ title                │     │ weight               │
                             │ llm_score            │     │ status ('approved')  │
                             │ llm_label            │     └──────────────────────┘
                             │ confidence           │
                             │ synced_to_feedback   │
                             └──────────────────────┘
```

---

## 4. Luồng hoạt động chính

### Flow 1: Thu thập tin tức (Crawling)

```
main.py → NewsAnalyzer.run()
              │
              ▼
    VietnamDataFetcher.fetch_data(source_id)
              │
              ├─► VnExpressScraper.fetch()     ┐
              ├─► CafeFScraper.fetch()         │
              ├─► TinnhanhScraper.fetch()      │ BaseScraper interface:
              ├─► VietnamFinanceScraper.fetch()│ - get_url()
              ├─► VnEconomyScraper.fetch()     │ - parse_articles()
              ├─► BaodautuScraper.fetch()      │ - fetch() → {status, items[]}
              ├─► Money24hScraper.fetch()      │
              └─► ...                          ┘
              │
              ▼
    DatabaseManager.save_news(results, id_to_name)
              │
              ├─ INSERT OR IGNORE INTO news_articles
              │  (dedup by UNIQUE(source_id, title, crawl_date))
              └─ Returns: số bài mới được insert
```

**Retry logic:** Mỗi scraper được retry tối đa 2 lần với random wait 3–5 giây.

---

### Flow 2: Phân tích sentiment (Real-time scoring)

```
Bài báo (title text)
        │
        ▼
SentimentAnalyzer.analyze(text)          [singleton, src/utils/sentiment.py]
        │
        ├─ Detect language
        │     ├─ Vietnamese? → _score_vietnamese(text)
        │     │                     │
        │     │     ┌───────────────┴────────────────┐
        │     │     │                                │
        │     │   lexicon_score()            underthesea.sentiment()
        │     │   (VI_POS + auto-learned     (optional, "positive"/
        │     │    VI_NEG + auto-learned)     "negative")
        │     │     │                                │
        │     │     └──── blend: 70% lexicon + 30% underthesea ────┘
        │     │
        │     └─ English? → VADER.polarity_scores(text)["compound"]
        │
        ▼
  (score: float [-1.0, 1.0], label: "Positive"/"Negative"/"Neutral")
```

**Lexicon hierarchy (ưu tiên cao → thấp):**
1. Static Vietnamese lexicon (`_VI_POS_LEXICON`, `_VI_NEG_LEXICON`)
2. Auto-learned keywords từ `keyword_suggestions` (không cần approve)
3. Approved keywords từ `learned_keywords`
4. underthesea direction (nếu available)

---

### Flow 3: Labeling Pipeline (Human-in-the-loop)

```
Admin clicks "Build Queue"
        │
        ▼
LabelingPipeline.build_daily_queue(date, limit=25)
        │
        ├─ Lấy tất cả bài của ngày hôm đó từ news_articles
        ├─ Bỏ qua bài đã có trong labeling_queue
        │
        ▼
  score_article_uncertainty(title) cho mỗi bài
        │
        ├─ lexicon_score: Raw VI lexicon score
        ├─ uts_label: underthesea prediction
        ├─ final_score/label: get_sentiment()
        ├─ hit_count: số keyword match
        │
        ├─ signal_conflict    = disagreement giữa lexicon và underthesea
        ├─ magnitude_uncertainty = |score| gần 0 (vùng mơ hồ)
        ├─ match_sparsity     = ít keyword match → kém tin cậy
        └─ fasttext_conflict  = (nếu có model fasttext)
        │
        ▼
  uncertainty_score = weighted sum:
    Không có fasttext: 0.45 × signal_conflict
                     + 0.30 × magnitude_uncertainty
                     + 0.25 × match_sparsity
    Có fasttext:      0.35 × signal_conflict
                     + 0.25 × magnitude_uncertainty
                     + 0.20 × match_sparsity
                     + 0.20 × fasttext_conflict
        │
        ▼
  Sort giảm dần → Lấy top 25 → INSERT INTO labeling_queue (status='pending')
        │
        ▼
Admin review trên Dashboard
        │
        ▼
LabelingPipeline.submit_label(queue_id, user_score, user_label, comment)
        │
        ├─ Gọi SentimentLearningManager.add_feedback(...)
        │         └─ INSERT INTO sentiment_feedback
        │         └─ Nếu |user_score - predicted_score| > 0.3:
        │              → _extract_keywords_from_feedback() (auto n-gram extraction)
        │
        └─ UPDATE labeling_queue SET status='labeled', admin_score=?, admin_label=?
```

---

### Flow 4: Learning Loop (Keyword Learning)

```
sentiment_feedback có diff lớn (|user - predicted| > 0.3)
        │
        ▼
_extract_keywords_from_feedback(feedback_id, title, user_score, user_label)
        │
        ├─ Tách words từ title
        ├─ Tạo bigrams và trigrams
        └─ INSERT OR IGNORE INTO keyword_suggestions
              (keyword, sentiment_type, suggested_weight = |user_score|)
        │
        ▼
[Auto-aggregation — KHÔNG cần admin approve]
get_auto_aggregated_keywords(min_confidence=0.3, min_frequency=2, lookback_days=30)
        │
        ├─ GROUP BY (keyword, sentiment_type)
        ├─ confidence = min(1.0, freq/10) × min(1.0, max_cooccur/5)
        ├─ weight = min(0.8, avg_weight × (0.5 + confidence × 0.5))
        └─ Filter: freq >= 2 AND confidence >= 0.3
        │
        ▼
_get_auto_learned_lexicons() [5-min cache]
        │
        ▼
_score_vietnamese() → merged lexicon (static + auto-learned)
→ Sentiment score cải thiện dần theo thời gian

[Admin tùy chọn]
Dashboard → "Review & Remove" tab
        └─ Xóa keyword xấu → reject_keyword() → reviewed=1
           (keyword bị loại khỏi aggregation)
```

---

### Flow 5: LLM Batch Evaluator (Autonomous labeling)

```
LLMSentimentEvaluator.evaluate_high_uncertainty_articles(
    days_back=7, min_uncertainty=threshold, limit=100
)
        │
        ▼
_fetch_high_uncertainty_articles()
    → SELECT từ labeling_queue WHERE uncertainty_score >= threshold
      AND chưa được LLM evaluate
        │
        ▼
evaluate_batch(articles)
    → Group thành batches (mặc định 15 bài/batch)
    → Gọi LLM (Claude Haiku / GPT-3.5) với batch prompt
    → _parse_llm_response() → danh sách LLMEvaluation
    → _persist_evaluations() → INSERT INTO sentiment_llm_evaluations
        │
        ▼
sync_llm_feedback_to_learning(min_confidence=0.6)
    → Lấy rows từ sentiment_llm_evaluations WHERE confidence >= 0.6
      AND synced_to_feedback = 0
    → INSERT INTO sentiment_feedback (LLM đóng vai trò "annotator")
    → UPDATE synced_to_feedback = 1
        │
        ▼
Learning loop tiếp tục như Flow 4 ↑
```

---

### Flow 6: Notification

```
PushRecordManager.has_pushed_today(source)
        │
        ├─ True → Skip (tránh gửi trùng)
        └─ False →
                │
                ▼
           send_to_notifications(news_data)
                │
                ├─► TelegramNotifier.send(message)
                └─► EmailNotifier.send(message)
                │
                ▼
           PushRecordManager.record_push(source)
```

---

## 5. Dashboard (sentiment_dashboard.py)

Dashboard được xây bằng **Streamlit**, có 3 tab chính:

```
┌─────────────────────────────────────────────────────────┐
│  SENTIMENT LEARNING DASHBOARD                           │
├─────────────┬───────────────────────┬───────────────────┤
│ Tab 1:      │ Tab 2:                │ Tab 3:            │
│ Labeling    │ Keyword Review        │ Analytics         │
│ Queue       │                       │                   │
├─────────────┼───────────────────────┼───────────────────┤
│ - Chọn ngày │ - Danh sách pending   │ - Sentiment stats │
│ - Build     │   keyword_suggestions │ - Accuracy chart  │
│   queue     │ - Approve/Reject      │ - Misclassified   │
│ - Xem stats │ - Xem learned_kw      │   articles        │
│ - Review    │ - KW Extractor tab    │ - Test analyzer   │
│   articles  │                       │                   │
│ - Submit    │                       │                   │
│   label     │                       │                   │
└─────────────┴───────────────────────┴───────────────────┘
```

**Khởi chạy:**
```bash
streamlit run trend_news/sentiment_dashboard.py
```

---

## 6. Dependency Graph (runtime)

```
main.py
  └── NewsAnalyzer
        ├── VietnamDataFetcher
        │     └── [*Scraper instances]  (BaseScraper subclasses)
        ├── DatabaseManager
        │     └── SQLite: output/trend_news.db
        └── (Notification pipeline)
              ├── PushRecordManager
              └── send_to_notifications → TelegramNotifier / EmailNotifier

sentiment_dashboard.py
  ├── LabelingPipeline
  │     ├── SentimentLearningManager  ← add_feedback, approve_keyword
  │     └── SentimentAnalyzer         ← get_sentiment() [singleton]
  ├── DynamicLexiconManager           ← get_combined_lexicon()
  ├── KeywordExtractor                ← suggest_improvements()
  └── LLMSentimentEvaluator           ← evaluate_high_uncertainty_articles()

SentimentAnalyzer (singleton)
  ├── _score_vietnamese()
  │     ├── _VI_POS_LEXICON / _VI_NEG_LEXICON   (static)
  │     ├── _get_auto_learned_lexicons()          (keyword_suggestions table)
  │     ├── _get_learned_lexicons()               (learned_keywords table)
  │     └── underthesea.sentiment()               (optional)
  └── VADER                                        (English, optional)
```

---

## 7. Configuration

```
trend_news/
├── config/
│   ├── settings.yaml / config.yaml    # API keys, thresholds, sources
│   └── frequency_words.txt            # Stop words tiếng Việt
├── .env                               # TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, etc.
└── output/
    └── trend_news.db                  # SQLite database (auto-created)
```

Các env vars quan trọng:
| Biến | Mô tả |
|------|--------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Channel/chat ID |
| `ANTHROPIC_API_KEY` | Claude API (LLM evaluator) |
| `OPENAI_API_KEY` | GPT fallback (LLM evaluator) |

---

## 8. Startup Sequence

```
1. python main.py                    # Chạy crawl pipeline
   └─ NewsAnalyzer.__init__()
   └─ NewsAnalyzer.run()
       └─ VietnamDataFetcher → crawl all sources
       └─ DatabaseManager.save_news()

2. streamlit run sentiment_dashboard.py   # Admin dashboard
   └─ get_managers()                       # Khởi tạo shared managers
   └─ Render tab 1/2/3

3. (Optional) LLMSentimentEvaluator
   └─ evaluate_high_uncertainty_articles()  # Có thể chạy theo schedule
   └─ sync_llm_feedback_to_learning()
```

---

## 9. Key Design Decisions

| Quyết định | Lý do |
|-----------|-------|
| SQLite thay vì Postgres | Đơn giản, không cần server, phù hợp scale hiện tại |
| INSERT OR IGNORE dedup | Tránh trùng bài cùng source + title + ngày |
| Uncertainty-first labeling | Ưu tiên bài khó phân loại → tối đa ROI của effort labeling |
| Auto n-gram extraction | Tự động mở rộng từ điển mà không cần con người tự gõ |
| LLM batch (15 bài/call) | Giảm chi phí API call, tận dụng context window |
| Graceful degradation | underthesea / fasttext / LangChain đều optional → chạy được mà không cần cài |
| Singleton SentimentAnalyzer | Tránh reload model nhiều lần, cache lexicon |
| Zero-approval keyword learning | keyword_suggestions auto-aggregated bằng frequency + confidence, không cần admin approve; admin chỉ cần xóa keyword xấu |

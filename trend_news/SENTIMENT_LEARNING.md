# Sentiment Learning System

## 🎯 Tổng quan

Hệ thống học sentiment tự động cải thiện độ chính xác phân tích cảm xúc tin tức dựa trên:

1. **Feedback từ người dùng** - Học từ đánh giá thực tế
2. **Data mining** - Tự động phát hiện từ khóa mới từ database
3. **Dynamic lexicon** - Từ điển động cập nhật theo thời gian
4. **Streamlit UI** - Giao diện quản lý trực quan

## 📁 Cấu trúc mới

```
trend_news/
├── src/
│   └── core/
│       ├── sentiment_learning.py    # Learning system core
│       └── keyword_extractor.py     # Keyword mining engine
├── sentiment_dashboard.py           # Streamlit UI
├── start_dashboard.sh               # Launch script
└── server.py                        # API (đã cập nhật)
```

## 🚀 Khởi động nhanh

### 1. Cài đặt dependencies

```bash
cd trend_news
pip install -r requirements.txt
```

### 2. Khởi chạy Dashboard

```bash
chmod +x start_dashboard.sh
./start_dashboard.sh
```

Hoặc trực tiếp:

```bash
streamlit run sentiment_dashboard.py
```

Dashboard sẽ mở tại: **http://localhost:8501**

### 3. Khởi chạy API Server (optional)

```bash
python server.py
```

API sẽ chạy tại: **http://localhost:8000**

## 📊 Các tính năng chính

### 1. **Dashboard** 📊
- Thống kê độ chính xác theo thời gian
- Xem lexicon hiện tại (static + learned)
- Gợi ý cải thiện nhanh

### 2. **Feedback Management** 💬
- Thêm feedback cho predictions
- Xem lịch sử feedback
- Hệ thống tự động trích xuất keywords từ feedback có sai số lớn

### 3. **Keyword Management** 🔤
- **Auto-extracted**: Từ khóa được phát hiện tự động từ patterns
- **Manual Add**: Thêm từ khóa thủ công
- **Review & Approve**: Duyệt từ khóa trước khi thêm vào lexicon

### 4. **Analytics** 📈
- Biểu đồ accuracy trends
- Phân tích cases bị misclassified
- Identify weak points

### 5. **Test Sentiment** 🧪
- Test real-time với custom text
- Visual gauge presentation
- Quick feedback submission

## 🔌 API Endpoints mới

### Feedback

```bash
# Submit feedback
POST /api/v1/feedback
{
  "news_title": "string",
  "predicted_score": 0.5,
  "predicted_label": "Bullish",
  "user_score": 0.8,
  "user_label": "Bullish"
}

# Get statistics
GET /api/v1/feedback/stats?days=7
```

### Keywords

```bash
# Get suggestions
GET /api/v1/keywords/suggestions?days=30&min_frequency=3

# Approve keyword
POST /api/v1/keywords/approve
{
  "keyword": "tăng vọt",
  "sentiment_type": "positive",
  "weight": 0.7
}

# Get approved keywords
GET /api/v1/keywords/approved

# Get combined lexicon
GET /api/v1/lexicon/combined
```

### Analysis

```bash
# Get improvement suggestions
GET /api/v1/analysis/improvements
```

## 💾 Database Schema mới

### `sentiment_feedback`
Lưu feedback từ người dùng
```sql
CREATE TABLE sentiment_feedback (
    id INTEGER PRIMARY KEY,
    news_title TEXT,
    predicted_score REAL,
    predicted_label TEXT,
    user_score REAL,
    user_label TEXT,
    user_comment TEXT,
    created_at TIMESTAMP
)
```

### `learned_keywords`
Từ khóa được học và approved
```sql
CREATE TABLE learned_keywords (
    id INTEGER PRIMARY KEY,
    keyword TEXT UNIQUE,
    sentiment_type TEXT,
    weight REAL,
    confidence REAL,
    frequency INTEGER,
    status TEXT,  -- 'pending', 'approved', 'rejected'
    last_seen TIMESTAMP
)
```

### `keyword_suggestions`
Suggestions chờ review
```sql
CREATE TABLE keyword_suggestions (
    id INTEGER PRIMARY KEY,
    keyword TEXT,
    sentiment_type TEXT,
    suggested_weight REAL,
    co_occurrence_count INTEGER,
    supporting_titles TEXT,  -- JSON
    reviewed BOOLEAN
)
```

## 🔄 Workflow học tập

```
1. User submits feedback
   ↓
2. System calculates error
   ↓
3. If error > 0.3:
   → Auto extract keywords from title
   → Save to keyword_suggestions
   ↓
4. Keyword Extractor analyzes patterns
   → Find frequent n-grams
   → Co-occurrence analysis
   ↓
5. Admin reviews in UI
   → Approve/Reject keywords
   ↓
6. Approved keywords → learned_keywords
   ↓
7. Dynamic lexicon updates
   → Cache refreshes
   → Future predictions improve
```

## 📈 Cách sử dụng hiệu quả

### Giai đoạn 1: Thu thập feedback (1-2 tuần)
1. Test sentiment trên các tin tức thực
2. Submit feedback cho cases sai
3. Hệ thống tích lũy data

### Giai đoạn 2: Review keywords (hàng tuần)
1. Vào "Keyword Management"
2. Click "Analyze & Extract Keywords"
3. Review các suggestions
4. Approve những từ có ý nghĩa

### Giai đoạn 3: Monitor performance (liên tục)
1. Check "Analytics" tab
2. Theo dõi accuracy trends
3. Xem misclassified cases
4. Tiếp tục refine

## 🎨 Screenshots

### Dashboard
![Dashboard overview với stats và lexicon]

### Feedback Form
![Form submit feedback với prediction comparison]

### Keyword Management
![Keyword suggestions với examples và approve buttons]

### Analytics
![Charts showing accuracy trends và misclassification analysis]

## 🛠️ Customization

### Thay đổi thresholds

Trong `src/core/sentiment_learning.py`:

```python
# Thay đổi ngưỡng auto-extract
if abs(user_score - predicted_score) > 0.3:  # Mặc định 0.3
    self._extract_keywords_from_feedback(...)
```

### Thêm stop words

Trong `src/core/keyword_extractor.py`:

```python
self.stop_words = {
    'của', 'và', 'có', ...
    # Thêm stop words của bạn
}
```

### Điều chỉnh scoring thresholds

Trong `src/utils/sentiment.py`:

```python
def _score_to_label(compound: float) -> str:
    if compound <= -0.35:  # Điều chỉnh thresholds
        return "Bearish"
    # ...
```

## 🔒 Best Practices

1. **Regular reviews**: Review keyword suggestions ít nhất 1 lần/tuần
2. **Quality over quantity**: Chỉ approve keywords có ý nghĩa rõ ràng
3. **Monitor accuracy**: Theo dõi accuracy rate thường xuyên
4. **Diverse feedback**: Thu thập feedback từ nhiều types của news
5. **Backup lexicon**: Backup learned_keywords table định kỳ

## 🐛 Troubleshooting

### Dashboard không khởi động
```bash
# Kiểm tra Streamlit
pip install --upgrade streamlit

# Kiểm tra dependencies
pip install -r requirements.txt
```

### Database errors
```bash
# Reinitialize database
python3 -c "from src.core.sentiment_learning import SentimentLearningManager; SentimentLearningManager('output/trend_news.db')"
```

### Import errors
```bash
# Đảm bảo PYTHONPATH đúng
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

## 📚 Tài liệu API đầy đủ

Truy cập: **http://localhost:8000/docs** (khi server đang chạy)

FastAPI tự động generate interactive API documentation.

## 🤝 Contributing

Các cải tiến có thể thêm:

1. **Export/Import lexicon** - Chia sẻ learned keywords
2. **A/B testing** - So sánh versions
3. **Bulk feedback** - Upload CSV feedback
4. **Advanced analytics** - Confusion matrix, ROC curves
5. **Multi-user** - User authentication và roles

## 📞 Support

Có vấn đề? Check:
- Logs trong terminal
- FastAPI docs: `/docs`
- Streamlit logs trong browser console

---

**Version**: 1.0.0  
**Last Updated**: 2026-02-15

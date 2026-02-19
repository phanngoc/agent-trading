# TrendRadar API — Tài liệu định nghĩa các Endpoint

> **Base URL**: `http://localhost:8000`
> **Framework**: FastAPI
> **Docs tương tác**: `/docs` (Swagger UI) · `/redoc` (ReDoc)

---

## Mục lục

1. [Root](#1-root)
2. [Alpha Vantage Compatible](#2-alpha-vantage-compatible)
3. [Native API — News](#3-native-api--news)
4. [Sentiment Learning — Feedback](#4-sentiment-learning--feedback)
5. [Sentiment Learning — Keywords](#5-sentiment-learning--keywords)
6. [Sentiment Learning — Lexicon & Analysis](#6-sentiment-learning--lexicon--analysis)
7. [Labeling Queue](#7-labeling-queue)
8. [Data Models](#8-data-models)

---

## 1. Root

### `GET /`

Kiểm tra server hoạt động.

**Response**
```json
{ "message": "Welcome to TrendRadar API" }
```

---

## 2. Alpha Vantage Compatible

### `GET /query`

Endpoint tương thích định dạng Alpha Vantage `NEWS_SENTIMENT`. Trả về danh sách tin tức kèm điểm sentiment được tính real-time.

**Query Parameters**

| Tên | Kiểu | Bắt buộc | Mặc định | Mô tả |
|-----|------|----------|----------|-------|
| `function` | string | ✅ | — | Phải là `NEWS_SENTIMENT` |
| `tickers` | string | ❌ | — | Mã cổ phiếu (map sang tìm kiếm trong tiêu đề, e.g. `VIC`) |
| `topics` | string | ❌ | — | Chủ đề lọc |
| `time_from` | string | ❌ | — | Thời gian bắt đầu, định dạng `YYYYMMDDTHHMM` hoặc `YYYYMMDD` |
| `time_to` | string | ❌ | — | Thời gian kết thúc, định dạng `YYYYMMDDTHHMM` hoặc `YYYYMMDD` |
| `limit` | integer | ❌ | `50` | Số bản ghi tối đa |
| `apikey` | string | ❌ | — | API key (hiện tại bỏ qua) |

**Response** — `NewsSentimentResponse`

```json
{
  "items": "25",
  "sentiment_score_definition": "x <= -0.35: Bearish; -0.35 < x <= -0.15: Somewhat-Bearish; -0.15 < x < 0.15: Neutral; 0.15 <= x < 0.35: Somewhat-Bullish; x >= 0.35: Bullish",
  "relevance_score_definition": "0 < x <= 1: with a higher score indicating higher relevance.",
  "feed": [
    {
      "title": "...",
      "url": "...",
      "time_published": "20240115T0930",
      "summary": "Ranked: 1",
      "source": "cafef",
      "source_domain": "cafef",
      "topics": [],
      "overall_sentiment_score": 0.42,
      "overall_sentiment_label": "Bullish",
      "relevance_score": 1
    }
  ]
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `400` | `function` không phải `NEWS_SENTIMENT` |

---

## 3. Native API — News

### `GET /api/v1/news`

Lấy danh sách tin tức từ database với bộ lọc linh hoạt.

**Query Parameters**

| Tên | Kiểu | Bắt buộc | Mặc định | Mô tả |
|-----|------|----------|----------|-------|
| `start_date` | string | ❌ | — | Ngày bắt đầu, ISO format `YYYY-MM-DD` hoặc `YYYY-MM-DDTHH:MM:SS` |
| `end_date` | string | ❌ | — | Ngày kết thúc, ISO format |
| `source` | string | ❌ | — | Lọc theo `source_id` chính xác, e.g. `cafef`, `24hmoney` |
| `tickers` | string | ❌ | — | Comma-separated mã cổ phiếu, tìm theo alias trong tiêu đề, e.g. `VIC,HPG` |
| `limit` | integer | ❌ | `50` | Số bản ghi tối đa |

**Response** — Array các news object từ database

```json
[
  {
    "id": 123,
    "title": "Vingroup công bố kết quả kinh doanh...",
    "url": "https://...",
    "source_id": "cafef",
    "crawled_at": "2024-01-15T09:30:00",
    "ranks": "1",
    "relevance_score": 1
  }
]
```

---

## 4. Sentiment Learning — Feedback

### `POST /api/v1/feedback`

Ghi nhận phản hồi của người dùng về kết quả dự đoán sentiment, dùng để hệ thống học và cải thiện.

**Request Body** — `SentimentFeedback`

```json
{
  "news_title": "Cổ phiếu VIC tăng mạnh sau thông báo...",
  "predicted_score": 0.12,
  "predicted_label": "Neutral",
  "user_score": 0.45,
  "user_label": "Bullish",
  "news_id": 123,
  "news_url": "https://...",
  "comment": "Tin rõ ràng tích cực, nên là Bullish"
}
```

| Trường | Kiểu | Bắt buộc | Mô tả |
|--------|------|----------|-------|
| `news_title` | string | ✅ | Tiêu đề bài báo |
| `predicted_score` | float | ✅ | Điểm sentiment hệ thống dự đoán |
| `predicted_label` | string | ✅ | Nhãn sentiment hệ thống dự đoán |
| `user_score` | float | ✅ | Điểm sentiment người dùng chỉnh sửa |
| `user_label` | string | ✅ | Nhãn sentiment người dùng chỉnh sửa |
| `news_id` | integer | ❌ | ID bài báo trong DB |
| `news_url` | string | ❌ | URL bài báo |
| `comment` | string | ❌ | Ghi chú từ người dùng |

**Response**

```json
{
  "success": true,
  "feedback_id": 456,
  "message": "Feedback recorded successfully"
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server khi ghi feedback |

---

### `GET /api/v1/feedback/stats`

Lấy thống kê chất lượng dự đoán sentiment.

**Query Parameters**

| Tên | Kiểu | Mặc định | Mô tả |
|-----|------|----------|-------|
| `days` | integer | `7` | Số ngày nhìn lại |

**Response**

```json
{
  "total_feedback": 150,
  "accuracy": 0.72,
  "avg_error": 0.18,
  "label_distribution": {
    "Bullish": 45,
    "Bearish": 30,
    "Neutral": 75
  }
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

## 5. Sentiment Learning — Keywords

### `POST /api/v1/keywords/approve` ⚠️ DEPRECATED

> **410 Gone** — Endpoint này không còn hoạt động. Keywords hiện được kích hoạt tự động dựa trên tần suất và ngưỡng confidence từ `keyword_suggestions`.

---

### `GET /api/v1/keywords/suggestions`

Lấy danh sách từ khóa được gợi ý, trích xuất từ dữ liệu feedback.

**Query Parameters**

| Tên | Kiểu | Mặc định | Mô tả |
|-----|------|----------|-------|
| `days` | integer | `30` | Số ngày nhìn lại để phân tích |
| `min_frequency` | integer | `3` | Tần suất xuất hiện tối thiểu |
| `limit` | integer | `50` | Số gợi ý tối đa mỗi loại |

**Response**

```json
{
  "positive": [
    { "keyword": "tăng trưởng", "frequency": 12, "confidence": 0.85 }
  ],
  "negative": [
    { "keyword": "lỗ ròng", "frequency": 8, "confidence": 0.91 }
  ]
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

### `GET /api/v1/keywords/approved`

Lấy danh sách từ khóa đã được kích hoạt tự động (tổng hợp từ `keyword_suggestions`).

**Không có query parameters**

**Response**

```json
{
  "positive": [
    { "keyword": "lợi nhuận", "weight": 0.7 }
  ],
  "negative": [
    { "keyword": "thua lỗ", "weight": -0.8 }
  ]
}
```

> Ngưỡng kích hoạt: `min_confidence=0.3`, `min_frequency=2`, `lookback_days=30`

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

## 6. Sentiment Learning — Lexicon & Analysis

### `GET /api/v1/lexicon/combined`

Lấy từ điển sentiment kết hợp (static + tự động học từ `keyword_suggestions`).

**Không có query parameters**

**Response**

```json
{
  "positive": [{ "keyword": "tăng trưởng", "weight": 0.7 }],
  "negative": [{ "keyword": "thua lỗ", "weight": -0.8 }],
  "total_positive": 320,
  "total_negative": 280
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

### `GET /api/v1/analysis/improvements`

Lấy gợi ý cải thiện toàn diện cho hệ thống sentiment.

**Không có query parameters**

**Response**

```json
{
  "suggestions": [
    "Thêm từ khóa cho lĩnh vực bất động sản",
    "Cải thiện nhận dạng tin tức trung lập"
  ],
  "priority_areas": ["real_estate", "banking"],
  "misclassification_patterns": [...]
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

## 7. Labeling Queue

### `POST /api/v1/labeling/build`

Chấm điểm các bài báo trong ngày và thêm top N bài có độ bất định cao nhất vào hàng đợi gán nhãn.

**Query Parameters**

| Tên | Kiểu | Mặc định | Ràng buộc | Mô tả |
|-----|------|----------|-----------|-------|
| `date` | string | Ngày hôm nay | ISO `YYYY-MM-DD` | Ngày cần xử lý |
| `limit` | integer | `25` | 1–100 | Số bài tối đa đưa vào queue |

**Response**

```json
{
  "total": 80,
  "inserted": 25,
  "already": 5,
  "limit": 25
}
```

| Trường | Mô tả |
|--------|-------|
| `total` | Tổng số bài được chấm điểm |
| `inserted` | Số bài mới được thêm vào queue |
| `already` | Số bài đã có trong queue (không thêm lại) |

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

### `GET /api/v1/labeling/queue`

Lấy danh sách các mục trong hàng đợi gán nhãn, sắp xếp theo `priority_rank`.

**Query Parameters**

| Tên | Kiểu | Mặc định | Mô tả |
|-----|------|----------|-------|
| `date` | string | Ngày hôm nay | Ngày cần xem, ISO `YYYY-MM-DD` |
| `status` | string | — | Lọc theo trạng thái: `pending` \| `labeled` \| `skipped` |

**Response**

```json
{
  "date": "2024-01-15",
  "count": 20,
  "items": [
    {
      "id": 1,
      "news_id": 123,
      "title": "...",
      "priority_rank": 1,
      "uncertainty_score": 0.85,
      "status": "pending",
      "lexicon_score": 0.05,
      "uts_label": "Neutral",
      "fasttext_label": "Positive"
    }
  ]
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

### `POST /api/v1/labeling/submit`

Gửi nhãn do admin gán cho một mục trong queue. Tự động tạo bản ghi trong `sentiment_feedback`.

**Request Body** — `LabelSubmission`

```json
{
  "queue_id": 1,
  "user_score": 0.5,
  "user_label": "Bullish",
  "comment": "Tin tức rõ ràng tích cực"
}
```

| Trường | Kiểu | Bắt buộc | Mô tả |
|--------|------|----------|-------|
| `queue_id` | integer | ✅ | ID của mục trong labeling queue |
| `user_score` | float | ✅ | Điểm sentiment của admin (-1.0 đến 1.0) |
| `user_label` | string | ✅ | Nhãn: `Bullish` / `Somewhat-Bullish` / `Neutral` / `Somewhat-Bearish` / `Bearish` |
| `comment` | string | ❌ | Ghi chú thêm |

**Response**

```json
{
  "success": true,
  "feedback_id": 789,
  "queue_id": 1
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `400` | Dữ liệu không hợp lệ (e.g. queue_id không tồn tại) |
| `500` | Lỗi server |

---

### `POST /api/v1/labeling/skip/{queue_id}`

Đánh dấu một mục trong queue là đã bỏ qua.

**Path Parameters**

| Tên | Kiểu | Mô tả |
|-----|------|-------|
| `queue_id` | integer | ID của mục cần bỏ qua |

**Response**

```json
{
  "success": true,
  "queue_id": 1,
  "status": "skipped"
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

### `GET /api/v1/labeling/stats`

Lấy thống kê tóm tắt của hàng đợi gán nhãn theo ngày.

**Query Parameters**

| Tên | Kiểu | Mặc định | Mô tả |
|-----|------|----------|-------|
| `date` | string | Ngày hôm nay | Ngày cần xem, ISO `YYYY-MM-DD` |

**Response**

```json
{
  "date": "2024-01-15",
  "total": 25,
  "pending": 10,
  "labeled": 12,
  "skipped": 3
}
```

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

### `GET /api/v1/labeling/score`

Debug endpoint: tính điểm bất định (uncertainty) cho một tiêu đề bài báo bất kỳ.

**Query Parameters**

| Tên | Kiểu | Bắt buộc | Mô tả |
|-----|------|----------|-------|
| `title` | string | ✅ | Tiêu đề bài báo cần chấm điểm |

**Response**

```json
{
  "title": "Cổ phiếu VIC tăng 3% sau thông báo...",
  "lexicon_score": 0.2,
  "uts_label": "Somewhat-Bullish",
  "final_score": 0.18,
  "final_label": "Somewhat-Bullish",
  "uncertainty_score": 0.72,
  "signal_conflict": true,
  "magnitude_uncertainty": 0.35,
  "match_sparsity": 0.6,
  "fasttext_label": "Neutral"
}
```

| Trường | Mô tả |
|--------|-------|
| `lexicon_score` | Điểm từ lexicon-based scorer |
| `uts_label` | Nhãn từ UTS model |
| `final_score` | Điểm sentiment cuối cùng |
| `final_label` | Nhãn cuối cùng |
| `uncertainty_score` | Mức độ bất định (0–1, càng cao càng không chắc) |
| `signal_conflict` | Có xung đột giữa các signal hay không |
| `magnitude_uncertainty` | Bất định về độ lớn |
| `match_sparsity` | Mật độ khớp từ khóa thấp |
| `fasttext_label` | Nhãn từ FastText model |

**Errors**

| Code | Mô tả |
|------|-------|
| `500` | Lỗi server |

---

## 8. Data Models

### `NewsItem`

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `title` | string | Tiêu đề bài báo |
| `url` | string | URL bài báo |
| `time_published` | string | Thời gian đăng (format `YYYYMMDDTHHMM`) |
| `summary` | string | Tóm tắt (mặc định hiển thị rank) |
| `banner_image` | string \| null | URL ảnh banner |
| `source` | string | ID nguồn (e.g. `cafef`) |
| `category_within_source` | string | Danh mục trong nguồn (mặc định `General`) |
| `source_domain` | string | Domain nguồn |
| `topics` | array[string] | Danh sách chủ đề |
| `overall_sentiment_score` | float | Điểm sentiment (-1.0 đến 1.0) |
| `overall_sentiment_label` | string | Nhãn: `Bearish` / `Somewhat-Bearish` / `Neutral` / `Somewhat-Bullish` / `Bullish` |
| `relevance_score` | integer | Điểm liên quan (0–1) |

### `SentimentFeedback`

| Trường | Kiểu | Bắt buộc | Mô tả |
|--------|------|----------|-------|
| `news_title` | string | ✅ | Tiêu đề bài báo |
| `predicted_score` | float | ✅ | Điểm hệ thống dự đoán |
| `predicted_label` | string | ✅ | Nhãn hệ thống dự đoán |
| `user_score` | float | ✅ | Điểm người dùng hiệu chỉnh |
| `user_label` | string | ✅ | Nhãn người dùng hiệu chỉnh |
| `news_id` | integer | ❌ | ID bài báo |
| `news_url` | string | ❌ | URL bài báo |
| `comment` | string | ❌ | Ghi chú |

### `LabelSubmission`

| Trường | Kiểu | Bắt buộc | Mô tả |
|--------|------|----------|-------|
| `queue_id` | integer | ✅ | ID mục trong labeling queue |
| `user_score` | float | ✅ | Điểm sentiment admin gán |
| `user_label` | string | ✅ | Nhãn admin gán |
| `comment` | string | ❌ | Ghi chú |

### `KeywordApproval` (Deprecated)

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `keyword` | string | Từ khóa |
| `sentiment_type` | string | `positive` hoặc `negative` |
| `weight` | float | Trọng số |

---

### Sentiment Score Reference

| Score | Label |
|-------|-------|
| `x >= 0.35` | **Bullish** |
| `0.15 <= x < 0.35` | **Somewhat-Bullish** |
| `-0.15 < x < 0.15` | **Neutral** |
| `-0.35 < x <= -0.15` | **Somewhat-Bearish** |
| `x <= -0.35` | **Bearish** |

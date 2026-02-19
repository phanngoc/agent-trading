# Cách hoạt động của FinancialSituationMemory

## Tổng quan
Module dùng thuật toán BM25 (Best Matching 25) — một giải thuật tìm kiếm văn bản cổ điển, không cần API, không cần embedding, chạy hoàn toàn offline.

## Cấu trúc dữ liệu

```
self.documents        = ["tình huống A", "tình huống B", ...]
self.recommendations  = ["lời khuyên A", "lời khuyên B", ...]
self.bm25             = BM25Okapi(index đã build)
Hai list documents và recommendations luôn song song theo index — documents[i] đi kèm recommendations[i].

Luồng hoạt động

1. add_situations()          2. get_memories()
   ─────────────────            ─────────────────────────
   (situation, advice) ──►      current_situation
         │                           │
         ▼                           ▼
   documents[].append()        _tokenize(query)
   recommendations[].append()       │
         │                           ▼
         ▼                      bm25.get_scores()  ← BM25 scoring
   _rebuild_index()                  │              tất cả documents
         │                           ▼
         ▼                      top-n indices
   BM25Okapi(tokenized_docs)         │
                                     ▼
                               trả về List[dict]
                               {matched_situation,
                                recommendation,
                                similarity_score}
```

## BM25 hoạt động như thế nào?

BM25 chấm điểm mức độ "liên quan" giữa query và mỗi document dựa trên tần suất từ (TF) có điều chỉnh theo độ dài tài liệu:

```
Score(D, Q) = Σ IDF(qᵢ) × [f(qᵢ,D) × (k1+1)] / [f(qᵢ,D) + k1×(1-b+b×|D|/avgdl)]
```

Đơn giản hơn: từ nào xuất hiện nhiều trong document ngắn → điểm cao hơn.

Ví dụ từ __main__:

```
# Query: "volatility in tech sector, rising interest rates"
# → Match document 2: "Tech sector showing high volatility..."  ✓ score cao
# → Match document 4: "rising yields..."                        ✓ score cao
```

Tokenizer đơn giản

```
def _tokenize(self, text):
    tokens = re.findall(r'\b\w+\b', text.lower())
    # "Tech Sector! Rising." → ["tech", "sector", "rising"]
```

Chỉ lowercase + tách từ, không loại stopwords, không stemming — phù hợp cho văn bản tài chính ngắn.

## Điểm cần chú ý
Điểm	Chi tiết
Index rebuild mỗi lần add	_rebuild_index() gọi lại BM25Okapi(...) toàn bộ sau mỗi add_situations(). Nếu gọi nhiều lần riêng lẻ với tập dữ liệu lớn thì chậm
Score normalize 0→1	Chia cho max(scores) để dễ so sánh, nhưng nếu tất cả scores = 0 (không có từ nào khớp) thì trả về 0
Không persistent	Bộ nhớ chỉ tồn tại trong RAM, mỗi lần khởi động lại phải add_situations() lại từ đầu
config param không dùng	Giữ lại để tương thích API cũ (trước đây có thể dùng vector embedding)
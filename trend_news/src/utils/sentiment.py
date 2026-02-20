"""
Sentiment analysis — Vietnamese (underthesea + lexicon) + Chinese (SnowNLP) + English (VADER).

Vietnamese pipeline:
  1. underthesea.sentiment() → "positive" | "negative"  (direction)
  2. _lexicon_score()        → float in [-1.0, 1.0]     (direction + magnitude)
  3. Combined float score in [-1.0, 1.0]

Chinese pipeline:
  SnowNLP.sentiments → P(positive) ∈ [0,1] → mapped to [-1,1]

Fallback chain: underthesea → lexicon-only → (0.0, "Neutral")
English: VADER → (0.0, "Neutral")

Public API (unchanged):
    get_sentiment(text: str) -> Tuple[float, str]
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# VADER — English sentiment (optional)
# ---------------------------------------------------------------------------
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
    _vader_available = True
except ImportError:
    _vader = None
    _vader_available = False

# ---------------------------------------------------------------------------
# ViVADER — Vietnamese VADER-inspired analyzer (local, zero external deps)
# ---------------------------------------------------------------------------
try:
    from src.utils.vivader import ViVADERSentimentAnalyzer
    _vivader = ViVADERSentimentAnalyzer()
    _vivader_available = True
except ImportError:
    try:
        from .vivader import ViVADERSentimentAnalyzer
        _vivader = ViVADERSentimentAnalyzer()
        _vivader_available = True
    except ImportError:
        _vivader = None  # type: ignore[assignment]
        _vivader_available = False

# ---------------------------------------------------------------------------
# SnowNLP — Chinese sentiment (optional)
# ---------------------------------------------------------------------------
try:
    from snownlp import SnowNLP as _SnowNLP
    _snownlp_available = True
except ImportError:
    _SnowNLP = None  # type: ignore[assignment, misc]
    _snownlp_available = False

# ---------------------------------------------------------------------------
# underthesea — Vietnamese sentiment direction (optional)
# ---------------------------------------------------------------------------
try:
    from underthesea import sentiment as _uts_sentiment
    _uts_available = True
except ImportError:
    _uts_sentiment = None
    _uts_available = False

# ---------------------------------------------------------------------------
# Vietnamese language detection — zero dependency, Unicode-based
# ---------------------------------------------------------------------------
_VI_UNIQUE_RE = re.compile(
    r'[àáâãèéêìíòóôõùúýăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ'
    r'ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯẠẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ]'
)


def _is_vietnamese(text: str) -> bool:
    """True nếu text chứa ký tự đặc trưng của tiếng Việt."""
    return bool(_VI_UNIQUE_RE.search(text))


# ---------------------------------------------------------------------------
# Chinese language detection — zero dependency, Unicode-based
# ---------------------------------------------------------------------------
_ZH_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')


def _is_chinese(text: str) -> bool:
    """True if text contains CJK Unified Ideographs (Chinese)."""
    return bool(_ZH_RE.search(text))


# ---------------------------------------------------------------------------
# Vietnamese financial lexicon — expanded from 45 → ~250 terms
# ---------------------------------------------------------------------------
_VI_POSITIVE: Dict[str, float] = {
    # Kỷ lục / vượt mục tiêu
    "kỷ lục": 0.8, "lập kỷ lục": 0.85, "phá kỷ lục": 0.85,
    "vượt kế hoạch": 0.75, "vượt mục tiêu": 0.75, "đạt mục tiêu": 0.65,
    "thắng thầu": 0.65, "trúng thầu": 0.65,

    # Tăng trưởng mạnh
    "tăng mạnh": 0.8, "bứt phá": 0.75, "đột phá": 0.75, "bullish": 0.7,
    "tăng vọt": 0.75, "tăng đột biến": 0.75, "leo thang tích cực": 0.65,

    # Phục hồi / khởi sắc
    "phục hồi mạnh": 0.7, "phục hồi": 0.6, "khởi sắc": 0.6,
    "uptrend": 0.6, "hồi phục": 0.55, "cải thiện": 0.5,

    # Hưởng lợi / lợi thế
    "hưởng lợi": 0.6, "tận dụng cơ hội": 0.55, "lợi thế cạnh tranh": 0.6,
    "ưu thế": 0.5, "thắng lợi": 0.65,

    # Tăng trưởng / doanh thu / lợi nhuận
    "tăng trưởng mạnh": 0.7, "tăng trưởng": 0.6, "tăng trưởng tốt": 0.65,
    "lãi ròng tăng": 0.7, "doanh thu tăng": 0.65, "lợi nhuận tăng": 0.7,
    "lợi nhuận cao kỷ lục": 0.85, "lợi nhuận": 0.5, "lãi": 0.5,

    # Cổ tức / chia thưởng
    "chia cổ tức": 0.6, "tăng cổ tức": 0.65, "thưởng cổ phiếu": 0.55,
    "mua lại cổ phiếu": 0.5,

    # Mở rộng / đầu tư
    "mở rộng": 0.55, "mở rộng quy mô": 0.6, "mở rộng thị trường": 0.6,
    "hợp đồng lớn": 0.65, "đầu tư mới": 0.55, "nâng hạng": 0.6,
    "nâng cấp": 0.45, "tái cơ cấu thành công": 0.6,

    # Dòng tiền / thanh khoản tốt
    "dòng tiền vào": 0.55, "ngoại tệ vào": 0.5, "mua ròng": 0.5,
    "thanh khoản tốt": 0.5, "thanh khoản cao": 0.5,

    # Thị trường / điểm số
    "điểm xanh": 0.5, "xanh": 0.4, "tích cực": 0.45,
    "tăng điểm": 0.5, "thị trường tích cực": 0.55,

    # Từ khóa tăng / lên / vượt
    "tăng": 0.45, "lên": 0.3, "vượt": 0.35, "kỳ vọng": 0.3,

    # Chất lượng / uy tín
    "được xếp hạng tốt": 0.55, "uy tín cao": 0.5, "chất lượng tốt": 0.5,
    "đánh giá cao": 0.55, "được vinh danh": 0.6, "nhận giải thưởng": 0.6,

    # Hợp tác / liên kết
    "hợp tác chiến lược": 0.55, "ký kết hợp đồng": 0.5,
    "bắt tay hợp tác": 0.45, "liên doanh": 0.45,

    # IPO / niêm yết
    "niêm yết thành công": 0.65, "ipo thành công": 0.65,
    "lên sàn": 0.5, "tăng vốn": 0.45,

    # Đỉnh cao
    "đỉnh": 0.5, "đỉnh lịch sử": 0.75, "cao nhất": 0.6, "cao kỷ lục": 0.75,
}

_VI_NEGATIVE: Dict[str, float] = {
    # Phàn nàn / yêu cầu / phản đối
    "kiến nghị khẩn": 0.55, "kiến nghị": 0.25, "kêu cứu": 0.6,
    "phản đối": 0.45, "khiếu nại": 0.4, "tố cáo": 0.5,
    "phàn nàn": 0.35, "chỉ trích": 0.4, "lên án": 0.5,
    "yêu cầu khẩn": 0.5, "đề nghị khẩn": 0.45,

    # Khẩn cấp / bức xúc / stress
    "khẩn cấp": 0.4, "khẩn": 0.3, "gấp": 0.25,
    "bức xúc": 0.45, "lo lắng": 0.35, "lo ngại": 0.4,
    "căng thẳng": 0.4, "hoang mang": 0.45, "bất an": 0.45,

    # Phá sản / vỡ nợ / khủng hoảng
    "phá sản": 0.9, "vỡ nợ": 0.85, "khủng hoảng": 0.8, "sụp đổ": 0.8,
    "mất vốn": 0.75, "âm vốn": 0.75, "mất thanh khoản": 0.8,
    "mất khả năng thanh toán": 0.85,

    # Lao dốc / giảm mạnh
    "lao dốc": 0.75, "giảm mạnh": 0.7, "giảm sâu": 0.7,
    "lao xuống": 0.7, "rơi tự do": 0.8, "bốc hơi": 0.65,
    "bốc hơi tỷ đồng": 0.75,

    # Thua lỗ / thất bại
    "thua lỗ": 0.65, "thất bại": 0.6, "lỗ nặng": 0.75,
    "lỗ lớn": 0.7, "lỗ": 0.55, "thua": 0.45,

    # Bán tháo / tháo chạy
    "bán tháo ròng": 0.65, "bán tháo": 0.65, "tháo chạy": 0.7,
    "tháo vốn": 0.65, "rút vốn": 0.5,

    # Bearish / downtrend
    "bearish": 0.65, "downtrend": 0.55, "xu hướng giảm": 0.55,

    # Nợ xấu / nợ
    "nợ xấu": 0.7, "nợ tăng": 0.5, "gánh nặng nợ": 0.65,
    "nợ quá hạn": 0.65, "nợ khó đòi": 0.65,

    # Thị trường xấu
    "giảm điểm": 0.5, "thanh khoản thấp": 0.45, "thanh khoản cạn": 0.55,
    "tiêu cực": 0.5, "điểm đỏ": 0.5, "đỏ sàn": 0.55,

    # Hoạt động kém / trì hoãn
    "trì hoãn": 0.4, "chậm tiến độ": 0.45, "dừng hoạt động": 0.6,
    "tạm dừng": 0.45, "đình trệ": 0.55, "ngừng hoạt động": 0.6,
    "tạm hoãn": 0.4, "chậm trễ": 0.4,

    # Chi phí / gánh nặng tài chính
    "chi phí tăng": 0.4, "giá điện tăng": 0.4, "thuế tăng": 0.35,
    "gánh nặng chi phí": 0.5, "áp lực chi phí": 0.45,
    "chi phí leo thang": 0.5,

    # Điều tra / vi phạm / xử phạt
    "bị điều tra": 0.6, "vi phạm": 0.55, "bị xử phạt": 0.55,
    "bị phạt": 0.5, "khởi tố": 0.7, "bắt giữ": 0.65,
    "bị bắt": 0.65, "tạm giam": 0.6,

    # Rủi ro / cảnh báo / áp lực
    "rủi ro cao": 0.55, "rủi ro": 0.4, "áp lực": 0.4,
    "cảnh báo": 0.4, "cảnh báo nghiêm trọng": 0.6,

    # Mất / thiệt hại
    "thiệt hại": 0.55, "thiệt hại nặng": 0.7, "mất mát": 0.5,
    "suy giảm": 0.45, "sụt giảm": 0.5, "sụt": 0.45,

    # Từ khóa giảm / khó / xấu
    "giảm": 0.4, "khó khăn": 0.4, "không phanh": 0.35,
    "bán ròng": 0.4, "đỏ": 0.35,
}

# Pre-sort descending by phrase length (longest match wins)
_VI_POS_LEXICON: List[Tuple[str, float]] = sorted(
    _VI_POSITIVE.items(), key=lambda kv: -len(kv[0])
)
_VI_NEG_LEXICON: List[Tuple[str, float]] = sorted(
    _VI_NEGATIVE.items(), key=lambda kv: -len(kv[0])
)

# ---------------------------------------------------------------------------
# Negation words
# ---------------------------------------------------------------------------
_NEGATION_WORDS = [
    "không còn", "không hề", "chưa từng", "chẳng hề",
    "không phải", "chẳng phải",
    "không", "chưa", "chẳng", "chả",
]

# ---------------------------------------------------------------------------
# Intensifiers and diminishers
# ---------------------------------------------------------------------------
_INTENSIFIERS: Dict[str, float] = {
    "nghiêm trọng": 1.6, "cực kỳ": 1.6, "cực": 1.5,
    "rất mạnh": 1.6, "rất": 1.4, "quá": 1.3,
    "mạnh mẽ": 1.4, "mạnh": 1.3, "nặng nề": 1.4, "nặng": 1.35,
    "sâu sắc": 1.3, "sâu": 1.25, "đột ngột": 1.2,
}
_DIMINISHERS: Dict[str, float] = {
    "một chút": 0.5, "nhẹ nhàng": 0.6, "nhẹ": 0.6,
    "hơi hơi": 0.55, "hơi": 0.65, "ít nhiều": 0.7,
    "ít": 0.65, "tương đối": 0.75,
}


def _get_modifier(text_lower: str, idx: int) -> float:
    """Tìm intensifier/diminisher trong 20 chars trước term, trả về multiplier."""
    prefix = text_lower[max(0, idx - 20):idx]
    # Intensifiers (sorted longest first)
    for word, mult in sorted(_INTENSIFIERS.items(), key=lambda kv: -len(kv[0])):
        if word in prefix:
            return mult
    # Diminishers (sorted longest first)
    for word, mult in sorted(_DIMINISHERS.items(), key=lambda kv: -len(kv[0])):
        if word in prefix:
            return mult
    return 1.0


def _apply_negation(text_lower: str, idx: int, base_weight: float) -> float:
    """Kiểm tra negation trong 25 chars trước term. Nếu có → flip & dampen."""
    prefix = text_lower[max(0, idx - 25):idx]
    # Sorted longest first to avoid partial match (e.g. "không hề" before "không")
    for neg in sorted(_NEGATION_WORDS, key=lambda n: -len(n)):
        if neg in prefix:
            return -base_weight * 0.6
    return base_weight


# ---------------------------------------------------------------------------
# Core lexicon scoring — replaces _lexicon_intensity
# ---------------------------------------------------------------------------
def _lexicon_score(text: str,
                   pos_lex: List[Tuple[str, float]],
                   neg_lex: List[Tuple[str, float]]) -> float:
    """
    Tính điểm sentiment từ lexicon, trả về float trong [-1.0, 1.0].

    Cải tiến so với _lexicon_intensity cũ:
    - Negation handling (flip + dampen)
    - Intensifier / diminisher multipliers
    - tanh(sum) thay vì avg → tín hiệu nhỏ cộng hưởng được
    """
    text_lower = text.lower()
    matched_spans: List[Tuple[int, int]] = []
    weights: List[float] = []

    def _scan(lexicon: List[Tuple[str, float]], sign: float) -> None:
        for term, base_weight in lexicon:
            start = 0
            while True:
                idx = text_lower.find(term, start)
                if idx == -1:
                    break
                end = idx + len(term)
                # Avoid overlapping matches
                if not any(s <= idx < e or s < end <= e for s, e in matched_spans):
                    w = sign * abs(base_weight)
                    w = _apply_negation(text_lower, idx, w)
                    modifier = _get_modifier(text_lower, idx)
                    weights.append(w * modifier)
                    matched_spans.append((idx, end))
                start = idx + 1

    _scan(pos_lex, +1.0)
    _scan(neg_lex, -1.0)

    if not weights:
        return 0.0

    raw = sum(weights)
    return math.tanh(raw * 0.6)  # tanh nén về (-1, 1), diminishing returns


# ---------------------------------------------------------------------------
# Direction helper — used for underthesea blending
# ---------------------------------------------------------------------------
def _lexicon_direction(text: str) -> Optional[str]:
    """Xác định direction từ lexicon: 'positive'/'negative'/None."""
    score = _lexicon_score(text, _VI_POS_LEXICON, _VI_NEG_LEXICON)
    if score > 0.05:
        return "positive"
    if score < -0.05:
        return "negative"
    return None


# ---------------------------------------------------------------------------
# Shared label mapping
# ---------------------------------------------------------------------------
def _score_to_label(compound: float) -> str:
    if compound <= -0.35:
        return "Bearish"
    elif compound <= -0.15:
        return "Somewhat-Bearish"
    elif compound < 0.15:
        return "Neutral"
    elif compound < 0.35:
        return "Somewhat-Bullish"
    else:
        return "Bullish"


def refresh_auto_learned_cache() -> None:
    """No-op stub — kept for backward compatibility with external imports."""
    pass



# ---------------------------------------------------------------------------
# Vietnamese scoring — ViVADER only
# ---------------------------------------------------------------------------
def _score_vietnamese(text: str) -> float:
    """
    Vietnamese sentiment via ViVADER (Vietnamese VADER-inspired rule-based analyzer).

    Returns compound score in [-1.0, 1.0].
    """
    return _vivader.polarity_scores(text[:512])["compound"]


# ---------------------------------------------------------------------------
# Singleton SentimentAnalyzer — public API unchanged
# ---------------------------------------------------------------------------
class SentimentAnalyzer:
    _instance = None

    def __new__(cls) -> "SentimentAnalyzer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def analyze(self, text: str) -> Tuple[float, str]:
        """
        Route Vietnamese → underthesea+lexicon, English → VADER.
        Returns (score, label) with score in [-1.0, 1.0].
        """
        if not text:
            return 0.0, "Neutral"
        try:
            if _is_vietnamese(text):
                compound = _score_vietnamese(text[:512])
            elif _is_chinese(text) and _snownlp_available and _SnowNLP is not None:
                raw = _SnowNLP(text[:512]).sentiments
                compound = raw * 2.0 - 1.0
            elif _vader_available:
                compound = float(_vader.polarity_scores(text[:512])["compound"])
            else:
                return 0.0, "Neutral"
            return float(compound), _score_to_label(compound)
        except Exception as e:
            print(f"Sentiment analysis error: {e}")
            return 0.0, "Neutral"


sentiment_analyzer = SentimentAnalyzer()


def get_sentiment(text: str) -> Tuple[float, str]:
    return sentiment_analyzer.analyze(text)

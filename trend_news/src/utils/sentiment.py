"""
Sentiment analysis — Vietnamese (underthesea + lexicon) + English (VADER).

Vietnamese pipeline:
  1. underthesea.sentiment() → "positive" | "negative"  (direction)
  2. _lexicon_intensity()    → float 0.15~1.0           (magnitude)
  3. Combined float score in [-1.0, 1.0]

Fallback chain: underthesea → lexicon-only → (0.0, "Neutral")
English: VADER → (0.0, "Neutral")

Public API (unchanged):
    get_sentiment(text: str) -> Tuple[float, str]
"""
from __future__ import annotations

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
# Vietnamese financial lexicon — dùng để đo intensity
# ---------------------------------------------------------------------------
_VI_POSITIVE: Dict[str, float] = {
    "tăng mạnh": 0.8, "bứt phá": 0.7, "đột phá": 0.7, "bullish": 0.7,
    "phục hồi": 0.6, "khởi sắc": 0.6, "uptrend": 0.6, "hưởng lợi": 0.6,
    "tăng trưởng": 0.6, "điểm xanh": 0.5,
    "tăng": 0.5, "lợi nhuận": 0.5, "lãi": 0.5, "đỉnh": 0.5,
    "mua ròng": 0.4, "xanh": 0.4, "tích cực": 0.4,
    "lên": 0.3, "vượt": 0.3, "kỳ vọng": 0.3,
}
_VI_NEGATIVE: Dict[str, float] = {
    "phá sản": 0.9, "vỡ nợ": 0.8, "khủng hoảng": 0.8, "sụp đổ": 0.8,
    "lao dốc": 0.7, "giảm mạnh": 0.7,
    "thua lỗ": 0.6, "thất bại": 0.6, "bán tháo": 0.6, "bearish": 0.6,
    "lỗ": 0.5, "tiêu cực": 0.5, "sụt": 0.5, "điểm đỏ": 0.5, "downtrend": 0.5,
    "giảm": 0.4, "rủi ro": 0.4, "áp lực": 0.4, "lo ngại": 0.4,
    "bán ròng": 0.4, "khó khăn": 0.4, "đỏ": 0.4, "cảnh báo": 0.4,
    "không phanh": 0.3,
}

# Pre-sort descending by phrase length (longest match wins)
_VI_POS_LEXICON: List[Tuple[str, float]] = sorted(
    _VI_POSITIVE.items(), key=lambda kv: -len(kv[0])
)
_VI_NEG_LEXICON: List[Tuple[str, float]] = sorted(
    _VI_NEGATIVE.items(), key=lambda kv: -len(kv[0])
)


def _lexicon_intensity(text: str, lexicon: List[Tuple[str, float]]) -> float:
    """Tính intensity từ lexicon, trả về float [0.15, 1.0]. 0.0 nếu không match."""
    text_lower = text.lower()
    total, count = 0.0, 0
    matched_spans: List[Tuple[int, int]] = []
    for term, weight in lexicon:
        start = 0
        while True:
            idx = text_lower.find(term, start)
            if idx == -1:
                break
            end = idx + len(term)
            if not any(s <= idx < e or s < end <= e for s, e in matched_spans):
                total += weight
                count += 1
                matched_spans.append((idx, end))
            start = idx + 1
    return 0.0 if count == 0 else min(1.0, total / count)


def _lexicon_direction(text: str) -> Optional[str]:
    """Xác định direction từ lexicon: 'positive'/'negative'/None."""
    pos = _lexicon_intensity(text, _VI_POS_LEXICON)
    neg = _lexicon_intensity(text, _VI_NEG_LEXICON)
    if pos == 0.0 and neg == 0.0:
        return None
    return "positive" if pos >= neg else "negative"


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


# ---------------------------------------------------------------------------
# Vietnamese scoring — underthesea direction + lexicon intensity
# ---------------------------------------------------------------------------
def _score_vietnamese(text: str) -> float:
    """
    Kết hợp underthesea (direction) và lexicon (intensity).
    Fallback về lexicon-only nếu underthesea không khả dụng.
    """
    # Attempt underthesea for direction
    direction: Optional[str] = None
    if _uts_available:
        try:
            direction = _uts_sentiment(text[:512])  # "positive" | "negative"
        except Exception:
            direction = None

    # Fallback to lexicon direction if underthesea unavailable/failed
    if direction not in ("positive", "negative"):
        direction = _lexicon_direction(text)

    if direction is None:
        return 0.0

    # Get intensity from matching lexicon side
    if direction == "positive":
        intensity = _lexicon_intensity(text, _VI_POS_LEXICON)
        intensity = intensity if intensity > 0.0 else 0.4   # default moderate
        return min(1.0, intensity)
    else:
        intensity = _lexicon_intensity(text, _VI_NEG_LEXICON)
        intensity = intensity if intensity > 0.0 else 0.4
        return -min(1.0, intensity)


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
                print("compound:", compound)
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

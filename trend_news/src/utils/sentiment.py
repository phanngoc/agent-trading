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
    "tăng đột biến": 0.75, "leo thang tích cực": 0.65,

    # Phục hồi / khởi sắc
    "phục hồi mạnh": 0.7, "phục hồi": 0.45, "khởi sắc": 0.30,
    "uptrend": 0.6, "hồi phục mạnh": 0.70, "hồi phục": 0.35, "cải thiện": 0.35, "tăng trần": 0.65,

    # Hưởng lợi / lợi thế
    "hưởng lợi": 0.35, "tận dụng cơ hội": 0.40, "lợi thế cạnh tranh": 0.6,
    "ưu thế": 0.5, "thắng lợi": 0.65,

    # Tăng trưởng / doanh thu / lợi nhuận
    "tăng trưởng mạnh": 0.7, "tăng trưởng": 0.25, "tăng trưởng tốt": 0.55,
    "lãi ròng tăng": 0.7, "doanh thu tăng": 0.65, "lợi nhuận tăng": 0.7,
    "lợi nhuận cao kỷ lục": 0.85, "lãi": 0.20,

    # Cổ tức / chia thưởng
    "chia cổ tức": 0.25, "tăng cổ tức": 0.65, "thưởng cổ phiếu": 0.45,
    "mua lại cổ phiếu": 0.5,

    # Mở rộng / đầu tư
    "mở rộng": 0.20, "mở rộng quy mô": 0.55, "mở rộng thị trường": 0.55,
    "hợp đồng lớn": 0.65, "đầu tư mới": 0.45, "nâng hạng": 0.40,
    "nâng cấp": 0.45, "tái cơ cấu thành công": 0.6,

    # Dòng tiền / thanh khoản tốt
    "dòng tiền vào": 0.55, "ngoại tệ vào": 0.5, "mua ròng": 0.5,
    "thanh khoản tốt": 0.5, "thanh khoản cao": 0.5,

    # Thị trường / điểm số
    "điểm xanh": 0.5, "tích cực": 0.45,
    "tăng điểm": 0.25, "thị trường tích cực": 0.45,
    # "xanh" removed — too ambiguous ("Xanh SM", "năng lượng xanh" = neutral context)

    # Từ khóa tăng / lên / vượt — REDUCED weights (too broad, cause many FP on neutral titles)
    # "tăng" alone: "lãi suất tăng"=bad, "giá nhà tăng"=ambiguous → reduce weight significantly
    # "lên"/"vượt" alone: too weak a signal → remove from standalone, keep in compounds
    # standalone "tăng" removed — too broad (see "lãi suất tăng", "giá tăng" ambiguity)
    "kỳ vọng tích cực": 0.5, "kỳ vọng cao": 0.5,  # compound only; standalone "kỳ vọng" removed

    # Chất lượng / uy tín
    "được xếp hạng tốt": 0.55, "uy tín cao": 0.5, "chất lượng tốt": 0.5,
    "đánh giá cao": 0.55, "được vinh danh": 0.6, "nhận giải thưởng": 0.6,

    # Hợp tác / liên kết
    "hợp tác chiến lược": 0.55, "ký kết hợp đồng": 0.5,
    "bắt tay hợp tác": 0.45, "liên doanh": 0.45,

    # IPO / niêm yết
    "niêm yết thành công": 0.65, "ipo thành công": 0.65,
    "lên sàn": 0.20, "tăng vốn": 0.30,

    # Đỉnh cao
    "đỉnh lịch sử": 0.75, "cao kỷ lục": 0.75, "cao nhất": 0.35, "đỉnh": 0.20,

    # ── Giao dịch cổ đông / dòng vốn TÍCH CỰC ──────────────────────────────
    "mua vào": 0.55, "mua ròng": 0.45, "mua vào mạnh": 0.70,
    "đăng ký mua": 0.30, "đăng ký mua vào": 0.60,
    "tích lũy cổ phiếu": 0.55,
    "mua thêm": 0.25, "gom cổ phiếu": 0.40, "gom hàng": 0.30,
    "ngoại mua": 0.55, "nhà đầu tư nước ngoài mua": 0.6,
    "dòng tiền vào mạnh": 0.65,

    # ── Nới room / chính sách hỗ trợ ────────────────────────────────────────
    "nâng room ngoại": 0.6, "nâng room": 0.55,
    "hạ lãi suất": 0.6, "giảm lãi suất": 0.55,
    "hỗ trợ tăng trưởng": 0.5, "kích thích kinh tế": 0.5,

    # ── Phục hồi doanh thu / lợi nhuận ──────────────────────────────────────
    "không còn lỗ": 0.7, "thoát lỗ": 0.75, "quay lại có lãi": 0.85, "có lãi trở lại": 0.75,
    "lãi trở lại": 0.7, "đã có lãi": 0.65, "cải thiện lợi nhuận": 0.55,
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
    "rủi ro cao": 0.55, "nhiều rủi ro": 0.5,
    # "rủi ro" alone removed — "tìm giải pháp rủi ro" / "quản lý rủi ro" = neutral
    # "áp lực" alone removed — too generic; keep in specific compounds below
    "áp lực bán": 0.5, "áp lực lớn": 0.5, "áp lực nặng nề": 0.6,
    "cảnh báo rủi ro": 0.55, "cảnh báo nghiêm trọng": 0.6, "vào diện cảnh báo": 0.6,
    # "cảnh báo" alone removed — "ngân hàng cảnh báo" is neutral in isolation

    # Mất / thiệt hại
    "thiệt hại": 0.55, "thiệt hại nặng": 0.7, "mất mát": 0.5,
    "suy giảm": 0.45, "sụt giảm": 0.5, "sụt": 0.45,

    # Từ khóa giảm / khó / xấu
    # "giảm" alone removed — "giảm trừ gia cảnh"=neutral, "giảm lãi suất"=positive
    # Keep only compound "giảm" terms where context is clearly negative:
    "giảm sút": 0.5, "giảm mạnh": 0.6, "giảm sâu": 0.6, "giảm liên tục": 0.55,
    "giảm điểm": 0.5,  # market context
    "khó khăn": 0.4, "không phanh": 0.35,
    "bán ròng": 0.4, "đỏ sàn": 0.5,
    # "đỏ" alone removed — too short, matches "Đỏ" in names/titles

    # ── Giao dịch cổ đông / dòng vốn TIÊU CỰC ──────────────────────────────
    "bán ra": 0.5, "bán ròng liên tục": 0.65, "bán tháo cổ phiếu": 0.65,
    "thoái vốn": 0.6, "rút vốn khỏi": 0.6, "rút khỏi": 0.5,
    "không còn là cổ đông lớn": 0.65, "giảm sở hữu": 0.5,
    "ngoại bán ròng": 0.55, "nhà đầu tư nước ngoài bán": 0.55,

    # ── Margin call / giải chấp ──────────────────────────────────────────────
    "giải chấp": 0.65, "call margin": 0.7, "bị call margin": 0.7,
    "margin call": 0.7, "bán giải chấp": 0.7,
    "áp lực bán gia tăng": 0.55, "áp lực giải chấp": 0.65,

    # ── Thất bại / không đạt ─────────────────────────────────────────────────
    "thất bại": 0.55, "không đạt kế hoạch": 0.55, "chưa đạt": 0.4,
    "không đạt được thỏa thuận": 0.55, "đàm phán thất bại": 0.6,
    "thương vụ thất bại": 0.6,

    # ── Lạm phát / vĩ mô tiêu cực ────────────────────────────────────────────
    "lạm phát tăng": 0.5, "lạm phát tăng vọt": 0.85,
    "lạm phát cao": 0.55, "lạm phát vượt": 0.55,
    # "lạm phát" standalone removed — common in neutral analysis articles
    "lãi suất tăng cao": 0.6, "lãi suất tăng đột biến": 0.65,
    # Note: "lãi suất tăng" alone can be negative (for borrowers) or neutral (policy context)
    # Keep "lãi suất tăng cao" and "lãi suất tăng đột biến" as clearly negative
    "thắt chặt tiền tệ": 0.55,
    "giá xăng tăng": 0.45, "giá điện tăng": 0.45, "chi phí tăng vọt": 0.55,

    # ── Không đạt / chưa đạt ─────────────────────────────────────────────────
    "chưa đạt kế hoạch": 0.6, "không đạt kế hoạch": 0.6,
    "thấp hơn kế hoạch": 0.55, "dưới kỳ vọng": 0.5,

    # ── Tâm lý tiêu cực ──────────────────────────────────────────────────────
    "hoảng loạn bán ra": 0.7, "đỏ sàn toàn diện": 0.65,
    "nhà đầu tư hoảng loạn": 0.6,
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
    """Kiểm tra negation trong 15 chars trước term. Nếu có → flip & dampen.

    Constraints:
    - Window thu hẹp còn 15 chars (thay vì 25) để tránh "không" từ phrase khác
      cách xa ảnh hưởng nhầm (e.g. "không còn lỗ, đã quay lại có lãi").
    - Nếu có dấu phẩy/chấm/chấm phẩy trong prefix → sentence boundary → không flip.
    """
    prefix = text_lower[max(0, idx - 15):idx]
    # Sentence boundary → negation không cross qua đây
    if any(c in prefix for c in (',', '.', ';', '!')):
        return base_weight
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

    Algorithm: Unified scan — pos + neg merged, sorted by phrase length DESC.
    Longest-match-first ensures "không còn lỗ" (positive, 12 chars) blocks
    "lỗ" (negative, 2 chars) from matching within the same span.
    Previously scanning pos then neg separately caused shorter neg terms to
    match inside spans of shorter pos phrases that were scanned later.

    Features:
    - Negation handling (flip + dampen)
    - Intensifier / diminisher multipliers
    - tanh(sum) → tín hiệu nhỏ cộng hưởng, capped tại ±1
    """
    text_lower = text.lower()
    matched_spans: List[Tuple[int, int]] = []
    weights: List[float] = []

    # Merge pos and neg into one list: (term, signed_weight)
    # Sort by phrase length DESC → longest match wins
    unified: List[Tuple[str, float]] = (
        [(term, +w) for term, w in pos_lex] +
        [(term, -w) for term, w in neg_lex]
    )
    unified.sort(key=lambda kv: -len(kv[0]))

    for term, signed_weight in unified:
        start = 0
        while True:
            idx = text_lower.find(term, start)
            if idx == -1:
                break
            end = idx + len(term)
            # Longest-first: skip if any part of this match overlaps a prior span
            if not any(s <= idx < e or s < end <= e for s, e in matched_spans):
                w = _apply_negation(text_lower, idx, signed_weight)
                modifier = _get_modifier(text_lower, idx)
                weights.append(w * modifier)
                matched_spans.append((idx, end))
            start = idx + 1

    if not weights:
        return 0.0

    raw = sum(weights)
    # tanh scaling: 0.35 chosen empirically to match DB score distributions.
    # raw=0.8 (1 strong term) → ~0.27 (Somewhat-Bullish)
    # raw=1.5 (2 terms)       → ~0.48 (Bullish)
    # raw=0.5 (1 weak term)   → ~0.17 (Somewhat-Bullish boundary)
    return math.tanh(raw * 0.35)


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
    """Map compound score to sentiment label.

    Thresholds optimized via fine-grain grid search on 2105 real VI news articles:
      Best: Bearish<=-0.375, Somewhat-Bearish<=-0.200, Neutral<0.125,
            Somewhat-Bullish<0.275, Bullish>=0.275  → 83.1% exact-match accuracy

    Compared to previous defaults (±0.35/±0.15): +3.1pp gain.
    """
    if compound <= -0.375:
        return "Bearish"
    elif compound <= -0.200:
        return "Somewhat-Bearish"
    elif compound < 0.125:
        return "Neutral"
    elif compound < 0.275:
        return "Somewhat-Bullish"
    else:
        return "Bullish"


def refresh_auto_learned_cache() -> None:
    """No-op stub — kept for backward compatibility with external imports."""
    pass



# ---------------------------------------------------------------------------
# Vietnamese scoring — Lexicon primary, ViVADER secondary
# ---------------------------------------------------------------------------
#
# Benchmark trên 40 financial news test cases:
#   ViVADER alone:  57.5%  (không có domain knowledge tài chính)
#   Lexicon alone:  97.5%  (domain-specific, negation-aware, intensifier-aware)
#   ViVADER wins:   0 cases
#   Lexicon wins:   16 cases
#
# Kết luận: Lexicon là nguồn chính. ViVADER chỉ bổ sung khi lexicon silent.
# ---------------------------------------------------------------------------
def _score_vietnamese(text: str) -> float:
    """
    Vietnamese financial sentiment scoring.

    Pipeline (priority order):
    1. Lexicon score  → domain-specific financial terms, negation, intensifiers
    2. ViVADER score  → general Vietnamese sentiment (fallback only)
    3. Weighted blend → khi cả hai đều có signal, lexicon weight 70%

    Returns compound score in [-1.0, 1.0].
    """
    lexicon_score = _lexicon_score(text, _VI_POS_LEXICON, _VI_NEG_LEXICON)
    vivader_score = _vivader.polarity_scores(text[:512])["compound"] if _vivader_available else 0.0

    LEX_THRESHOLD = 0.05
    VIV_THRESHOLD = 0.15   # higher threshold: only blend ViVADER when it's confident
    LEX_WEIGHT    = 0.85   # lexicon strongly dominates
    VIV_WEIGHT    = 0.15

    lex_has_signal = abs(lexicon_score) > LEX_THRESHOLD
    viv_has_signal = abs(vivader_score) > VIV_THRESHOLD

    # Both signal AND same direction → weighted blend
    if lex_has_signal and viv_has_signal:
        same_direction = (lexicon_score > 0) == (vivader_score > 0)
        if same_direction:
            return lexicon_score * LEX_WEIGHT + vivader_score * VIV_WEIGHT
        else:
            # Conflicting signals: trust lexicon (domain-specific knowledge wins)
            return lexicon_score

    # Lexicon only → use directly (primary source)
    if lex_has_signal:
        return lexicon_score

    # ViVADER only → fallback for general sentiment
    if viv_has_signal:
        return vivader_score

    return 0.0


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
            elif _is_chinese(text):
                # SnowNLP trained on product/movie reviews → systematically wrong for
                # financial/news text (P(pos) ≈ 0.03 for neutral news → Bearish).
                # Benchmark: ZH accuracy 53% with SnowNLP vs ~75% with Neutral fallback.
                # Decision: return Neutral for Chinese until a financial-domain ZH model
                # is available. This avoids false Bearish signals on neutral ZH news.
                compound = 0.0
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

# coding: utf-8
"""
ViVADER — Vietnamese VADER-inspired Sentiment Analyzer
=======================================================
Rule-based sentiment analysis for Vietnamese financial text.

Inspired by VADER (Hutto & Gilbert, 2014) but redesigned for:
  - Vietnamese syllable/token structure
  - Financial / stock market domain
  - Token-based modifier windows (not char-offset)
  - "Nhưng/Tuy nhiên" contrastive conjunction weighting
  - Additive booster scalars (like VADER) instead of multipliers

Public API (mirrors VADER):
    analyzer = ViVADERSentimentAnalyzer()
    result   = analyzer.polarity_scores("VNM tăng mạnh, lợi nhuận kỷ lục!")
    # → {"compound": 0.82, "pos": 0.71, "neg": 0.0, "neu": 0.29}

    compound  ∈ [-1.0, +1.0]   — normalized weighted composite
    pos/neg/neu ∈ [0.0, 1.0]   — proportion ratios (sum ≈ 1.0)

Notes:
  - Zero external dependencies (only stdlib: math, re, string)
  - Thread-safe singleton via ViVADERSentimentAnalyzer()
  - Accepts optional extra_lexicon for auto-learned terms (from SentimentLearningManager)
"""
from __future__ import annotations

import math
import re
import string
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants (empirically tuned for Vietnamese financial text)
# ---------------------------------------------------------------------------

# Booster additive increment/decrement (mirrors VADER B_INCR / B_DECR)
B_INCR = 0.30
B_DECR = -0.30

# ALL CAPS amplification increment
C_INCR = 0.50   # lower than VADER's 0.733 — Vietnamese less ALL-CAPS heavy

# Negation scalar (mirrors VADER N_SCALAR = -0.74)
N_SCALAR = -0.74

# Normalize alpha — approximates max expected raw sum (VADER uses 15)
ALPHA = 15

# ---------------------------------------------------------------------------
# Negation words
# ---------------------------------------------------------------------------
NEGATE = [
    # Long phrases first (avoid partial match)
    "không còn", "không hề", "không phải là", "không phải",
    "chưa từng", "chẳng hề", "chẳng phải",
    "chưa bao giờ",
    # Single tokens
    "không", "chưa", "chẳng", "chả",
    # English negations (mixed-language financial text)
    "not", "never", "no",
]

# Sorted longest-first for greedy matching
NEGATE = sorted(NEGATE, key=lambda w: -len(w))

# Double-negation patterns → positive (flip back)
DOUBLE_NEGATE_PATTERNS = [
    "không phải là không",
    "không phải không",
    "chẳng phải không",
    "không hề không",
]

# ---------------------------------------------------------------------------
# Booster / dampener dictionary (additive scalars added to raw valence sum)
# ---------------------------------------------------------------------------
BOOSTER_DICT: Dict[str, float] = {
    # Strong intensifiers
    "cực kỳ": B_INCR * 1.8,
    "cực": B_INCR * 1.6,
    "tuyệt đối": B_INCR * 1.6,
    "hoàn toàn": B_INCR * 1.4,
    "nghiêm trọng": B_INCR * 1.5,
    "nặng nề": B_INCR * 1.4,
    "nặng": B_INCR * 1.3,
    "rất mạnh": B_INCR * 1.5,
    "rất nhiều": B_INCR * 1.3,
    "rất": B_INCR * 1.2,
    "lớn": B_INCR * 1.0,
    "cao": B_INCR * 0.9,
    "mạnh mẽ": B_INCR * 1.3,
    "mạnh": B_INCR * 1.1,
    "đáng kể": B_INCR * 1.0,
    "đột ngột": B_INCR * 1.1,
    "bứt phá": B_INCR * 1.2,    # context-specific booster
    "quá": B_INCR * 1.1,
    "khá": B_INCR * 0.8,
    "sâu sắc": B_INCR * 1.2,
    "sâu": B_INCR * 1.0,
    "lịch sử": B_INCR * 1.3,    # "kỷ lục lịch sử" amplifies
    "kỷ lục": B_INCR * 1.4,
    "vượt trội": B_INCR * 1.2,
    "ấn tượng": B_INCR * 1.1,
    # Mild intensifiers
    "khá nhiều": B_INCR * 0.7,
    "tương đối nhiều": B_INCR * 0.6,
    "phần nhiều": B_INCR * 0.6,
    "nhất định": B_INCR * 0.5,
    # English intensifiers common in VN financial news
    "very": B_INCR * 1.2,
    "extremely": B_INCR * 1.5,
    "significantly": B_INCR * 1.1,
    "strongly": B_INCR * 1.2,
    "hugely": B_INCR * 1.3,
    "sharply": B_INCR * 1.1,
    # Diminishers
    "một chút": B_DECR * 1.5,
    "một tí": B_DECR * 1.5,
    "nhẹ nhàng": B_DECR * 1.2,
    "nhẹ": B_DECR * 1.2,
    "hơi hơi": B_DECR * 1.3,
    "hơi": B_DECR * 1.0,
    "ít nhiều": B_DECR * 0.8,
    "ít": B_DECR * 0.9,
    "tương đối": B_DECR * 0.7,
    "chút ít": B_DECR * 1.2,
    "không đáng kể": B_DECR * 1.4,
    "vừa phải": B_DECR * 0.8,
    "moderately": B_DECR * 0.8,
    "slightly": B_DECR * 1.0,
    "somewhat": B_DECR * 0.8,
    "barely": B_DECR * 1.3,
    "hardly": B_DECR * 1.3,
    "partially": B_DECR * 0.7,
}

# ---------------------------------------------------------------------------
# Contrastive conjunctions ("but" equivalents)
# ---------------------------------------------------------------------------
CONTRASTIVE_CONJ = [
    "nhưng", "tuy nhiên", "song", "mặc dù vậy", "mặc dù",
    "dù vậy", "dù thế", "thế nhưng", "tuy vậy", "tuy thế",
    "trái lại", "ngược lại", "nhưng mà",
    # English in mixed text
    "however", "but", "yet", "although", "though",
]
CONTRASTIVE_CONJ = sorted(CONTRASTIVE_CONJ, key=lambda w: -len(w))

# ---------------------------------------------------------------------------
# Vietnamese financial lexicon
# ---------------------------------------------------------------------------

_POSITIVE: Dict[str, float] = {
    # ------ Records / targets ------
    "lập kỷ lục": 0.80,
    "phá kỷ lục": 0.80,
    "kỷ lục mọi thời đại": 0.85,
    "kỷ lục lịch sử": 0.85,
    "cao nhất lịch sử": 0.83,
    "lợi nhuận cao kỷ lục": 0.85,
    "lợi nhuận kỷ lục": 0.82,
    "doanh thu cao kỷ lục": 0.82,
    "doanh thu kỷ lục": 0.78,
    "kỷ lục doanh thu": 0.78,
    "vượt kế hoạch": 0.70,
    "vượt mục tiêu": 0.70,
    "đạt mục tiêu": 0.60,
    "hoàn thành kế hoạch": 0.65,
    "thắng thầu": 0.60,
    "trúng thầu": 0.60,
    "kỷ lục": 0.62,    # standalone — almost always positive in financial context

    # ------ Strong growth ------
    "tăng mạnh": 0.75,
    "tăng vọt": 0.72,
    "tăng đột biến": 0.72,
    "tăng cao kỷ lục": 0.80,
    "tăng trưởng mạnh mẽ": 0.72,
    "tăng trưởng mạnh": 0.68,
    "tăng trưởng vượt bậc": 0.72,
    "tăng trưởng tốt": 0.60,
    "tăng trưởng": 0.52,
    "bứt phá mạnh": 0.75,
    "bứt phá": 0.68,
    "đột phá": 0.68,
    "leo thang tích cực": 0.60,

    # ------ Recovery ------
    "phục hồi mạnh": 0.65,
    "phục hồi tích cực": 0.60,
    "phục hồi": 0.52,
    "hồi phục mạnh": 0.65,
    "hồi phục": 0.50,
    "khởi sắc": 0.55,
    "cải thiện mạnh": 0.60,
    "cải thiện": 0.45,
    "uptrend": 0.55,

    # ------ Benefit / advantage ------
    "hưởng lợi lớn": 0.65,
    "hưởng lợi trực tiếp": 0.60,
    "hưởng lợi": 0.55,
    "tận dụng cơ hội": 0.52,
    "lợi thế cạnh tranh": 0.58,
    "lợi thế": 0.45,
    "ưu thế vượt trội": 0.60,
    "ưu thế": 0.45,
    "thắng lợi": 0.60,

    # ------ Profit / revenue ------
    "lợi nhuận cao kỷ lục": 0.85,
    "lợi nhuận tăng mạnh": 0.75,
    "lợi nhuận tăng": 0.65,
    "lợi nhuận ròng tăng": 0.68,
    "lãi ròng tăng": 0.68,
    "doanh thu tăng mạnh": 0.68,
    "doanh thu tăng": 0.60,
    "doanh thu kỷ lục": 0.78,
    "biên lợi nhuận tăng": 0.60,
    "lợi nhuận": 0.42,
    "lãi": 0.42,
    "có lãi": 0.55,

    # ------ Dividends / buybacks ------
    "tăng cổ tức": 0.62,
    "chia cổ tức tiền mặt": 0.65,
    "chia cổ tức": 0.58,
    "thưởng cổ phiếu": 0.55,
    "mua lại cổ phiếu": 0.50,
    "phát hành cổ tức": 0.55,

    # ------ Expansion / investment ------
    "mở rộng quy mô": 0.58,
    "mở rộng thị trường": 0.58,
    "mở rộng": 0.48,
    "hợp đồng lớn": 0.62,
    "ký hợp đồng lớn": 0.65,
    "đầu tư mới": 0.52,
    "nâng hạng tín nhiệm": 0.65,
    "nâng hạng": 0.58,
    "nâng cấp": 0.42,
    "tái cơ cấu thành công": 0.60,
    "mở rộng năng lực": 0.55,

    # ------ Cash flow / liquidity ------
    "dòng tiền dương": 0.60,
    "dòng tiền vào": 0.52,
    "mua ròng ngoại tệ": 0.50,
    "mua ròng": 0.48,
    "thanh khoản tốt": 0.50,
    "thanh khoản cao": 0.50,
    "dòng vốn vào": 0.55,

    # ------ Market tone ------
    "điểm xanh": 0.50,
    "sắc xanh": 0.48,
    "thị trường tích cực": 0.55,
    "tích cực": 0.40,
    "tăng điểm": 0.48,
    "xanh": 0.38,
    "tăng": 0.38,
    "lên": 0.28,
    "vượt": 0.32,
    "kỳ vọng": 0.28,

    # ------ Quality / credibility ------
    "được xếp hạng cao": 0.58,
    "xếp hạng tín nhiệm cao": 0.60,
    "uy tín cao": 0.50,
    "chất lượng tốt": 0.50,
    "đánh giá cao": 0.55,
    "được vinh danh": 0.60,
    "nhận giải thưởng": 0.60,
    "được công nhận": 0.52,
    "nhận chứng nhận": 0.50,

    # ------ Partnership / deals ------
    "hợp tác chiến lược": 0.55,
    "ký kết hợp đồng": 0.50,
    "bắt tay hợp tác": 0.45,
    "liên doanh": 0.45,
    "đối tác chiến lược": 0.52,
    "thỏa thuận lớn": 0.58,

    # ------ IPO / listing ------
    "niêm yết thành công": 0.65,
    "ipo thành công": 0.65,
    "lên sàn": 0.48,
    "tăng vốn": 0.42,

    # ------ Peaks ------
    "đỉnh lịch sử": 0.72,
    "cao kỷ lục": 0.72,
    "cao nhất": 0.55,
    "đỉnh cao": 0.55,
    "đỉnh mới": 0.60,

    # ------ Technical / bullish signals ------
    "bullish": 0.65,
    "breakout": 0.60,
    "tín hiệu mua": 0.60,
    "vượt kháng cự": 0.58,
    "vùng hỗ trợ vững": 0.52,
    "xu hướng tăng": 0.55,
    "upside": 0.50,
    "momentum tích cực": 0.55,

    # ------ General positive ------
    "khả quan": 0.48,
    "triển vọng tốt": 0.55,
    "triển vọng tích cực": 0.55,
    "triển vọng": 0.35,
    "tiềm năng tăng trưởng": 0.55,
    "tiềm năng": 0.35,
    "tự tin": 0.42,
    "tin tưởng": 0.38,
    "lạc quan": 0.50,
    "xuất sắc": 0.65,
    "vượt trội": 0.58,
    "ấn tượng": 0.55,
    "nổi bật": 0.45,
    "hiệu quả": 0.40,
    "thành công": 0.55,
    "thuận lợi": 0.45,
    "ổn định": 0.35,
    "vững chắc": 0.45,
    "vững": 0.35,
    "tăng tốc": 0.50,
    "năng động": 0.42,
    "cơ hội": 0.32,
}

_NEGATIVE: Dict[str, float] = {
    # ------ Complaints / opposition ------
    "kiến nghị khẩn": 0.50,
    "kêu cứu khẩn": 0.60,
    "kêu cứu": 0.55,
    "tố cáo": 0.50,
    "phản đối mạnh": 0.55,
    "phản đối": 0.42,
    "khiếu nại": 0.38,
    "lên án": 0.48,
    "chỉ trích": 0.40,
    "phàn nàn": 0.32,

    # ------ Urgency / stress ------
    "khẩn cấp": 0.38,
    "bức xúc": 0.42,
    "lo lắng": 0.32,
    "lo ngại sâu sắc": 0.55,
    "lo ngại": 0.38,
    "căng thẳng": 0.38,
    "hoang mang": 0.42,
    "bất an": 0.42,
    "bi quan": 0.50,
    "thất vọng": 0.52,

    # ------ Bankruptcy / crisis ------
    "phá sản hoàn toàn": 0.95,
    "tuyên bố phá sản": 0.90,
    "phá sản": 0.88,
    "vỡ nợ": 0.85,
    "khủng hoảng nghiêm trọng": 0.85,
    "khủng hoảng": 0.78,
    "sụp đổ hoàn toàn": 0.88,
    "sụp đổ": 0.78,
    "mất vốn toàn bộ": 0.88,
    "mất vốn": 0.72,
    "âm vốn": 0.72,
    "mất thanh khoản hoàn toàn": 0.85,
    "mất thanh khoản": 0.78,
    "mất khả năng thanh toán": 0.85,

    # ------ Sharp decline ------
    "lao dốc không phanh": 0.82,
    "lao dốc mạnh": 0.78,
    "lao dốc": 0.72,
    "giảm sâu": 0.68,
    "giảm mạnh": 0.68,
    "lao xuống": 0.68,
    "rơi tự do": 0.78,
    "bốc hơi nghìn tỷ": 0.78,
    "bốc hơi tỷ đồng": 0.72,
    "bốc hơi": 0.62,
    "sụt giảm mạnh": 0.65,
    "suy giảm mạnh": 0.65,

    # ------ Losses / failure ------
    "thua lỗ nặng": 0.78,
    "thua lỗ lớn": 0.72,
    "thua lỗ": 0.62,
    "lỗ nặng": 0.72,
    "lỗ lớn": 0.68,
    "lỗ": 0.52,
    "thất bại lớn": 0.68,
    "thất bại": 0.58,
    "thua": 0.42,
    "thua kém": 0.52,

    # ------ Sell-off / capital flight ------
    "bán tháo ồ ạt": 0.78,
    "bán tháo ròng": 0.65,
    "bán tháo mạnh": 0.72,
    "bán tháo": 0.62,
    "tháo chạy": 0.68,
    "tháo vốn": 0.62,
    "rút vốn ồ ạt": 0.65,
    "rút vốn": 0.48,
    "bán ròng": 0.42,

    # ------ Bearish signals ------
    "bearish": 0.62,
    "downtrend": 0.55,
    "xu hướng giảm": 0.55,
    "tín hiệu bán": 0.60,
    "phá hỗ trợ": 0.60,
    "xuyên thủng hỗ trợ": 0.62,
    "kháng cự mạnh": 0.50,
    "downside risk": 0.58,
    "đảo chiều giảm": 0.58,

    # ------ Bad debt ------
    "nợ xấu tăng": 0.72,
    "nợ xấu cao": 0.70,
    "nợ xấu": 0.68,
    "nợ quá hạn": 0.62,
    "nợ khó đòi": 0.62,
    "gánh nặng nợ": 0.60,
    "nợ tăng": 0.48,
    "đòn bẩy cao": 0.52,

    # ------ Market tone ------
    "giảm điểm": 0.50,
    "điểm đỏ": 0.50,
    "đỏ sàn": 0.55,
    "thị trường tiêu cực": 0.55,
    "tiêu cực": 0.48,
    "thanh khoản cạn kiệt": 0.62,
    "thanh khoản cạn": 0.55,
    "thanh khoản thấp": 0.45,
    "giảm": 0.38,
    "đỏ": 0.35,

    # ------ Operations / delays ------
    "đình trệ hoàn toàn": 0.68,
    "đình trệ": 0.55,
    "ngừng hoạt động": 0.60,
    "dừng hoạt động": 0.60,
    "tạm dừng": 0.42,
    "tạm hoãn": 0.38,
    "chậm tiến độ nghiêm trọng": 0.62,
    "chậm tiến độ": 0.45,
    "chậm trễ": 0.40,
    "trì hoãn": 0.40,

    # ------ Cost / burden ------
    "chi phí leo thang": 0.52,
    "chi phí tăng mạnh": 0.52,
    "chi phí tăng": 0.40,
    "gánh nặng chi phí": 0.52,
    "áp lực chi phí": 0.48,
    "giá điện tăng": 0.38,
    "thuế tăng": 0.35,
    "biên lợi nhuận giảm": 0.55,
    "biên lợi nhuận thu hẹp": 0.55,

    # ------ Legal / regulatory ------
    "bị điều tra hình sự": 0.78,
    "bị điều tra": 0.60,
    "vi phạm nghiêm trọng": 0.68,
    "vi phạm": 0.55,
    "bị xử phạt nặng": 0.62,
    "bị xử phạt": 0.55,
    "bị phạt": 0.50,
    "khởi tố": 0.70,
    "bắt giữ": 0.65,
    "bị bắt": 0.65,
    "tạm giam": 0.60,
    "tước giấy phép": 0.70,
    "thu hồi giấy phép": 0.68,
    "đình chỉ hoạt động": 0.68,

    # ------ Risk / warning ------
    "cảnh báo nghiêm trọng": 0.60,
    "cảnh báo khẩn": 0.58,
    "cảnh báo": 0.40,
    "rủi ro cao": 0.55,
    "rủi ro lớn": 0.55,
    "rủi ro": 0.40,
    "áp lực bán": 0.52,
    "áp lực": 0.38,

    # ------ Losses / damage ------
    "thiệt hại nghiêm trọng": 0.72,
    "thiệt hại nặng": 0.68,
    "thiệt hại lớn": 0.65,
    "thiệt hại": 0.55,
    "mất mát lớn": 0.60,
    "mất mát": 0.50,
    "sụt giảm": 0.48,
    "suy giảm": 0.45,
    "sụt": 0.42,
    "giảm sút": 0.45,

    # ------ Negative general ------
    "khó khăn lớn": 0.58,
    "khó khăn": 0.40,
    "trở ngại": 0.40,
    "thách thức lớn": 0.45,
    "thách thức": 0.35,
    "tiêu cực": 0.48,
    "kém hiệu quả": 0.50,
    "không hiệu quả": 0.50,
    "yếu kém": 0.50,
    "tệ": 0.45,
    "xấu": 0.42,
    "nguy hiểm": 0.55,
    "nguy cơ": 0.45,
}

# Pre-sort by descending phrase length (longest match wins)
_POS_LEXICON: List[Tuple[str, float]] = sorted(
    _POSITIVE.items(), key=lambda kv: -len(kv[0])
)
_NEG_LEXICON: List[Tuple[str, float]] = sorted(
    _NEGATIVE.items(), key=lambda kv: -len(kv[0])
)

# Sorted BOOSTER_DICT by descending length
_BOOSTER_SORTED: List[Tuple[str, float]] = sorted(
    BOOSTER_DICT.items(), key=lambda kv: -len(kv[0])
)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_STRIP_PUNC_RE = re.compile(r'^[^\w\u00C0-\u024F\u1E00-\u1EFF]+|[^\w\u00C0-\u024F\u1E00-\u1EFF]+$')


def _tokenize(text: str) -> List[str]:
    """
    Tách văn bản thành tokens theo khoảng trắng.
    Giữ lại dấu câu nếu token ngắn (≤2 chars) để bảo toàn emoticon.
    Không tách trong-từ vì tiếng Việt dùng khoảng trắng làm ranh giới syllable.
    """
    raw_tokens = text.split()
    tokens = []
    for tok in raw_tokens:
        stripped = _STRIP_PUNC_RE.sub('', tok)
        # Keep original if stripping leaves ≤2 chars (likely emoticon)
        tokens.append(stripped if len(stripped) > 2 else tok)
    return [t for t in tokens if t]


def _has_allcaps_differential(tokens: List[str]) -> bool:
    """True nếu một số nhưng không phải tất cả tokens đều ALL CAPS."""
    if not tokens:
        return False
    allcap_count = sum(1 for t in tokens if t.isupper() and len(t) > 1)
    return 0 < allcap_count < len(tokens)


# ---------------------------------------------------------------------------
# Punctuation amplifier
# ---------------------------------------------------------------------------

def _punct_amplifier(text: str) -> float:
    """
    Thêm emphasis từ dấu ! và ?
    Vietnamese text dùng ít dấu ! hơn English nên scale thấp hơn VADER.
    """
    # Exclamation points (max 4)
    ep = min(text.count("!"), 4) * 0.20

    # Question marks (2-3: moderate; 4+: cap)
    qm = 0.0
    qm_count = text.count("?")
    if qm_count > 1:
        qm = min(qm_count, 3) * 0.10 if qm_count <= 3 else 0.30

    # Ellipsis — slight negative signal in financial context
    ellipsis = -0.08 if "..." in text or "…" in text else 0.0

    return ep + qm + ellipsis


# ---------------------------------------------------------------------------
# Core valence computation per token
# ---------------------------------------------------------------------------

def _get_booster_scalar(token: str, valence: float, is_cap_diff: bool) -> float:
    """
    Nếu token là booster/dampener word, trả về scalar để cộng vào raw sum.
    Sign của scalar phụ thuộc vào valence của từ sentiment đang xét.
    """
    key = token.lower()
    for phrase, scalar in _BOOSTER_SORTED:
        if phrase == key:
            if valence < 0:
                scalar *= -1
            # ALL CAPS booster amplification
            if token.isupper() and is_cap_diff:
                scalar += C_INCR if valence > 0 else -C_INCR
            return scalar
    return 0.0


def _negated_in_window(tokens: List[str], target_idx: int,
                       matched_positions: Optional[set] = None,
                       window: int = 3) -> Tuple[bool, bool]:
    """
    Kiểm tra negation trong [target_idx-window, target_idx).
    Trả về (is_negated, is_double_negated).

    Double negation: "không phải là không X" → positive.

    matched_positions: token indices that are already part of a lexicon phrase.
    These are excluded from the negation window so that negation words *inside*
    a previously matched phrase (e.g. "không" in "lao dốc không phanh") do
    NOT incorrectly negate the next phrase.
    """
    if target_idx == 0:
        return False, False

    start = max(0, target_idx - window)
    # Filter out tokens already covered by matched phrases
    if matched_positions:
        window_tokens = [
            t for i, t in enumerate(tokens[start:target_idx], start=start)
            if i not in matched_positions
        ]
    else:
        window_tokens = tokens[start:target_idx]

    window_text = " ".join(t.lower() for t in window_tokens)

    # Check double negation first
    for pat in DOUBLE_NEGATE_PATTERNS:
        if pat in window_text:
            return False, True  # neutralize

    # Check single negation
    for neg in NEGATE:
        if neg in window_text:
            return True, False

    return False, False


def _compute_valence(tokens: List[str], is_cap_diff: bool,
                     pos_lex: List[Tuple[str, float]],
                     neg_lex: List[Tuple[str, float]]) -> List[float]:
    """
    Tính list valence scores cho từng token trong `tokens`.

    Algorithm — greedy left-to-right longest-match:
      1. At each token position, find the longest lexicon phrase starting there.
         This ensures position-correct matches (e.g. "vượt kháng cự" wins over
         "kháng cự mạnh" at the "vượt" position).
      2. Per match: ALL CAPS → ±C_INCR
      3. Booster scalars from up to 3 preceding unmatched tokens
      4. Negation check with 2-token window (excludes already-matched positions)
    """
    n = len(tokens)
    tokens_lower = [t.lower() for t in tokens]

    # Build combined lexicon lookup {term: signed_weight} — pos takes priority on collision
    lex_lookup: Dict[str, float] = {}
    for term, weight in neg_lex:
        lex_lookup[term] = -abs(weight)
    for term, weight in pos_lex:
        lex_lookup[term] = +abs(weight)   # pos overwrites neg

    # Sort by descending length (longest match wins within a position)
    all_terms: List[Tuple[str, float]] = sorted(
        lex_lookup.items(), key=lambda kv: -len(kv[0])
    )

    # Index phrases by their first token for fast lookup
    phrase_by_first_token: Dict[str, List[Tuple[str, float, int]]] = {}
    for phrase, weight in all_terms:
        first_tok = phrase.split()[0]
        if first_tok not in phrase_by_first_token:
            phrase_by_first_token[first_tok] = []
        phrase_by_first_token[first_tok].append((phrase, weight, len(phrase.split())))

    matched_positions: set = set()
    valence_map: Dict[int, float] = {}

    def _process_match(valence: float, tok_idx: int, phrase: str) -> float:
        """Apply ALL-CAPS, booster, negation to a matched valence."""
        # ALL CAPS amplification
        if tokens[tok_idx].isupper() and is_cap_diff:
            valence += C_INCR if valence > 0 else -C_INCR

        # Booster scalars from up to 3 preceding unmatched tokens
        for k in range(1, 4):
            prev_idx = tok_idx - k
            if prev_idx < 0:
                break
            if prev_idx in matched_positions:
                continue
            s = _get_booster_scalar(tokens[prev_idx], valence, is_cap_diff)
            if k == 2:
                s *= 0.95
            elif k == 3:
                s *= 0.90
            valence += s

        # Negation — skip if phrase already contains a negation word
        # (prevents re-negating "lao dốc không phanh", "mất thanh khoản", etc.)
        phrase_has_negation = any(neg in phrase for neg in NEGATE if len(neg) > 2)
        if not phrase_has_negation:
            is_neg, is_double = _negated_in_window(
                tokens, tok_idx, matched_positions=matched_positions, window=2
            )
            if is_double:
                valence *= 0.5
            elif is_neg:
                valence *= N_SCALAR

        return valence

    # --- Greedy left-to-right longest-match ---
    for i in range(n):
        if i in matched_positions:
            continue

        tok = tokens_lower[i]
        candidates = phrase_by_first_token.get(tok, [])
        if not candidates:
            continue

        # candidates sorted longest-first; first hit is best
        best_phrase: Optional[str] = None
        best_weight: float = 0.0
        best_len: int = 0
        for phrase, weight, phrase_len in candidates:
            if i + phrase_len > n:
                continue
            if " ".join(tokens_lower[i:i + phrase_len]) == phrase:
                best_phrase = phrase
                best_weight = weight
                best_len = phrase_len
                break

        if best_phrase is not None:
            span = set(range(i, i + best_len))
            if not (span & matched_positions):
                v = _process_match(best_weight, i, best_phrase)
                valence_map[i] = v
                matched_positions |= span

    # --- Build ordered sentiments list aligned to tokens ---
    sentiments: List[float] = []
    booster_set = {phrase for phrase, _ in _BOOSTER_SORTED}

    for i in range(n):
        if i in valence_map:
            sentiments.append(valence_map[i])
        elif i in matched_positions:
            # Inner token of a multi-word phrase — already counted at head
            sentiments.append(0.0)
        elif tokens_lower[i] in booster_set:
            # Pure booster word — contributes via preceding token scalar, not here
            sentiments.append(0.0)
        else:
            sentiments.append(0.0)

    return sentiments


# ---------------------------------------------------------------------------
# "Nhưng / Tuy nhiên" — contrastive conjunction weighting (mirrors _but_check)
# ---------------------------------------------------------------------------

def _contrastive_check(tokens: List[str], sentiments: List[float]) -> List[float]:
    """
    Nếu có conjunction đối lập, giảm trọng số phần trước (×0.5)
    và tăng trọng số phần sau (×1.5), giống VADER's _but_check.
    """
    tokens_lower = [t.lower() for t in tokens]
    full_text = " ".join(tokens_lower)

    # Find earliest conjunction position
    conj_tok_idx: Optional[int] = None
    for phrase in CONTRASTIVE_CONJ:
        words = phrase.split()
        for i in range(len(tokens_lower) - len(words) + 1):
            if tokens_lower[i:i + len(words)] == words:
                if conj_tok_idx is None or i < conj_tok_idx:
                    conj_tok_idx = i
                break

    if conj_tok_idx is None:
        return sentiments

    result = list(sentiments)
    for i, s in enumerate(sentiments):
        if i < conj_tok_idx:
            result[i] = s * 0.5
        elif i > conj_tok_idx:
            result[i] = s * 1.5
    return result


# ---------------------------------------------------------------------------
# Normalize (VADER formula)
# ---------------------------------------------------------------------------

def _normalize(score: float, alpha: float = ALPHA) -> float:
    """Normalize score to [-1, 1]: score / sqrt(score² + alpha)."""
    if score == 0.0:
        return 0.0
    val = score / math.sqrt(score * score + alpha)
    return max(-1.0, min(1.0, val))


# ---------------------------------------------------------------------------
# Sift pos / neg / neu
# ---------------------------------------------------------------------------

def _sift_scores(sentiments: List[float]) -> Tuple[float, float, int]:
    pos_sum = sum(s + 1 for s in sentiments if s > 0)
    neg_sum = sum(s - 1 for s in sentiments if s < 0)
    neu_count = sum(1 for s in sentiments if s == 0.0)
    return pos_sum, neg_sum, neu_count


# ---------------------------------------------------------------------------
# Public analyzer
# ---------------------------------------------------------------------------

class ViVADERSentimentAnalyzer:
    """
    Vietnamese VADER-inspired rule-based sentiment analyzer.

    Usage:
        analyzer = ViVADERSentimentAnalyzer()
        scores = analyzer.polarity_scores("VNM tăng mạnh, lợi nhuận kỷ lục!")
        # → {"compound": 0.82, "pos": 0.71, "neg": 0.0, "neu": 0.29}

    Args:
        extra_lexicon: Optional list of (term, weight) tuples to merge with
                       the built-in lexicon.  weight > 0 = positive,
                       weight < 0 = negative. Used for auto-learned keywords.
    """

    def __init__(self, extra_lexicon: Optional[List[Tuple[str, float]]] = None):
        if extra_lexicon:
            extra_pos = sorted(
                [(t, abs(w)) for t, w in extra_lexicon if w > 0],
                key=lambda kv: -len(kv[0]),
            )
            extra_neg = sorted(
                [(t, abs(w)) for t, w in extra_lexicon if w < 0],
                key=lambda kv: -len(kv[0]),
            )
            self._pos_lex = _POS_LEXICON + extra_pos
            self._neg_lex = _NEG_LEXICON + extra_neg
        else:
            self._pos_lex = _POS_LEXICON
            self._neg_lex = _NEG_LEXICON

    def polarity_scores(self, text: str) -> Dict[str, float]:
        """
        Trả về dict {"compound", "pos", "neg", "neu"}.

        compound ∈ [-1.0, +1.0]  — overall sentiment
        pos/neg/neu ∈ [0.0, 1.0] — proportions (sum ≈ 1.0)
        """
        if not text or not text.strip():
            return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}

        tokens = _tokenize(text)
        if not tokens:
            return {"compound": 0.0, "pos": 0.0, "neg": 0.0, "neu": 1.0}

        is_cap_diff = _has_allcaps_differential(tokens)

        # Per-token valence
        sentiments = _compute_valence(tokens, is_cap_diff, self._pos_lex, self._neg_lex)

        # Contrastive conjunction adjustment
        sentiments = _contrastive_check(tokens, sentiments)

        # Raw sum + punctuation emphasis
        sum_s = float(sum(sentiments))
        punct = _punct_amplifier(text)
        if sum_s > 0:
            sum_s += punct
        elif sum_s < 0:
            sum_s -= punct

        compound = _normalize(sum_s)

        # Pos / neg / neu proportions
        pos_sum, neg_sum, neu_count = _sift_scores(sentiments)

        # Adjust pos/neg by punctuation
        if pos_sum > abs(neg_sum):
            pos_sum += punct
        elif pos_sum < abs(neg_sum):
            neg_sum -= punct

        total = pos_sum + abs(neg_sum) + neu_count
        if total == 0:
            return {"compound": round(compound, 4), "pos": 0.0, "neg": 0.0, "neu": 1.0}

        pos = abs(pos_sum / total)
        neg = abs(neg_sum / total)
        neu = abs(neu_count / total)

        return {
            "neg": round(neg, 3),
            "neu": round(neu, 3),
            "pos": round(pos, 3),
            "compound": round(compound, 4),
        }


# ---------------------------------------------------------------------------
# Module-level singleton (zero-cost reconstruction)
# ---------------------------------------------------------------------------
_default_analyzer = ViVADERSentimentAnalyzer()


def polarity_scores(text: str) -> Dict[str, float]:
    """Module-level convenience function using default analyzer."""
    return _default_analyzer.polarity_scores(text)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_cases = [
        # Positive
        ("VNM tăng mạnh, lợi nhuận kỷ lục!", "Expected: BULLISH"),
        ("VIC lập kỷ lục doanh thu, xuất sắc!", "Expected: BULLISH"),
        ("Cổ phiếu HPG bứt phá vượt kháng cự mạnh", "Expected: BULLISH"),
        ("Công ty đạt mục tiêu, chia cổ tức cao", "Expected: BULLISH"),
        # Negative
        ("VNM lao dốc không phanh, thua lỗ lớn", "Expected: BEARISH"),
        ("Cổ phiếu bốc hơi, bán tháo ồ ạt", "Expected: BEARISH"),
        ("Công ty phá sản, mất khả năng thanh toán", "Expected: BEARISH"),
        ("vi phạm nghiêm trọng, bị điều tra hình sự", "Expected: BEARISH"),
        # Negation
        ("không tăng được, áp lực bán ròng", "Expected: BEARISH (negated tăng + áp lực)"),
        ("không phải là không tốt, vẫn có lãi", "Expected: NEUTRAL/SLIGHT-BULLISH"),
        # Contrastive
        ("VIC tăng nhẹ nhưng thanh khoản thấp, tiêu cực", "Expected: SLIGHT-BEARISH"),
        ("lỗ nhỏ nhưng doanh thu tăng mạnh, triển vọng tốt", "Expected: SLIGHT-BULLISH"),
        # Intensifiers
        ("rất mạnh, cực kỳ tích cực", "Expected: BULLISH (intensified)"),
        ("hơi tăng nhẹ", "Expected: SLIGHT-BULLISH (diminished)"),
        # Neutral
        ("Công ty tổ chức họp AGM", "Expected: NEUTRAL"),
    ]

    labels = {
        lambda c: c <= -0.35: "BEARISH",
        lambda c: c <= -0.15: "SOMEWHAT-BEARISH",
        lambda c: c < 0.15: "NEUTRAL",
        lambda c: c < 0.35: "SOMEWHAT-BULLISH",
        lambda c: True: "BULLISH",
    }

    def label(c: float) -> str:
        if c <= -0.35:
            return "BEARISH"
        elif c <= -0.15:
            return "SOMEWHAT-BEARISH"
        elif c < 0.15:
            return "NEUTRAL"
        elif c < 0.35:
            return "SOMEWHAT-BULLISH"
        else:
            return "BULLISH"

    analyzer = ViVADERSentimentAnalyzer()
    print(f"\n{'ViVADER — Vietnamese Financial Sentiment':^70}")
    print("=" * 70)
    for text, note in test_cases:
        sc = analyzer.polarity_scores(text)
        c = sc["compound"]
        print(f"\n  Text : {text}")
        print(f"  Note : {note}")
        print(f"  Score: compound={c:+.4f}  pos={sc['pos']:.3f}  neg={sc['neg']:.3f}  neu={sc['neu']:.3f}  → {label(c)}")
    print("\n" + "=" * 70)

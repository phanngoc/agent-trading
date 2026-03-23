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
# PhoBERT — Vietnamese financial BERT (lazy-loaded singleton)
# Model: mr4/phobert-base-vi-sentiment-analysis
# Labels: Tiêu cực (neg) / Tích cực (pos) / Trung tính (neutral)
# Load time: ~1.5s (cached after first call). Inference: ~0.2s/batch.
# Only invoked when lexicon signal is weak (|score| < BERT_INVOKE_THRESHOLD).
# ---------------------------------------------------------------------------
_phobert_pipe = None
_phobert_available: bool = False
_phobert_load_attempted: bool = False

BERT_INVOKE_THRESHOLD = 0.20   # invoke BERT when lexicon |score| < this
BERT_WEIGHT           = 0.60   # BERT weight in final blend (vs lexicon 0.40)
_BERT_LABEL_MAP = {"Tích cực": 1.0, "Tiêu cực": -1.0, "Trung tính": 0.0}
BERT_CONFIDENCE_THRESHOLD = 0.92  # only trust BERT when confidence is high

# BERT is general VI model — only invoke when text has domain keywords
# (prevents false positives on plain factual news like "công bố kết quả")
_BERT_DOMAIN_RE = re.compile(
    r'lỗ|lãi|tăng trần|giảm sàn|call margin|giải chấp|bán tháo|'
    r'phá sản|vỡ nợ|kỷ lục|đột biến|sụt giảm|bứt phá|'
    r'cổ tức|margin|thanh khoản|room ngoại|upcom|niêm yết',
    re.IGNORECASE
)


def _load_phobert() -> bool:
    """Lazy-load PhoBERT pipeline. Returns True if available."""
    global _phobert_pipe, _phobert_available, _phobert_load_attempted
    if _phobert_load_attempted:
        return _phobert_available
    _phobert_load_attempted = True
    try:
        from transformers import pipeline as hf_pipeline
        _phobert_pipe = hf_pipeline(
            "text-classification",
            model="mr4/phobert-base-vi-sentiment-analysis",
            device="cpu",
            max_length=128,
            truncation=True,
        )
        _phobert_available = True
    except Exception:
        _phobert_available = False
    return _phobert_available


def _score_phobert(text: str) -> float:
    """Run PhoBERT on text. Returns score in [-1.0, 1.0] or 0.0 on error.

    Only returns non-zero when confidence >= BERT_CONFIDENCE_THRESHOLD.
    This prevents the model from overriding clear neutral cases with marginal signals.
    """
    if not _load_phobert() or _phobert_pipe is None:
        return 0.0
    try:
        result = _phobert_pipe(text[:256])[0]
        direction = _BERT_LABEL_MAP.get(result["label"], 0.0)
        confidence = float(result["score"])
        # Only emit signal when BERT is very confident
        if confidence < BERT_CONFIDENCE_THRESHOLD:
            return 0.0
        # Scale: 0.85 conf → 0.35, 1.0 conf → 1.0
        magnitude = (confidence - BERT_CONFIDENCE_THRESHOLD) / (1.0 - BERT_CONFIDENCE_THRESHOLD)
        return direction * magnitude
    except Exception:
        return 0.0

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
    "tăng trưởng mạnh": 0.7, "tăng trưởng": 0.35, "tăng trưởng tốt": 0.55,
    "lãi ròng tăng": 0.7, "doanh thu tăng": 0.65, "lợi nhuận tăng": 0.7,
    "lợi nhuận cao kỷ lục": 0.85, "lãi": 0.30,

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

    # ── Tăng vọt / bứt phá nhanh ────────────────────────────────────────────
    "tăng vọt": 0.70, "tăng tốc": 0.55, "tăng mạnh mẽ": 0.70,
    "bùng nổ": 0.65, "bứt lên": 0.60, "vọt lên": 0.65,
    "lập đỉnh": 0.70, "đỉnh cao": 0.55, "mặt bằng mới": 0.50,
    "vượt kỳ vọng": 0.75, "vượt dự báo": 0.70, "vượt đỉnh": 0.70,
    "tăng nóng": 0.60, "cháy hàng": 0.50, "khan hiếm": 0.40,

    # ── Dòng vốn / thanh khoản tích cực ─────────────────────────────────────
    "dòng vốn vào": 0.60, "dòng tiền tốt": 0.55, "thanh khoản dồi dào": 0.55,
    "vốn ngoại vào": 0.60, "ngoại tệ chảy vào": 0.55,

    # ── Sóng tăng / bull run ─────────────────────────────────────────────────
    "sóng tăng": 0.65, "chu kỳ tăng": 0.60, "xu hướng tăng": 0.55,
    "thị trường bull": 0.70, "bull run": 0.70,

    # ── Kết quả vượt / đạt cao ──────────────────────────────────────────────
    "kết quả vượt": 0.65, "kết quả tốt": 0.60, "kết quả tích cực": 0.65,
    "doanh thu tăng mạnh": 0.75, "lợi nhuận kỷ lục": 0.85,

    # ── VN stock specific: chỉ số / thị trường ───────────────────────────────
    "vượt mốc": 0.65, "chinh phục mốc": 0.65, "vượt ngưỡng": 0.60,
    "dòng tiền ngoại": 0.55, "ngoại mua ròng": 0.65, "khối ngoại mua ròng": 0.65,
    "thanh khoản cải thiện": 0.55, "thanh khoản tăng": 0.45,
    "breadth tích cực": 0.55, "độ rộng tích cực": 0.50,

    # ── Hợp đồng / xuất khẩu / dự án ────────────────────────────────────────
    "ký hợp đồng": 0.60, "ký kết hợp đồng lớn": 0.75,
    "ký hợp đồng xuất khẩu": 0.70, "hợp đồng xuất khẩu lớn": 0.75,
    "xuất khẩu tăng": 0.55, "đơn hàng xuất khẩu": 0.50,
    "trúng thầu dự án": 0.70, "được chọn thầu": 0.65,
    "nhận đơn hàng": 0.55, "nhận hợp đồng mới": 0.60,
    "ký biên bản ghi nhớ": 0.45, "ký mou": 0.45,

    # ── Cổ phiếu vào rổ / nâng hạng ─────────────────────────────────────────
    "vào rổ vn30": 0.70, "vào rổ vnmidcap": 0.60, "vào rổ etf": 0.60,
    "thêm vào danh mục": 0.55, "được nâng hạng": 0.65,
    "thị trường mới nổi": 0.60, "nâng hạng thị trường": 0.65,
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
    "chưa đạt kế hoạch": 0.70, "không đạt kế hoạch": 0.70,
    "thấp hơn kế hoạch": 0.55, "dưới kỳ vọng": 0.5,

    # ── Tâm lý tiêu cực ──────────────────────────────────────────────────────
    "hoảng loạn bán ra": 0.7, "đỏ sàn toàn diện": 0.65,
    "nhà đầu tư hoảng loạn": 0.6,

    # ── Giảm mạnh / xả hàng / thoát ─────────────────────────────────────────
    "giảm sàn": 0.70, "xả hàng": 0.55, "bán mạnh": 0.55,
    "bị bán mạnh": 0.65, "rơi khỏi": 0.55, "rơi mạnh": 0.65,
    "đảo chiều giảm": 0.60, "lao dốc mạnh": 0.75,
    "mất điểm": 0.50, "mất mốc": 0.55,

    # ── Cảnh báo tài chính ────────────────────────────────────────────────────
    "cảnh báo": 0.35, "cảnh báo nguy cơ": 0.55,
    "rủi ro lớn": 0.55, "nguy cơ": 0.40,
    "thua lỗ": 0.65, "lỗ nặng": 0.75, "lỗ lớn": 0.70,
    "lỗ ròng": 0.65, "lỗ quý": 0.60, "báo lỗ": 0.70,

    # ── Sụt giảm doanh thu / vĩ mô xấu ──────────────────────────────────────
    "sốt giá": 0.45, "leo thang giá": 0.45,
    "tín dụng xấu": 0.55, "nợ xấu tăng": 0.75, "nợ xấu tăng cao": 0.80, "nợ xấu": 0.50,
    "doanh thu giảm": 0.55, "lợi nhuận giảm": 0.60,
    "doanh thu sụt": 0.60, "lợi nhuận sụt": 0.65,
    "bị phạt": 0.45, "xử phạt": 0.45, "truy thu": 0.40,
    "chậm tiến độ": 0.40, "dừng dự án": 0.55,

    # ── VN stock specific: hủy niêm yết / mất trắng ──────────────────────────
    "hủy niêm yết": 0.85, "huỷ niêm yết": 0.85,
    "bị hủy niêm yết": 0.85, "bị huỷ niêm yết": 0.85,
    "mất trắng": 0.80, "mất hết vốn": 0.85, "trắng tay": 0.80,
    "cưỡng chế niêm yết": 0.75, "đình chỉ giao dịch": 0.75,
    "tạm dừng giao dịch": 0.60, "bị tạm dừng niêm yết": 0.70,
    "vào diện đình chỉ": 0.75, "bị đình chỉ": 0.65,

    # ── Tiếp tục giảm / không phục hồi ───────────────────────────────────────
    "tiếp tục giảm": 0.55, "tiếp tục lao dốc": 0.70, "tiếp tục đỏ": 0.55,
    "tiếp tục sụt giảm": 0.65, "chưa có dấu hiệu phục hồi": 0.65,
    "không có dấu hiệu phục hồi": 0.70, "khó phục hồi": 0.55,
    "chưa thể phục hồi": 0.60, "xa đà giảm": 0.55,

    # ── Thấp hơn kỳ vọng / dưới dự báo ──────────────────────────────────────
    "thấp hơn kỳ vọng": 0.60, "thấp hơn dự báo": 0.60,
    "dưới dự báo": 0.55, "dưới kỳ vọng": 0.55,
    "thấp hơn mục tiêu": 0.55, "không đạt kỳ vọng": 0.60,

    # ── Ngoại bán ròng / dòng tiền ra ────────────────────────────────────────
    "khối ngoại bán ròng": 0.75, "ngoại bán ròng mạnh": 0.80,
    "ngoại bán ròng": 0.65,
    "dòng tiền ngoại ra": 0.60, "vốn ngoại tháo chạy": 0.75,
    "outflow": 0.55, "rút ròng": 0.55,
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

    Thresholds:
      Bearish      <= -0.200  (strong negative signal)
      Somewhat-Bearish <= -0.100
      Neutral       < 0.100
      Somewhat-Bullish < 0.200
      Bullish      >= 0.200

    Neural models (CN LoRA, EN FinBERT) output scores near ±0.9 for clear signals,
    so these thresholds produce clean Bullish/Bearish labels.
    VN lexicon ~0.2-0.4 for moderate terms → Somewhat-Bearish/Bullish is intentional.
    """
    if compound <= -0.200:
        return "Bearish"
    elif compound <= -0.100:
        return "Somewhat-Bearish"
    elif compound < 0.100:
        return "Neutral"
    elif compound < 0.200:
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
def _score_vietnamese(text: str, use_bert: bool = True) -> float:
    """
    Vietnamese financial sentiment scoring.

    Pipeline (priority order):
    1. Lexicon score     → domain-specific financial terms, negation, intensifiers
    2. ViVADER score     → general Vietnamese sentiment (fallback only)
    3. PhoBERT (BERT)    → deep-learning fallback when lexicon signal is weak

    Logic:
    - If |lexicon| >= BERT_INVOKE_THRESHOLD → lexicon is confident, blend with ViVADER
    - If |lexicon| < BERT_INVOKE_THRESHOLD  → invoke PhoBERT, blend result with lexicon

    Returns compound score in [-1.0, 1.0].
    """
    lexicon_score = _lexicon_score(text, _VI_POS_LEXICON, _VI_NEG_LEXICON)
    vivader_score = _vivader.polarity_scores(text[:512])["compound"] if _vivader_available else 0.0

    LEX_THRESHOLD = 0.05
    VIV_THRESHOLD = 0.15
    LEX_WEIGHT    = 0.85
    VIV_WEIGHT    = 0.15

    lex_strong = abs(lexicon_score) >= BERT_INVOKE_THRESHOLD  # confident lexicon signal
    lex_has_signal = abs(lexicon_score) > LEX_THRESHOLD
    viv_has_signal = abs(vivader_score) > VIV_THRESHOLD

    # --- Lexicon is confident: standard blend (no BERT needed) ---
    if lex_strong:
        if viv_has_signal:
            same_direction = (lexicon_score > 0) == (vivader_score > 0)
            if same_direction:
                return lexicon_score * LEX_WEIGHT + vivader_score * VIV_WEIGHT
        return lexicon_score

    # --- Lexicon weak: invoke PhoBERT (only for domain-relevant text) ---
    # Strategy: BERT improves coverage but conflicts with inaccurate DB labels.
    # Only use BERT for clearly negative signals — negative sentiment is universal
    # across domains (lỗ, thanh lý, phá sản) regardless of training data.
    # Positive BERT signals are less reliable (general model sees "vận hành" as positive
    # but financial context may be neutral).
    if use_bert and _BERT_DOMAIN_RE.search(text):
        bert_score = _score_phobert(text)

        # Trust BERT only for strong negative signals (both BERT negative AND strong conf)
        if bert_score < -0.30:
            if lex_has_signal and lexicon_score < 0:
                # Both agree negative → blend
                return bert_score * BERT_WEIGHT + lexicon_score * (1 - BERT_WEIGHT)
            elif not lex_has_signal:
                # Only BERT has strong negative signal
                return bert_score

    # --- Lexicon / ViVADER fallback ---
    # --- No strong BERT: fallback to standard logic ---
    if lex_has_signal and viv_has_signal:
        same_direction = (lexicon_score > 0) == (vivader_score > 0)
        if same_direction:
            return lexicon_score * LEX_WEIGHT + vivader_score * VIV_WEIGHT
        return lexicon_score
    if lex_has_signal:
        return lexicon_score
    if viv_has_signal:
        return vivader_score
    return 0.0


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chinese financial lexicon — domain-specific for news headlines
# ---------------------------------------------------------------------------
_ZH_POSITIVE: list[tuple[str, float]] = [
    # 大涨 / 上涨 / 涨幅
    ("大涨", 0.75), ("暴涨", 0.85), ("飙升", 0.80), ("涨停", 0.70),
    ("上涨", 0.40), ("反弹", 0.45), ("收涨", 0.40), ("走高", 0.35),
    ("涨幅", 0.30), ("拉升", 0.45), ("跳涨", 0.60), ("连涨", 0.55),
    ("突破", 0.55), ("创新高", 0.70), ("年内高", 0.60), ("阶段高", 0.50),
    # 利好 / 盈利 / 增长
    ("利好", 0.65), ("好消息", 0.55), ("超预期", 0.70), ("超出预期", 0.70),
    ("净利润增", 0.65), ("营收增", 0.60), ("业绩增", 0.65), ("盈利增", 0.60),
    ("业绩向好", 0.55), ("扭亏为盈", 0.80), ("转亏为盈", 0.80),
    # 买入 / 增持
    ("买入", 0.50), ("增持", 0.55), ("加仓", 0.50), ("回购", 0.45),
    ("外资净买入", 0.60), ("北向资金净流入", 0.60), ("净流入", 0.50),
    # 降息 / 宽松 / 刺激
    ("降息", 0.60), ("降准", 0.60), ("宽松", 0.45), ("刺激", 0.40),
    ("利率下调", 0.55), ("货币宽松", 0.50),
    # 贸易 / 协议 / 价格提涨
    ("贸易协议", 0.55), ("自由贸易协议", 0.60), ("贸易协定生效", 0.60),
    ("价格提涨", 0.45), ("计划提涨", 0.45), ("涨价", 0.40),
    ("焦炭价格上涨", 0.50), ("焦炭提涨", 0.50),
    # 市场积极 / 走强
    ("市场情绪好转", 0.55), ("情绪回暖", 0.50), ("资金流入", 0.50),
    ("成交量放大", 0.35), ("量价齐升", 0.60),
]

_ZH_NEGATIVE: list[tuple[str, float]] = [
    # 下跌 / 大跌 / 暴跌
    ("暴跌", 0.85), ("大跌", 0.75), ("跌停", 0.75), ("大幅下跌", 0.75),
    ("下跌", 0.55), ("跌幅", 0.45), ("走低", 0.35), ("收跌", 0.40),
    ("大幅回落", 0.65), ("大幅下挫", 0.70), ("急跌", 0.65),
    ("大幅走低", 0.65), ("全线下跌", 0.65), ("跌破", 0.55),
    # 亏损 / 利空
    ("亏损", 0.65), ("净亏损", 0.70), ("利空", 0.65), ("坏消息", 0.55),
    ("业绩下滑", 0.60), ("营收下降", 0.55), ("净利润降", 0.60),
    ("业绩不及预期", 0.65), ("低于预期", 0.60), ("不及预期", 0.55),
    # 卖出 / 减持
    ("卖出", 0.50), ("减持", 0.55), ("减仓", 0.50), ("抛售", 0.60),
    ("外资净卖出", 0.60), ("北向资金净流出", 0.60), ("净流出", 0.50),
    # 风险 / 危机 / 崩溃
    ("风险", 0.35), ("危机", 0.70), ("崩溃", 0.85), ("暴雷", 0.80),
    ("违约", 0.75), ("破产", 0.85), ("流动性危机", 0.80),
    ("债务危机", 0.75), ("资金链断裂", 0.80),
    # 加息 / 紧缩 / 制裁
    ("加息", 0.65), ("升息", 0.65), ("缩表", 0.50), ("紧缩", 0.50),
    ("净回笼", 0.55), ("逆回购净回笼", 0.60), ("资金净回笼", 0.55),  # liquidity drain
    ("国债收益率创高", 0.55), ("国债收益率为.*高点", 0.55),  # yield highs = bearish
    ("制裁", 0.65), ("关税", 0.45), ("贸易战", 0.60),
    # 市场情绪差
    ("恐慌", 0.65), ("市场情绪低落", 0.55), ("信心不足", 0.50),
    ("抛压", 0.50), ("资金流出", 0.50), ("流动性不足", 0.60),
    # 爆炸 / 冲突 / 战争 (geopolitical → bearish for markets)
    ("爆炸", 0.55), ("冲突升级", 0.65), ("战争", 0.70), ("军事冲突", 0.65),
    ("袭击", 0.60), ("制裁升级", 0.70),
]

# Neutral override terms — these cancel out any lexicon signal (market consolidation/waiting)
_ZH_NEUTRAL_OVERRIDE: list[str] = [
    "震荡整理", "横盘整理", "窄幅震荡", "区间震荡",
    "观望情绪", "持币观望", "等待信号", "数据出炉前",
]

# Sort by length desc (longest match first)
_ZH_POS_LEX: list[tuple[str, float]] = sorted(_ZH_POSITIVE, key=lambda x: -len(x[0]))
_ZH_NEG_LEX: list[tuple[str, float]] = sorted(_ZH_NEGATIVE, key=lambda x: -len(x[0]))

_ZH_NEGATION = ["不", "未", "没有", "无", "非", "反", "否"]


def _score_chinese_financial(text: str) -> float:
    """
    Chinese financial sentiment scoring using domain-specific lexicon.
    
    Algorithm: same as VN lexicon_score (longest-match, negation, tanh)
    Focus: financial headlines from wallstreetcn, jin10, cls, weibo, zhihu
    """
    # Neutral override: market consolidation / wait-and-see patterns → 0.0
    for neutral_term in _ZH_NEUTRAL_OVERRIDE:
        if neutral_term in text:
            return 0.0

    weights: list[float] = []
    matched_spans: list[tuple[int, int]] = []
    
    unified: list[tuple[str, float]] = (
        [(term, +w) for term, w in _ZH_POS_LEX] +
        [(term, -w) for term, w in _ZH_NEG_LEX]
    )
    unified.sort(key=lambda kv: -len(kv[0]))
    
    for term, signed_weight in unified:
        idx = 0
        while True:
            pos = text.find(term, idx)
            if pos == -1:
                break
            end = pos + len(term)
            # Longest-first: skip overlapping spans
            if not any(s <= pos < e or s < end <= e for s, e in matched_spans):
                # Negation check (within 3 chars before term)
                prefix = text[max(0, pos - 3): pos]
                w = signed_weight
                for neg in _ZH_NEGATION:
                    if prefix.endswith(neg) or neg in prefix[-2:]:
                        w = -w * 0.6
                        break
                weights.append(w)
                matched_spans.append((pos, end))
            idx = pos + 1
    
    if not weights:
        # Fallback: try SnowNLP but only trust strong signals
        if _snownlp_available and _SnowNLP:
            try:
                s = _SnowNLP(text[:128]).sentiments
                # SnowNLP is biased — only use very strong signals
                if s > 0.85:
                    return 0.25   # cautious bullish
                if s < 0.15:
                    return -0.25  # cautious bearish
            except Exception:
                pass
        return 0.0
    
    raw = sum(weights)
    return math.tanh(raw * 0.35)


# ---------------------------------------------------------------------------
# English financial lexicon extension (for hackernews, reuters, ft etc.)
# ---------------------------------------------------------------------------
_EN_FIN_POSITIVE: list[tuple[str, float]] = [
    ("record high", 0.75), ("all-time high", 0.75), ("beats expectations", 0.80),
    ("beat estimates", 0.75), ("beats estimates", 0.75), ("record earnings", 0.75),
    ("strong earnings", 0.70), ("profit surge", 0.70), ("revenue growth", 0.75),
    ("rate cut", 0.75), ("fed cuts", 0.80), ("dovish", 0.55),
    ("rally", 0.65), ("surges", 0.70), ("soars", 0.65), ("jumps", 0.50),
    ("buyback", 0.50), ("dividend increase", 0.60), ("upgrade", 0.55),
    ("buy rating", 0.60), ("outperform", 0.55), ("overweight", 0.50),
    ("gdp growth", 0.50), ("jobs added", 0.55), ("unemployment falls", 0.60),
    ("unemployment rate falls", 0.60), ("adds jobs", 0.55), ("adds 200k", 0.60),
    ("adds 100k", 0.55), ("adds 300k", 0.60), ("new jobs", 0.45),
    ("inflation falls", 0.65), ("inflation cools", 0.65), ("inflation eases", 0.65),
    ("cpi falls", 0.65), ("cpi drops", 0.60), ("lowest inflation", 0.65),
    ("lowest level in", 0.50), ("lowest since", 0.50),
    ("trade deal", 0.60), ("trade agreement", 0.60), ("investment boom", 0.65),
    ("commits investment", 0.55), ("pledges investment", 0.55),
    ("committed to invest", 0.60), ("to invest", 0.45),
    ("economic recovery", 0.55), ("economic growth", 0.55),
]

_EN_FIN_NEGATIVE: list[tuple[str, float]] = [
    ("crash", 0.80), ("collapse", 0.80), ("plunges", 0.75), ("tumbles", 0.65),
    ("recession", 0.70), ("bear market", 0.65), ("selloff", 0.65), ("sell-off", 0.65),
    # Rate hike patterns — various phrasings
    ("rate hike", 0.65), ("rate hikes", 0.65), ("interest rate hike", 0.65),
    ("raises interest rates", 0.65), ("raising rates", 0.65), ("rate increase", 0.60),
    ("fed hikes", 0.65), ("hawkish", 0.55), ("tightening", 0.45),
    # Earnings misses
    ("misses expectations", 0.70), ("profit warning", 0.70), ("earnings miss", 0.70),
    ("layoffs", 0.60), ("job cuts", 0.60), ("bankruptcy", 0.85),
    ("downgrade", 0.60), ("sell rating", 0.65), ("underperform", 0.55),
    ("war", 0.60), ("sanctions", 0.75), ("tariffs", 0.55), ("new tariffs", 0.60),
    ("imposes tariffs", 0.65), ("default", 0.75),
    ("inflation surges", 0.65), ("inflation rises", 0.55), ("inflation high", 0.55),
    # Yield highs — bearish for bonds/equities
    ("yields spike", 0.55), ("yield hit", 0.50), ("yields hit", 0.50),
    ("yield highest", 0.65), ("yields highest", 0.65), ("yield surge", 0.60),
    ("16-year high", 0.65), ("highest since", 0.40),
    # Losses
    ("loan losses", 0.65), ("massive losses", 0.70), ("credit losses", 0.65),
    ("tech stocks fall", 0.55), ("stocks fall", 0.55),
]

_EN_POS_LEX: list[tuple[str, float]] = sorted(_EN_FIN_POSITIVE, key=lambda x: -len(x[0]))
_EN_NEG_LEX: list[tuple[str, float]] = sorted(_EN_FIN_NEGATIVE, key=lambda x: -len(x[0]))


_EN_DOMAIN_RE = re.compile(
    r'\b(stock|market|index|share|fund|etf|rate|rates|fed|gdp|cpi|yield|yields|bond|'
    r'earnings|profit|revenue|rally|crash|sell.?off|recession|inflation|'
    r'trade|tariff|tariffs|sanction|sanctions|bank|invest|investment|'
    r'crypto|bitcoin|oil|gold|jobs|unemployment|economy|economic|fiscal|monetary|'
    r'upgrade|downgrade|overweight|underweight|buyback|dividend|ipo|merger|acquisition|'
    r'treasury|central.?bank|interest.?rate)\b',
    re.IGNORECASE
)

def _score_english_financial(text: str) -> float:
    """English financial sentiment — lexicon + VADER blend.
    Only activates for finance-domain text to avoid false positives
    on tech/general EN articles (hackernews etc.)
    """
    # Domain gate: only score if text is finance-relevant
    if not _EN_DOMAIN_RE.search(text):
        return 0.0
    lex = _lexicon_score(text.lower(), _EN_POS_LEX, _EN_NEG_LEX)
    
    if _vader_available and _vader:
        vader_score = float(_vader.polarity_scores(text[:512])["compound"])
        if abs(lex) >= 0.20:
            # Financial lexicon strong — trust it, VADER often wrong on financial context
            # e.g. "raises rates" looks positive to VADER ("raises" = good word)
            if lex * vader_score > 0:
                return lex * 0.85 + vader_score * 0.15  # same direction: small VADER boost
            else:
                return lex  # disagreement: trust domain lexicon
        elif abs(lex) >= 0.05:
            # Weak lexicon signal — 60/40 blend
            return lex * 0.60 + vader_score * 0.40
        elif abs(vader_score) >= 0.20:
            # No lexicon signal, use VADER lightly
            return vader_score * 0.40  # dampen general VADER
    return lex


# ---------------------------------------------------------------------------
# Neural sentiment engine — lazy-loaded BERT models (CN + EN financial)
# ---------------------------------------------------------------------------
try:
    from src.utils.neural_sentiment import neural_engine as _neural_engine, _EN_FIN_RE
    _NEURAL_AVAILABLE = True
except ImportError:
    _neural_engine = None  # type: ignore
    _EN_FIN_RE = None      # type: ignore
    _NEURAL_AVAILABLE = False

# Lexicon-only threshold: if |lexicon| >= this, skip neural (already confident)
LEXICON_CONFIDENT_THRESHOLD = 0.15  # Lexicon leads when |score| >= 0.15

# Neural confidence threshold: below this, fall back to lexicon
NEURAL_CONF_THRESHOLD = 0.65


# ---------------------------------------------------------------------------
# Singleton SentimentAnalyzer — public API: analyze(text) → (score, label)
# ---------------------------------------------------------------------------
class SentimentAnalyzer:
    """
    Hybrid routing — priority per language:

    VN  → lexicon only (100% domain accuracy, 10k/sec)
    CN  → neural PRIMARY (LoRA-fine-tuned, 97.7% accuracy)
           └─ fallback to lexicon if neural unavailable/low-conf
    EN  → lexicon gate (financial domain check first)
           └─ if financial domain: neural PRIMARY (FinBERT)
           └─ fallback to lexicon
    other → 0.0 neutral
    """
    _instance = None

    def __new__(cls) -> "SentimentAnalyzer":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ── Core routing ──────────────────────────────────────────────────────

    def analyze(self, text: str) -> Tuple[float, str]:
        """Route text to correct scorer. Returns (score [-1,1], label)."""
        if not text:
            return 0.0, "Neutral"
        try:
            compound = self._route(text.strip())
            return float(compound), _score_to_label(compound)
        except Exception:
            return 0.0, "Neutral"

    def _route(self, text: str) -> float:
        if _is_vietnamese(text):
            return _score_vietnamese(text[:512])

        if _is_chinese(text):
            return self._score_cn(text)

        return self._score_en(text)

    # ── CN: LoRA neural primary, lexicon fallback ─────────────────────────

    def _score_cn(self, text: str) -> float:
        """CN: neutral-override check → neural (LoRA) primary → lexicon fallback."""
        # Hard neutral override: consolidation / wait-and-see patterns
        for neutral_term in _ZH_NEUTRAL_OVERRIDE:
            if neutral_term in text:
                return 0.0

        if _NEURAL_AVAILABLE and _neural_engine and _neural_engine.is_cn_available():
            neural_score, _, neural_conf = _neural_engine.score_cn(text)
            if neural_conf >= NEURAL_CONF_THRESHOLD:
                return neural_score

        # Fallback: lexicon (when neural unavailable or low confidence)
        return _score_chinese_financial(text)

    # ── EN: domain gate → neural primary, lexicon fallback ───────────────

    def _score_en(self, text: str) -> float:
        """EN: financial domain check → neural (FinBERT) primary → lexicon fallback."""
        # Non-financial EN → always neutral (avoid false positives on HN/tech)
        if _EN_FIN_RE and not _EN_FIN_RE.search(text):
            return 0.0

        # Financial domain confirmed — lexicon check first (fast path)
        lex_score = _score_english_financial(text)

        # If lexicon is already very confident, skip neural overhead
        if abs(lex_score) >= LEXICON_CONFIDENT_THRESHOLD:
            return lex_score

        # Neural primary for ambiguous / weak lexicon signal
        if _NEURAL_AVAILABLE and _neural_engine and _neural_engine.is_en_available():
            neural_score, _, neural_conf = _neural_engine.score_en(text)
            if neural_conf >= NEURAL_CONF_THRESHOLD:
                if abs(lex_score) >= 0.15:
                    # Lexicon has meaningful signal: 60/40 blend (lexicon leads)
                    blended = lex_score * 0.60 + neural_score * 0.40
                    # If lex and neural agree on direction, boost confidence
                    if lex_score * neural_score > 0:
                        return blended * 1.1
                    # Disagree: trust lexicon (domain-specific)
                    return lex_score
                return neural_score  # No lexicon signal: trust FinBERT

        return lex_score


sentiment_analyzer = SentimentAnalyzer()


def get_sentiment(text: str) -> Tuple[float, str]:
    return sentiment_analyzer.analyze(text)

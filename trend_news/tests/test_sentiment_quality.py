"""
test_sentiment_quality.py — Đánh giá chất lượng sentiment analysis cho tin tức chứng khoán VN.

Chạy:
    cd trend_news
    python -m pytest tests/test_sentiment_quality.py -v
    # hoặc chạy thẳng:
    python tests/test_sentiment_quality.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.sentiment import get_sentiment


# ── Test cases ───────────────────────────────────────────────────────────────
# Format: (title, expected_label)
# expected_label: "positive" | "negative" | "neutral"
# Threshold: score > 0.15 → positive, score < -0.15 → negative, else neutral

TEST_CASES = [

    # ── Cổ đông lớn / giao dịch nội bộ ─────────────────────────────────────
    ("Dragon Capital mua vào 5 triệu cổ phiếu MWG",             "positive"),
    ("Quỹ ngoại mua ròng 10 triệu cổ phiếu HPG",                "positive"),
    ("Cổ đông lớn đăng ký mua vào 50 triệu cổ phiếu",           "positive"),
    ("Insiders mua vào mạnh, kỳ vọng cổ phiếu tăng",            "positive"),
    ("Dragon Capital không còn là cổ đông lớn MWG sau khi bán ra 700.000 cổ phiếu", "negative"),
    ("Cổ đông lớn bán ra toàn bộ cổ phần, thoái vốn khỏi công ty", "negative"),
    ("Quỹ ngoại bán ròng liên tục 5 phiên, rút khỏi MWG",        "negative"),

    # ── Lợi nhuận / doanh thu ───────────────────────────────────────────────
    ("Hòa Phát lập kỷ lục lợi nhuận quý 1 năm 2026",            "positive"),
    ("VNM tăng trưởng mạnh doanh thu xuất khẩu quý 4",          "positive"),
    ("FPT báo lãi ròng tăng 35% so với cùng kỳ",                "positive"),
    ("ACB đạt lợi nhuận cao kỷ lục trong quý",                  "positive"),
    ("MWG lỗ nặng, cổ phiếu giảm sâu sau kết quả kinh doanh",   "negative"),
    ("Doanh thu HPG sụt giảm 20% do giá thép lao dốc",          "negative"),
    ("Công ty ghi nhận thua lỗ lớn nhất từ trước đến nay",       "negative"),

    # ── Kỹ thuật / thị trường ───────────────────────────────────────────────
    ("HPG được nâng hạng, nhà đầu tư nước ngoài mua ròng",      "positive"),
    ("Cổ phiếu bứt phá, vượt đỉnh lịch sử với thanh khoản cao", "positive"),
    ("VNIndex hồi phục mạnh, nhiều cổ phiếu tăng trần",         "positive"),
    ("HPG bị điều tra vi phạm, cổ phiếu lao dốc ngay sau đó",   "negative"),
    ("Thị trường giảm mạnh, nhiều cổ phiếu bán tháo ồ ạt",      "negative"),
    ("VNIndex lao dốc, thanh khoản cạn kiệt phiên cuối tuần",    "negative"),
    ("Cổ phiếu đỏ sàn toàn diện, nhà đầu tư hoảng loạn bán ra", "negative"),

    # ── M&A / hợp tác ───────────────────────────────────────────────────────
    ("Vingroup ký kết hợp đồng chiến lược, mở rộng thị trường",  "positive"),
    ("FPT thắng thầu dự án AI lớn tại Nhật Bản",                "positive"),
    ("Thương vụ M&A thất bại, hai bên không đạt được thỏa thuận","negative"),

    # ── Vĩ mô ───────────────────────────────────────────────────────────────
    ("NHNN hạ lãi suất, hỗ trợ tăng trưởng tín dụng",           "positive"),
    ("Lạm phát tăng vọt, áp lực chi phí lên toàn ngành",        "negative"),

    # ── Trung tính ──────────────────────────────────────────────────────────
    ("MWG công bố kết quả kinh doanh quý 4",                    "neutral"),
    ("Hòa Phát có thêm nhà máy thép mới hoạt động ở miền Nam",  "neutral"),
    ("Hòa Phát chính thức vận hành nhà máy ống thép 410.000 tấn/năm", "neutral"),
    ("VCB tổ chức đại hội cổ đông thường niên",                 "neutral"),
    ("Chứng khoán SSI ra mắt sản phẩm mới cho nhà đầu tư cá nhân", "neutral"),

    # ── Negation edge cases ──────────────────────────────────────────────────
    ("MWG không còn lỗ, đã quay lại có lãi",                    "positive"),
    ("HPG chưa đạt kế hoạch lợi nhuận năm",                    "negative"),
    ("Cổ phiếu không tăng nhưng cũng không giảm đáng kể",       "neutral"),

    # ── Các từ khóa hay bị miss ─────────────────────────────────────────────
    ("mua vào cổ phiếu với khối lượng lớn",                     "positive"),
    ("bán ra toàn bộ cổ phần nắm giữ",                          "negative"),
    ("thoái vốn khỏi công ty, bán ròng liên tục",               "negative"),
    ("nâng room ngoại lên 49%",                                  "positive"),
    ("giải chấp cổ phiếu, áp lực bán gia tăng",                "negative"),
    ("cổ phiếu bị call margin hàng loạt",                       "negative"),
]


def score_to_pred(score: float) -> str:
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"


def run_tests(verbose: bool = True) -> dict:
    results = {"correct": 0, "wrong": 0, "details": []}

    if verbose:
        print(f"\n{'Title':<60} | {'Score':>7} | {'Label':<18} | {'Expected':<10} | OK?")
        print("-" * 112)

    for title, expected in TEST_CASES:
        score, label = get_sentiment(title)
        pred = score_to_pred(score)
        ok = pred == expected

        if ok:
            results["correct"] += 1
        else:
            results["wrong"] += 1

        results["details"].append({
            "title": title,
            "score": score,
            "label": label,
            "expected": expected,
            "predicted": pred,
            "correct": ok,
        })

        if verbose:
            icon = "✅" if ok else "❌"
            print(f"{title[:59]:<60} | {score:>+7.3f} | {label:<18} | {expected:<10} | {icon}")

    total = results["correct"] + results["wrong"]
    acc = results["correct"] / total * 100
    results["accuracy"] = acc

    if verbose:
        print(f"\n{'='*112}")
        print(f"Accuracy: {results['correct']}/{total} = {acc:.1f}%")
        print()

        # Show failures grouped by category
        failures = [d for d in results["details"] if not d["correct"]]
        if failures:
            print(f"❌ Failed cases ({len(failures)}):")
            for f in failures:
                print(f"  [{f['expected']}→{f['predicted']} | {f['score']:+.3f}] {f['title']}")
        else:
            print("🎉 All tests passed!")

        # Category analysis
        cats = {
            "positive→negative (false alarm)": [],
            "negative→positive (missed danger)": [],
            "neutral→positive (over-positive)": [],
            "neutral→negative (over-negative)": [],
            "positive→neutral (missed positive)": [],
            "negative→neutral (missed negative)": [],
        }
        for d in failures:
            key = f"{d['expected']}→{d['predicted']}"
            label = {
                "positive→negative": "positive→negative (false alarm)",
                "negative→positive": "negative→positive (missed danger)",
                "neutral→positive": "neutral→positive (over-positive)",
                "neutral→negative": "neutral→negative (over-negative)",
                "positive→neutral":  "positive→neutral (missed positive)",
                "negative→neutral":  "negative→neutral (missed negative)",
            }.get(key, key)
            cats.get(label, []).append(d["title"])

        if any(cats.values()):
            print("\n📊 Error breakdown:")
            for cat, titles in cats.items():
                if titles:
                    print(f"  {cat}: {len(titles)}")
                    for t in titles:
                        print(f"    - {t}")

    return results


# ── Pytest integration ────────────────────────────────────────────────────────
def test_accuracy_above_threshold():
    """Accuracy phải đạt >= 85%."""
    results = run_tests(verbose=False)
    assert results["accuracy"] >= 85.0, (
        f"Sentiment accuracy {results['accuracy']:.1f}% < 85% threshold.\n"
        f"Failed: {[d for d in results['details'] if not d['correct']]}"
    )


def test_no_false_danger():
    """Không được classify neutral/positive thành negative (false danger)."""
    results = run_tests(verbose=False)
    false_danger = [
        d for d in results["details"]
        if d["expected"] in ("positive", "neutral") and d["predicted"] == "negative"
    ]
    assert not false_danger, (
        f"False danger cases: {[d['title'] for d in false_danger]}"
    )


def test_key_terms_detected():
    """Các từ khóa quan trọng phải được detect đúng."""
    critical = [
        ("mua vào cổ phiếu với khối lượng lớn", "positive"),
        ("bán ra toàn bộ cổ phần nắm giữ", "negative"),
        ("thoái vốn khỏi công ty, bán ròng liên tục", "negative"),
        ("MWG lỗ nặng, cổ phiếu giảm sâu", "negative"),
        ("Hòa Phát lập kỷ lục lợi nhuận quý 1", "positive"),
    ]
    failures = []
    for title, expected in critical:
        score, _ = get_sentiment(title)
        pred = score_to_pred(score)
        if pred != expected:
            failures.append(f"{title!r}: got {pred} (score={score:.3f}), expected {expected}")
    assert not failures, "Critical terms not detected:\n" + "\n".join(failures)


if __name__ == "__main__":
    run_tests(verbose=True)

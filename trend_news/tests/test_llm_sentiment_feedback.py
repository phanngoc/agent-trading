"""
Integration tests for the LLM Sentiment Feedback Loop.

Each test prints:
    (bài viết) => score: X.XX (Label) [confidence: 0.XX]

Run with:
    cd trend_news
    pytest tests/test_llm_sentiment_feedback.py -v -s

Environment variables required for real LLM calls:
    ANTHROPIC_API_KEY  or  OPENAI_API_KEY

Tests are split into:
  - Unit tests (no LLM, use mocks) – always run
  - Integration tests (real LLM calls) – run only if USE_REAL_LLM=1
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Conditionally import the module under test
# ---------------------------------------------------------------------------
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.llm_sentiment_evaluator import (
    BatchEvaluationResult,
    LLMEvaluation,
    LLMSentimentEvaluator,
)

USE_REAL_LLM = os.environ.get("USE_REAL_LLM", "0") == "1"

# ---------------------------------------------------------------------------
# Sample Vietnamese financial news articles
# ---------------------------------------------------------------------------

SAMPLE_ARTICLES = [
    # Tích cực rõ ràng
    {"id": 1,  "title": "VNM tăng trưởng lợi nhuận 25% vượt kỳ vọng thị trường"},
    {"id": 2,  "title": "HPG đạt kỷ lục doanh thu quý cao nhất trong lịch sử"},
    {"id": 3,  "title": "FPT mở rộng sang thị trường Nhật Bản, ký hợp đồng 100 triệu USD"},
    {"id": 4,  "title": "Chỉ số VN-Index phục hồi mạnh mẽ, vượt mốc 1.300 điểm"},

    # Tiêu cực rõ ràng
    {"id": 5,  "title": "Nhiều doanh nghiệp bất động sản lỗ nặng trong quý I/2025"},
    {"id": 6,  "title": "Áp lực bán tháo khiến thị trường chứng khoán giảm sâu nhất 3 tháng"},
    {"id": 7,  "title": "SSI cảnh báo rủi ro nợ xấu tăng cao trong lĩnh vực ngân hàng"},
    {"id": 8,  "title": "VIC ghi nhận khoản lỗ 2.500 tỷ đồng trong năm 2024"},

    # Trung lập / mơ hồ
    {"id": 9,  "title": "NHNN công bố kế hoạch điều chỉnh lãi suất trong quý II"},
    {"id": 10, "title": "Thị trường chứng khoán Việt Nam trước thềm kỳ họp ĐHCĐ 2025"},
    {"id": 11, "title": "Báo cáo tài chính năm 2024 của các ngân hàng thương mại"},

    # Biên giới khó phán đoán
    {"id": 12, "title": "VPBank giảm lãi suất cho vay nhưng lo ngại tỷ lệ nợ xấu"},
    {"id": 13, "title": "Xuất khẩu tăng 8% nhưng nhập siêu vẫn tiếp diễn"},
]

EXPECTED_LABELS = {
    # (article_id, expected_direction): 1=positive, -1=negative, 0=neutral
    1:  1,
    2:  1,
    3:  1,
    4:  1,
    5: -1,
    6: -1,
    7: -1,
    8: -1,
    9:  0,
    10: 0,
    11: 0,
}


# ---------------------------------------------------------------------------
# Mock LLM factory
# ---------------------------------------------------------------------------

def _build_mock_llm_response(articles: List[Dict]) -> str:
    """Simulate a realistic LLM JSON response for unit tests."""
    simple_rules = {
        # keywords → sentiment
        "tăng": 0.6, "lợi nhuận": 0.5, "kỷ lục": 0.7, "mở rộng": 0.5,
        "phục hồi": 0.55, "vượt": 0.45, "tốt": 0.4,
        "giảm": -0.5, "lỗ": -0.7, "rủi ro": -0.45, "áp lực": -0.5,
        "nợ xấu": -0.65, "bán tháo": -0.7, "cảnh báo": -0.4,
    }
    results = []
    for i, art in enumerate(articles):
        title = art.get("title", "").lower()
        score = 0.0
        for kw, val in simple_rules.items():
            if kw in title:
                score += val
        score = max(-1.0, min(1.0, score))
        label = "Positive" if score > 0.1 else ("Negative" if score < -0.1 else "Neutral")
        confidence = 0.5 + abs(score) * 0.4
        results.append({
            "idx": i + 1,
            "score": round(score, 2),
            "label": label,
            "confidence": round(confidence, 2),
            "reasoning": f"Mock: phát hiện từ khóa cảm xúc trong tiêu đề",
        })
    return json.dumps(results)


def _make_mock_llm(articles: List[Dict]) -> MagicMock:
    """Return a mock LLM object that yields deterministic responses."""
    mock = MagicMock()
    mock.model_name = "mock-model"

    def invoke(messages):
        resp = MagicMock()
        resp.content = _build_mock_llm_response(articles)
        return resp

    mock.invoke.side_effect = invoke
    return mock


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_evaluator_with_mock_llm(
    articles: List[Dict], tmp_db: str
) -> LLMSentimentEvaluator:
    """Create an evaluator backed by a mock LLM and a temp DB."""
    ev = object.__new__(LLMSentimentEvaluator)
    ev.db_path = tmp_db
    ev.batch_size = 15
    ev.uncertainty_threshold = 0.35
    ev._llm = _make_mock_llm(articles)
    ev._init_tables()
    return ev


def _init_minimal_db(db_path: str) -> None:
    """Create the minimum schema needed for tests."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sentiment_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER,
            news_title TEXT,
            news_url TEXT,
            predicted_score REAL,
            predicted_label TEXT,
            user_score REAL,
            user_label TEXT,
            user_comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            published_at TIMESTAMP
        );
    """)
    conn.close()


# ===========================================================================
# UNIT TESTS (always run – no real LLM needed)
# ===========================================================================

class TestLLMEvaluatorMocked(unittest.TestCase):
    """Unit tests using a mock LLM."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        _init_minimal_db(self.db_path)

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helper to run evaluation and print results table
    # ------------------------------------------------------------------

    def _run_and_print(
        self, articles: List[Dict], label: str = "Test"
    ) -> BatchEvaluationResult:
        ev = _make_evaluator_with_mock_llm(articles, self.db_path)
        # Patch invoke on a per-article basis
        result = ev.evaluate_batch(articles, skip_cached=False)

        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        print(f"  {'Tiêu đề':<50} {'Score':>6}  {'Label':>10}  Conf")
        print(f"  {'-'*50} {'-'*6}  {'-'*10}  ----")
        for ev_item in result.evaluations:
            short = ev_item.title[:48] + ".." if len(ev_item.title) > 50 else ev_item.title
            print(
                f"  {short:<50} {ev_item.score:>+6.2f}  {ev_item.label:>10}  {ev_item.confidence:.2f}"
            )
        print(f"\n  Model: {result.model_used}")
        print(f"  Evaluated: {result.evaluated}/{result.total_articles}, Failed: {result.failed}")
        return result

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_positive_articles_score_above_zero(self):
        """Tích cực rõ ràng => score > 0."""
        positive_articles = [a for a in SAMPLE_ARTICLES if a["id"] in (1, 2, 3, 4)]
        result = self._run_and_print(positive_articles, "Positive Articles")

        self.assertEqual(result.evaluated, len(positive_articles))
        for ev_item in result.evaluations:
            self.assertGreater(ev_item.score, 0, f"Expected positive: {ev_item.title}")

    def test_negative_articles_score_below_zero(self):
        """Tiêu cực rõ ràng => score < 0."""
        negative_articles = [a for a in SAMPLE_ARTICLES if a["id"] in (5, 6, 7, 8)]
        result = self._run_and_print(negative_articles, "Negative Articles")

        self.assertEqual(result.evaluated, len(negative_articles))
        for ev_item in result.evaluations:
            self.assertLess(ev_item.score, 0, f"Expected negative: {ev_item.title}")

    def test_full_batch_all_articles(self):
        """Đánh giá toàn bộ 13 bài viết trong 1 lần batch."""
        result = self._run_and_print(SAMPLE_ARTICLES, "Full Batch (13 articles)")

        self.assertGreater(result.evaluated, 0)
        self.assertLessEqual(result.failed, 0)
        # All evaluations should have valid scores
        for ev_item in result.evaluations:
            self.assertGreaterEqual(ev_item.score, -1.0)
            self.assertLessEqual(ev_item.score, 1.0)
            self.assertIn(ev_item.label, ("Positive", "Negative", "Neutral"))

    def test_confidence_bounds(self):
        """Confidence phải nằm trong [0.0, 1.0]."""
        result = self._run_and_print(SAMPLE_ARTICLES[:5], "Confidence Bounds")
        for ev_item in result.evaluations:
            self.assertGreaterEqual(ev_item.confidence, 0.0)
            self.assertLessEqual(ev_item.confidence, 1.0)

    def test_caching_skip_already_evaluated(self):
        """Articles đã đánh giá không bị gọi LLM lần 2."""
        articles = SAMPLE_ARTICLES[:3]
        ev = _make_evaluator_with_mock_llm(articles, self.db_path)

        # First pass
        result1 = ev.evaluate_batch(articles, skip_cached=False)
        self.assertEqual(result1.evaluated, 3)

        # Second pass with skip_cached=True
        result2 = ev.evaluate_batch(articles, skip_cached=True)
        self.assertEqual(result2.skipped_cached, 3)
        self.assertEqual(result2.evaluated, 0)
        print(f"\n[Cache test] First: {result1.evaluated}, Second skipped: {result2.skipped_cached}")

    def test_sync_to_feedback_table(self):
        """LLM evaluations có confidence >= 0.6 phải được sync vào sentiment_feedback."""
        articles = [SAMPLE_ARTICLES[0], SAMPLE_ARTICLES[4]]  # 1 positive + 1 negative
        ev = _make_evaluator_with_mock_llm(articles, self.db_path)
        ev.evaluate_batch(articles, skip_cached=False)

        synced = ev.sync_llm_feedback_to_learning(min_confidence=0.0)
        print(f"\n[Sync test] Synced {synced} LLM evals → sentiment_feedback")
        self.assertGreater(synced, 0)

        # Verify rows appear in sentiment_feedback
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT user_comment FROM sentiment_feedback WHERE user_comment LIKE '%LLM%'"
        ).fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)

    def test_get_evaluation_stats(self):
        """Stats method phải trả về dict với các key quan trọng."""
        articles = SAMPLE_ARTICLES[:6]
        ev = _make_evaluator_with_mock_llm(articles, self.db_path)
        ev.evaluate_batch(articles, skip_cached=False)

        stats = ev.get_evaluation_stats()
        print(f"\n[Stats] {stats}")
        self.assertIn("total", stats)
        self.assertGreater(stats["total"], 0)

    def test_parse_response_with_markdown_fence(self):
        """Parser phải xử lý được response bọc trong ```json ... ```."""
        ev = _make_evaluator_with_mock_llm([], self.db_path)
        raw = '```json\n[{"idx": 1, "score": 0.5, "label": "Positive", "confidence": 0.8, "reasoning": "test"}]\n```'
        parsed = ev._parse_llm_response(raw, 1)
        self.assertEqual(len(parsed), 1)
        self.assertAlmostEqual(parsed[0]["score"], 0.5)

    def test_single_article_quick_check(self):
        """Kiểm tra nhanh một bài viết đơn lẻ."""
        article = {"id": 99, "title": "VN-Index tăng 2% sau tin tức tích cực từ FED"}
        ev = _make_evaluator_with_mock_llm([article], self.db_path)
        result = ev.evaluate_batch([article], skip_cached=False)

        self.assertEqual(len(result.evaluations), 1)
        ev_item = result.evaluations[0]
        print(f"\n  (bài viết) {ev_item.title!r} => score: {ev_item.score:.2f} ({ev_item.label})")
        self.assertGreater(ev_item.score, 0)


# ===========================================================================
# INTEGRATION TESTS (real LLM – only if USE_REAL_LLM=1)
# ===========================================================================

@unittest.skipUnless(USE_REAL_LLM, "Set USE_REAL_LLM=1 to run real LLM tests")
class TestLLMEvaluatorReal(unittest.TestCase):
    """Integration tests with a real LLM (costs money – use sparingly)."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        _init_minimal_db(self.db_path)

        self.evaluator = LLMSentimentEvaluator(
            db_path=self.db_path,
            model_provider="openai",
            batch_size=10,
        )

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except Exception:
            pass

    def _print_results(self, result: BatchEvaluationResult, label: str) -> None:
        print(f"\n{'='*65}")
        print(f"  {label}")
        print(f"{'='*65}")
        print(f"  {'Tiêu đề':<52} {'Score':>6}  {'Label':>10}  Conf")
        print(f"  {'-'*52} {'-'*6}  {'-'*10}  ----")
        for ev_item in result.evaluations:
            short = ev_item.title[:50] + ".." if len(ev_item.title) > 52 else ev_item.title
            print(
                f"  {short:<52} {ev_item.score:>+6.2f}  {ev_item.label:>10}  {ev_item.confidence:.2f}"
            )
            if ev_item.reasoning:
                print(f"       💬 {ev_item.reasoning[:80]}")
        print(f"\n  Model: {result.model_used} | Cost estimate: ~{result.tokens_estimated} tokens")
        print(f"  Evaluated: {result.evaluated}/{result.total_articles}, Failed: {result.failed}")

    def test_real_batch_evaluation_full(self):
        """Real LLM: đánh giá 13 bài viết mẫu và in kết quả."""
        result = self.evaluator.evaluate_batch(SAMPLE_ARTICLES, skip_cached=False)
        self._print_results(result, "REAL LLM: Full Batch (13 articles)")

        self.assertGreaterEqual(result.evaluated, 10, "At least 10/13 should succeed")
        self.assertEqual(result.failed, 0)

        # Sanity: obvious positives should have score > 0
        by_id = {int(ev_item.article_id or 0): ev_item for ev_item in result.evaluations}
        for art_id in (1, 2, 3, 4):
            if art_id in by_id:
                self.assertGreater(
                    by_id[art_id].score, -0.2,
                    f"Article {art_id} should not be strongly negative"
                )

    def test_real_direction_accuracy(self):
        """Real LLM: kiểm tra tỷ lệ đúng chiều (positive/negative)."""
        testable = [a for a in SAMPLE_ARTICLES if a["id"] in EXPECTED_LABELS and EXPECTED_LABELS[a["id"]] != 0]
        result = self.evaluator.evaluate_batch(testable, skip_cached=False)
        self._print_results(result, "REAL LLM: Direction Accuracy Test")

        correct = 0
        total = len(result.evaluations)
        for ev_item in result.evaluations:
            art_id = ev_item.article_id
            expected = EXPECTED_LABELS.get(art_id, 0)
            actual_dir = 1 if ev_item.score > 0.05 else (-1 if ev_item.score < -0.05 else 0)
            if expected == actual_dir:
                correct += 1
                print(f"  ✅ [{art_id}] {ev_item.title[:50]!r}: {ev_item.score:+.2f}")
            else:
                print(f"  ❌ [{art_id}] {ev_item.title[:50]!r}: expected {'pos' if expected==1 else 'neg'}, got {ev_item.score:+.2f}")

        accuracy = correct / total if total > 0 else 0
        print(f"\n  Direction accuracy: {correct}/{total} = {accuracy:.1%}")
        self.assertGreaterEqual(accuracy, 0.70, "LLM should achieve >70% direction accuracy")

    def test_real_ambiguous_articles(self):
        """Real LLM: bài viết mơ hồ – kiểm tra xem LLM có nhận ra không."""
        ambiguous = [a for a in SAMPLE_ARTICLES if a["id"] in (9, 10, 11, 12, 13)]
        result = self.evaluator.evaluate_batch(ambiguous, skip_cached=False)
        self._print_results(result, "REAL LLM: Ambiguous Articles")

        for ev_item in result.evaluations:
            print(
                f"\n  (bài viết) {ev_item.title!r}\n"
                f"             => score: {ev_item.score:.2f} ({ev_item.label}) "
                f"[confidence: {ev_item.confidence:.2f}]"
            )

    def test_real_cost_efficiency_batch_vs_individual(self):
        """Real LLM: so sánh chi phí batch vs gọi từng cái (ước tính)."""
        articles = SAMPLE_ARTICLES[:8]

        # Batch call
        result = self.evaluator.evaluate_batch(articles, skip_cached=False)
        print(f"\n  Batch (8 articles): ~{result.tokens_estimated} tokens")
        print(f"  Per-article estimate: ~{result.tokens_estimated // max(result.evaluated, 1)} tokens each")

        # If evaluated individually, rough estimate
        individual_estimate = 8 * 200  # ~200 tokens per individual call
        batch_estimate = result.tokens_estimated

        savings_pct = (1 - batch_estimate / individual_estimate) * 100
        print(f"  Estimated savings vs individual: {savings_pct:.0f}%")
        self.assertLess(batch_estimate, individual_estimate)


# ===========================================================================
# Standalone runner with rich output
# ===========================================================================

def run_demo(use_real_llm: bool = False, db_path: Optional[str] = None) -> None:
    """
    Run a quick demo evaluation and print results in a readable table.
    Useful for quick visual validation.

    Args:
        use_real_llm: If True, use real LLM (requires API key in env)
        db_path: Path to SQLite DB (temp file if None)
    """
    import tempfile

    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        _init_minimal_db(db_path)

    print("\n" + "="*65)
    print("  LLM SENTIMENT FEEDBACK LOOP - DEMO")
    print("="*65)

    if use_real_llm:
        evaluator = LLMSentimentEvaluator(
            db_path=db_path, model_provider="openai", batch_size=13
        )
    else:
        evaluator = _make_evaluator_with_mock_llm(SAMPLE_ARTICLES, db_path)

    result = evaluator.evaluate_batch(SAMPLE_ARTICLES, skip_cached=False)

    print(f"\n  {'#':>3}  {'Tiêu đề':<50}  {'Score':>6}  {'Label':>10}  Conf")
    print(f"  {'-'*3}  {'-'*50}  {'-'*6}  {'-'*10}  ----")
    for i, ev_item in enumerate(result.evaluations, 1):
        short = ev_item.title[:48] + ".." if len(ev_item.title) > 50 else ev_item.title
        print(
            f"  {i:>3}  {short:<50}  {ev_item.score:>+6.2f}  {ev_item.label:>10}  {ev_item.confidence:.2f}"
        )

    print(f"\n  {'─'*65}")
    print(f"  Model: {result.model_used}")
    print(f"  Articles: {result.total_articles} | Evaluated: {result.evaluated} | "
          f"Skipped: {result.skipped_cached} | Failed: {result.failed}")
    print(f"  Estimated tokens: ~{result.tokens_estimated}")

    # Sync high-confidence to feedback
    synced = evaluator.sync_llm_feedback_to_learning(min_confidence=0.6)
    print(f"\n  Synced {synced} high-confidence evaluations → sentiment_feedback table")

    stats = evaluator.get_evaluation_stats()
    print(f"\n  DB Stats: {stats}")
    print("="*65 + "\n")


if __name__ == "__main__":
    # Quick demo mode when run directly
    real = os.environ.get("USE_REAL_LLM", "0") == "1"
    run_demo(use_real_llm=real)

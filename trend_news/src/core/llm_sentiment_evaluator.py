"""
LLM Batch Sentiment Evaluator - Cost-efficient feedback loop using LangChain.

Architecture:
  Articles (high uncertainty) → Batch Queue → LLM Evaluator → DB
                                                                ↓
                                             sentiment_llm_evaluations table
                                                                ↓
                                   Combined with admin feedback in learning system

Cost optimizations:
  - Batch up to N articles per LLM call (default 15)
  - Only evaluate articles above uncertainty threshold
  - Cache results in DB to avoid re-evaluation
  - Use cheapest viable model (claude-haiku or gpt-3.5-turbo)
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional LangChain imports – graceful degradation if not installed
# ---------------------------------------------------------------------------
try:
    import langchain_core as _lc_check  # presence check – plain dict API used at runtime

    _LANGCHAIN_AVAILABLE = True
    del _lc_check
except ImportError:
    _LANGCHAIN_AVAILABLE = False

try:
    from langchain_anthropic import ChatAnthropic  # type: ignore

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    from langchain_openai import ChatOpenAI  # type: ignore

    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LLMEvaluation:
    """Result from LLM sentiment evaluation."""

    article_id: Optional[int]
    title: str
    score: float          # [-1.0, 1.0]
    label: str            # "Positive" | "Negative" | "Neutral"
    confidence: float     # [0.0, 1.0] – how certain the LLM is
    reasoning: str        # Short explanation (for audit trail)
    model_used: str
    evaluated_at: str


@dataclass
class BatchEvaluationResult:
    """Summary of a batch LLM evaluation run."""

    total_articles: int
    evaluated: int
    skipped_cached: int
    failed: int
    evaluations: List[LLMEvaluation]
    model_used: str
    tokens_estimated: int


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích cảm xúc tin tức tài chính Việt Nam.
Nhiệm vụ: Đánh giá cảm xúc (sentiment) của từng tiêu đề tin tức về chứng khoán và tài chính.

Quy tắc chấm điểm:
- score từ -1.0 đến 1.0 (âm = tiêu cực, dương = tích cực, 0 = trung lập)
- confidence từ 0.0 đến 1.0 (mức độ chắc chắn của đánh giá)
- label: "Positive" (score > 0.1), "Negative" (score < -0.1), "Neutral" (còn lại)

Dấu hiệu tích cực: tăng, lãi, tốt, mạnh, phục hồi, kỳ vọng cao, đột phá, đỉnh cao
Dấu hiệu tiêu cực: giảm, lỗ, xấu, yếu, rủi ro, lo ngại, áp lực, đáy, mất

Trả về JSON array với mỗi phần tử có dạng:
{"idx": <index>, "score": <float>, "label": <str>, "confidence": <float>, "reasoning": <str ngắn gọn>}
"""

_BATCH_TEMPLATE = """Đánh giá sentiment cho {n} tiêu đề tin tức sau:

{articles}

Trả về JSON array (đúng format, không giải thích thêm):"""


# ---------------------------------------------------------------------------
# Core evaluator class
# ---------------------------------------------------------------------------

class LLMSentimentEvaluator:
    """
    Batch-evaluate article sentiment using an LLM via LangChain.

    Usage::

        evaluator = LLMSentimentEvaluator(db_path="output/trend_news.db")
        result = evaluator.evaluate_batch([
            {"id": 1, "title": "Cổ phiếu VNM tăng mạnh 5%"},
            {"id": 2, "title": "Thị trường chứng khoán giảm sâu"},
        ])
        for ev in result.evaluations:
            print(f"{ev.title!r} => score: {ev.score:.2f} ({ev.label})")
    """

    # Max articles per single LLM call
    DEFAULT_BATCH_SIZE = 15
    # Only evaluate articles with uncertainty above this threshold
    DEFAULT_UNCERTAINTY_THRESHOLD = 0.35

    def __init__(
        self,
        db_path: Optional[str] = None,
        model_provider: str = "openai",
        model_name: Optional[str] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        uncertainty_threshold: float = DEFAULT_UNCERTAINTY_THRESHOLD,
    ):
        if db_path is None:
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            db_path = os.path.join(project_root, "output", "trend_news.db")
        self.db_path = db_path
        self.batch_size = batch_size
        self.uncertainty_threshold = uncertainty_threshold

        self._llm = self._init_llm(model_provider, model_name)
        self._init_tables()

    # ------------------------------------------------------------------
    # Initialization helpers
    # ------------------------------------------------------------------

    def _init_llm(self, provider: str, model_name: Optional[str]) -> Any:
        """Initialize the cheapest viable LLM for the given provider."""
        if not _LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain not installed. Run: pip install langchain-core"
            )

        if provider == "openai":
            if not _OPENAI_AVAILABLE:
                raise ImportError(
                    "langchain-openai not installed. Run: pip install langchain-openai"
                )
            name = model_name or "gpt-4o-mini"
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set in environment")
            return ChatOpenAI(model=name, api_key=api_key, max_tokens=2048)

        if provider == "anthropic":
            if not _ANTHROPIC_AVAILABLE:
                raise ImportError(
                    "langchain-anthropic not installed. Run: pip install langchain-anthropic"
                )
            name = model_name or "claude-haiku-4-5-20251001"
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set in environment")
            return ChatAnthropic(model=name, api_key=api_key, max_tokens=2048)

        raise ValueError(f"Unknown provider: {provider!r}. Use 'anthropic' or 'openai'.")

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        """Create DB tables for LLM evaluations."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sentiment_llm_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id INTEGER,
                    title TEXT NOT NULL,
                    llm_score REAL NOT NULL,
                    llm_label TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    reasoning TEXT,
                    model_used TEXT,
                    batch_id TEXT,
                    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    -- merged into feedback loop?
                    synced_to_feedback BOOLEAN DEFAULT 0,
                    FOREIGN KEY (news_id) REFERENCES news_articles(id)
                )
            """)
            # Index for quick lookup by news_id
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_eval_news_id
                ON sentiment_llm_evaluations(news_id)
            """)
            # Index for un-synced rows
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_eval_synced
                ON sentiment_llm_evaluations(synced_to_feedback)
            """)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_batch(
        self,
        articles: List[Dict[str, Any]],
        skip_cached: bool = True,
        batch_id: Optional[str] = None,
    ) -> BatchEvaluationResult:
        """
        Evaluate a list of articles in cost-efficient batches.

        Args:
            articles: List of dicts with at least {"title": str} and optionally {"id": int}
            skip_cached: If True, skip articles already evaluated
            batch_id: Optional label for this batch run (e.g. "2025-01-15-morning")

        Returns:
            BatchEvaluationResult with all LLMEvaluation objects
        """
        if batch_id is None:
            batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        to_evaluate: List[Dict] = []
        skipped = 0

        for art in articles:
            art_id = art.get("id")
            if skip_cached and art_id is not None and self._is_cached(art_id):
                skipped += 1
                continue
            to_evaluate.append(art)

        all_evaluations: List[LLMEvaluation] = []
        failed = 0

        # Process in batches of self.batch_size
        for chunk_start in range(0, len(to_evaluate), self.batch_size):
            chunk = to_evaluate[chunk_start: chunk_start + self.batch_size]
            try:
                evals = self._call_llm_batch(chunk, batch_id)
                self._persist_evaluations(evals)
                all_evaluations.extend(evals)
            except Exception as exc:
                print(f"[LLMEvaluator] Batch failed: {exc}")
                failed += len(chunk)

        model_name = getattr(self._llm, "model_name", getattr(self._llm, "model", "unknown"))
        return BatchEvaluationResult(
            total_articles=len(articles),
            evaluated=len(all_evaluations),
            skipped_cached=skipped,
            failed=failed,
            evaluations=all_evaluations,
            model_used=model_name,
            tokens_estimated=len(to_evaluate) * 80,  # rough estimate
        )

    def evaluate_high_uncertainty_articles(
        self,
        days_back: int = 7,
        min_uncertainty: Optional[float] = None,
        limit: int = 100,
    ) -> BatchEvaluationResult:
        """
        Pull articles with high uncertainty from DB and evaluate with LLM.
        Only articles that haven't been evaluated yet are fetched.

        Args:
            days_back: How many days of articles to consider
            min_uncertainty: Override default uncertainty threshold
            limit: Max number of articles to evaluate
        """
        threshold = min_uncertainty if min_uncertainty is not None else self.uncertainty_threshold
        articles = self._fetch_high_uncertainty_articles(days_back, threshold, limit)
        if not articles:
            print("[LLMEvaluator] No high-uncertainty articles to evaluate")
            return BatchEvaluationResult(0, 0, 0, 0, [], "", 0)
        print(f"[LLMEvaluator] Evaluating {len(articles)} high-uncertainty articles")
        return self.evaluate_batch(articles)

    def sync_llm_feedback_to_learning(self, min_confidence: float = 0.6) -> int:
        """
        Merge high-confidence LLM evaluations into sentiment_feedback table
        so the learning system can use them alongside admin feedback.

        Args:
            min_confidence: Only sync evaluations where LLM confidence >= this value

        Returns:
            Number of rows synced
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, news_id, title, llm_score, llm_label, confidence, model_used
                FROM sentiment_llm_evaluations
                WHERE synced_to_feedback = 0
                AND confidence >= ?
            """, (min_confidence,))
            rows = cursor.fetchall()

            synced = 0
            for row in rows:
                # Insert into sentiment_feedback as LLM-sourced feedback
                cursor.execute("""
                    INSERT OR IGNORE INTO sentiment_feedback
                    (news_id, news_title, predicted_score, predicted_label,
                     user_score, user_label, user_comment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["news_id"],
                    row["title"],
                    row["llm_score"],     # predicted = LLM score (used as baseline)
                    row["llm_label"],
                    row["llm_score"],     # user = LLM score (LLM acts as annotator)
                    row["llm_label"],
                    f"[LLM:{row['model_used']}] confidence={row['confidence']:.2f}",
                    datetime.now().isoformat(),
                ))
                # Mark as synced
                cursor.execute("""
                    UPDATE sentiment_llm_evaluations SET synced_to_feedback = 1
                    WHERE id = ?
                """, (row["id"],))
                synced += 1

            conn.commit()
            print(f"[LLMEvaluator] Synced {synced} LLM evaluations → sentiment_feedback")
            return synced
        finally:
            conn.close()

    def get_evaluation_stats(self) -> Dict[str, Any]:
        """Return summary statistics of LLM evaluations."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    AVG(confidence) as avg_confidence,
                    SUM(CASE WHEN llm_label='Positive' THEN 1 ELSE 0 END) as positive_count,
                    SUM(CASE WHEN llm_label='Negative' THEN 1 ELSE 0 END) as negative_count,
                    SUM(CASE WHEN llm_label='Neutral'  THEN 1 ELSE 0 END) as neutral_count,
                    SUM(CASE WHEN synced_to_feedback=1 THEN 1 ELSE 0 END) as synced_count,
                    MIN(evaluated_at) as earliest,
                    MAX(evaluated_at) as latest
                FROM sentiment_llm_evaluations
            """)
            row = cursor.fetchone()
            return dict(row) if row else {}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cached(self, news_id: int) -> bool:
        """Check if this article was already evaluated."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM sentiment_llm_evaluations WHERE news_id = ? LIMIT 1",
                (news_id,)
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def _call_llm_batch(
        self, articles: List[Dict], batch_id: str
    ) -> List[LLMEvaluation]:
        """Send one batched LLM request for up to batch_size articles."""
        numbered = "\n".join(
            f"{i+1}. {art.get('title', '')}" for i, art in enumerate(articles)
        )
        prompt_text = _BATCH_TEMPLATE.format(n=len(articles), articles=numbered)

        # Plain OpenAI-style dicts – accepted by all LangChain chat models
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
        ]
        response = self._llm.invoke(messages)
        raw = response.content if hasattr(response, "content") else str(response)

        parsed = self._parse_llm_response(raw, len(articles))
        model_name = getattr(self._llm, "model_name", getattr(self._llm, "model", "unknown"))
        now = datetime.now().isoformat()

        evaluations: List[LLMEvaluation] = []
        for item in parsed:
            idx = item.get("idx", 1) - 1  # convert 1-based to 0-based
            if idx < 0 or idx >= len(articles):
                continue
            art = articles[idx]
            evaluations.append(LLMEvaluation(
                article_id=art.get("id"),
                title=art.get("title", ""),
                score=float(item.get("score", 0.0)),
                label=item.get("label", "Neutral"),
                confidence=float(item.get("confidence", 0.5)),
                reasoning=item.get("reasoning", ""),
                model_used=model_name,
                evaluated_at=now,
            ))
        return evaluations

    def _parse_llm_response(self, raw: str, expected_count: int) -> List[Dict]:
        """Robustly parse JSON from LLM response."""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            # Sometimes LLM wraps in {"items": [...]}
            for key in ("items", "results", "evaluations"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        except json.JSONDecodeError:
            pass

        # Fallback: try to extract JSON array substring
        import re
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        print(f"[LLMEvaluator] WARNING: Could not parse LLM response. Raw: {raw[:200]}")
        return []

    def _persist_evaluations(self, evaluations: List[LLMEvaluation]) -> None:
        """Save LLM evaluations to DB."""
        if not evaluations:
            return
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO sentiment_llm_evaluations
                (news_id, title, llm_score, llm_label, confidence, reasoning, model_used, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    ev.article_id,
                    ev.title,
                    ev.score,
                    ev.label,
                    ev.confidence,
                    ev.reasoning,
                    ev.model_used,
                    ev.evaluated_at,
                )
                for ev in evaluations
            ])
            conn.commit()
        finally:
            conn.close()

    def _fetch_high_uncertainty_articles(
        self, days_back: int, min_uncertainty: float, limit: int
    ) -> List[Dict]:
        """
        Fetch articles from news_articles that:
        - Were crawled in the last `days_back` days
        - Have not yet been LLM-evaluated
        - Have high uncertainty (stored in labeling queue or re-computed)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Try fetching from labeling_queue if it has uncertainty_score
            try:
                cursor.execute("""
                    SELECT lq.news_id AS id, na.title
                    FROM labeling_queue lq
                    JOIN news_articles na ON na.id = lq.news_id
                    WHERE lq.uncertainty_score >= ?
                    AND lq.status = 'pending'
                    AND na.published_at >= datetime('now', '-' || ? || ' days')
                    AND lq.news_id NOT IN (
                        SELECT news_id FROM sentiment_llm_evaluations WHERE news_id IS NOT NULL
                    )
                    ORDER BY lq.uncertainty_score DESC
                    LIMIT ?
                """, (min_uncertainty, days_back, limit))
                rows = cursor.fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass  # labeling_queue may not exist yet

            # Fallback: just grab recent articles not yet evaluated
            cursor.execute("""
                SELECT na.id, na.title
                FROM news_articles na
                WHERE na.published_at >= datetime('now', '-' || ? || ' days')
                AND na.id NOT IN (
                    SELECT news_id FROM sentiment_llm_evaluations WHERE news_id IS NOT NULL
                )
                ORDER BY na.published_at DESC
                LIMIT ?
            """, (days_back, limit))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

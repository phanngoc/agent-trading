"""
Claude-backed sentiment scorer with prompt batching.

Strategy: chunk items into groups of `prompt_batch_size`, fire chunks
in parallel against /v1/messages with a single shared system prompt.
This amortizes the system prompt across multiple articles for token
efficiency without needing the Anthropic Batches API (which OAuth
tokens cannot access).

On any Claude error or unparseable response, falls back to the local
lexicon in src.utils.sentiment so callers always get a result.
"""

from __future__ import annotations

import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.core.claude_client import ClaudeAPIError, ClaudeClient

PROMPT_BATCH_SIZE = 5  # items per /v1/messages call
SYNC_CONCURRENCY = 5

LabelStr = Literal["Positive", "Negative", "Neutral"]
SourceStr = Literal["claude", "lexicon_fallback"]


@dataclass
class SentimentItem:
    article_id: Optional[int]
    title: str
    content: str = ""
    language: str = "vi"  # vi|zh|en

    def to_prompt_text(self, max_content: int = 600) -> str:
        snippet = (self.content or "").strip()[:max_content]
        if snippet:
            return f"{self.title.strip()}\n{snippet}"
        return self.title.strip()


@dataclass
class SentimentResult:
    article_id: Optional[int]
    title: str
    score: float
    label: str
    confidence: float
    reasoning: str
    source: SourceStr
    model_used: str = ""
    evaluated_at: str = field(default_factory=lambda: datetime.now().isoformat())


_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích sentiment tin tức tài chính đa ngôn ngữ (Việt, Trung, Anh).

Quy tắc chấm điểm cho từng tin:
- score: float trong [-1.0, 1.0]. Âm = tiêu cực với nhà đầu tư, dương = tích cực, 0 = trung lập.
- label: "Positive" nếu score > 0.1, "Negative" nếu score < -0.1, "Neutral" còn lại.
- confidence: float trong [0.0, 1.0] - độ chắc chắn của đánh giá.
- reasoning: 1 câu ngắn (<=120 ký tự).

Tín hiệu tích cực: tăng trưởng, lãi, kỳ vọng, mở rộng, vượt dự báo, hồi phục.
Tín hiệu tiêu cực: giảm, lỗ, rủi ro, áp lực, bán tháo, suy thoái, vỡ nợ.

Trả về DUY NHẤT một JSON array, mỗi phần tử:
{"idx": <int 1-based>, "score": <float>, "label": <str>, "confidence": <float>, "reasoning": <str>}
Không thêm văn bản khác."""


def _build_user_prompt(items: List[SentimentItem]) -> str:
    lines = [f"Đánh giá {len(items)} tin sau, trả JSON array đúng thứ tự:"]
    for i, it in enumerate(items, 1):
        lines.append(f"\n[{i}] ({it.language}) {it.to_prompt_text()}")
    lines.append("\nJSON array:")
    return "\n".join(lines)


def _parse_response(raw: str, expected: int) -> List[Dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        # strip code fence
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group())
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        for key in ("items", "results", "evaluations"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, list):
        return []
    return data


def _label_from_score(score: float) -> str:
    if score > 0.1:
        return "Positive"
    if score < -0.1:
        return "Negative"
    return "Neutral"


def _lexicon_fallback_one(item: SentimentItem) -> SentimentResult:
    """Cheap rule-based scoring used when Claude is unavailable."""
    from src.utils.sentiment import get_sentiment  # local import → optional dep
    score, label = get_sentiment(item.title)
    return SentimentResult(
        article_id=item.article_id,
        title=item.title,
        score=float(score),
        label=label,
        confidence=0.4,  # lexicon is a coarse signal
        reasoning="lexicon fallback (Claude unavailable)",
        source="lexicon_fallback",
        model_used="lexicon",
    )


class ClaudeSentiment:
    """Prompt-batched sentiment scorer over Claude /v1/messages."""

    def __init__(
        self,
        client: Optional[ClaudeClient] = None,
        db_path: Optional[str] = None,
        prompt_batch_size: int = PROMPT_BATCH_SIZE,
        concurrency: int = SYNC_CONCURRENCY,
    ):
        self.client = client or ClaudeClient()
        self.db_path = db_path
        self.prompt_batch_size = prompt_batch_size
        self.concurrency = concurrency

    def score(self, items: List[SentimentItem]) -> List[SentimentResult]:
        """Score `items` via prompt-batched Claude calls. Order preserved."""
        if not items:
            return []

        chunks: List[List[SentimentItem]] = [
            items[i : i + self.prompt_batch_size]
            for i in range(0, len(items), self.prompt_batch_size)
        ]
        results: Dict[int, SentimentResult] = {}

        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            futures = {pool.submit(self._score_chunk, c): idx for idx, c in enumerate(chunks)}
            for fut in as_completed(futures):
                chunk_idx = futures[fut]
                chunk = chunks[chunk_idx]
                try:
                    chunk_results = fut.result()
                except Exception as exc:
                    print(f"[ClaudeSentiment] chunk {chunk_idx} failed: {exc}")
                    chunk_results = [_lexicon_fallback_one(it) for it in chunk]
                offset = chunk_idx * self.prompt_batch_size
                for j, r in enumerate(chunk_results):
                    results[offset + j] = r

        ordered = [results[i] for i in range(len(items))]
        if self.db_path:
            self._persist(ordered)
        return ordered

    def _score_chunk(self, chunk: List[SentimentItem]) -> List[SentimentResult]:
        prompt = _build_user_prompt(chunk)
        try:
            resp = self.client.messages_create(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM_PROMPT,
                max_tokens=512 + 80 * len(chunk),
            )
        except ClaudeAPIError as exc:
            print(f"[ClaudeSentiment] API error: {exc}")
            return [_lexicon_fallback_one(it) for it in chunk]

        raw = self.client.extract_text(resp)
        parsed = _parse_response(raw, expected=len(chunk))
        model_used = resp.get("model", self.client.model)
        return self._materialize(chunk, parsed, "claude", model_used)

    # ------------------------------------------------------------------
    # Materialization + persistence
    # ------------------------------------------------------------------
    def _materialize(
        self,
        chunk: List[SentimentItem],
        parsed: List[Dict[str, Any]],
        source: SourceStr,
        model_used: str,
    ) -> List[SentimentResult]:
        by_idx: Dict[int, Dict[str, Any]] = {}
        for entry in parsed:
            try:
                idx = int(entry.get("idx", 0)) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(chunk):
                by_idx[idx] = entry

        out: List[SentimentResult] = []
        for i, item in enumerate(chunk):
            entry = by_idx.get(i)
            if entry is None:
                out.append(_lexicon_fallback_one(item))
                continue
            try:
                score = max(-1.0, min(1.0, float(entry.get("score", 0.0))))
                conf = max(0.0, min(1.0, float(entry.get("confidence", 0.5))))
            except (TypeError, ValueError):
                out.append(_lexicon_fallback_one(item))
                continue
            label = entry.get("label") or _label_from_score(score)
            out.append(SentimentResult(
                article_id=item.article_id,
                title=item.title,
                score=score,
                label=str(label),
                confidence=conf,
                reasoning=str(entry.get("reasoning", ""))[:240],
                source=source,
                model_used=model_used,
            ))
        return out

    # ------------------------------------------------------------------
    # DB-driven evaluation (drop-in replacement for LLMSentimentEvaluator)
    # ------------------------------------------------------------------
    def evaluate_high_uncertainty_articles(
        self,
        days_back: int = 7,
        min_uncertainty: float = 0.35,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Pull uncertain articles from DB, score, persist.

        Returns a summary dict compatible with the old BatchEvaluationResult shape:
          {evaluated, skipped_cached, failed, model_used}
        """
        if not self.db_path:
            raise RuntimeError("db_path is required for evaluate_high_uncertainty_articles")
        articles = self._fetch_high_uncertainty(days_back, min_uncertainty, limit)
        if not articles:
            return {"evaluated": 0, "skipped_cached": 0, "failed": 0, "model_used": ""}

        from src.utils.sentiment import _is_chinese, _is_vietnamese

        def _detect_lang(text: str) -> str:
            if _is_vietnamese(text):
                return "vi"
            if _is_chinese(text):
                return "zh"
            return "en"

        items = [
            SentimentItem(
                article_id=row["id"],
                title=row["title"],
                content=row.get("content", "") or "",
                language=_detect_lang(row["title"]),
            )
            for row in articles
        ]
        results = self.score(items)
        failed = sum(1 for r in results if r.source == "lexicon_fallback")
        evaluated = len(results) - failed
        model = next(
            (r.model_used for r in results if r.source != "lexicon_fallback"),
            "lexicon",
        )
        return {
            "evaluated": evaluated,
            "skipped_cached": 0,
            "failed": failed,
            "model_used": model,
        }

    def sync_llm_feedback_to_learning(self, min_confidence: float = 0.6) -> int:
        """Promote high-confidence Claude evaluations into sentiment_feedback."""
        if not self.db_path:
            return 0
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, news_id, title, llm_score, llm_label, confidence, model_used
                FROM sentiment_llm_evaluations
                WHERE synced_to_feedback = 0 AND confidence >= ?
            """, (min_confidence,))
            rows = cur.fetchall()
            synced = 0
            now = datetime.now().isoformat()
            for r in rows:
                cur.execute("""
                    INSERT OR IGNORE INTO sentiment_feedback
                    (news_id, news_title, predicted_score, predicted_label,
                     user_score, user_label, user_comment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["news_id"], r["title"],
                    r["llm_score"], r["llm_label"],
                    r["llm_score"], r["llm_label"],
                    f"[Claude:{r['model_used']}] confidence={r['confidence']:.2f}",
                    now,
                ))
                cur.execute(
                    "UPDATE sentiment_llm_evaluations SET synced_to_feedback = 1 WHERE id = ?",
                    (r["id"],),
                )
                synced += 1
            conn.commit()
            return synced
        finally:
            conn.close()

    def _fetch_high_uncertainty(
        self, days_back: int, min_uncertainty: float, limit: int
    ) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT lq.news_id AS id, na.title,
                           COALESCE(na.content, '') AS content
                    FROM labeling_queue lq
                    JOIN news_articles na ON na.id = lq.news_id
                    WHERE lq.uncertainty_score >= ?
                      AND lq.status = 'pending'
                      AND na.crawled_at >= datetime('now', '-' || ? || ' days')
                      AND lq.news_id NOT IN (
                          SELECT news_id FROM sentiment_llm_evaluations
                          WHERE news_id IS NOT NULL
                      )
                    ORDER BY lq.uncertainty_score DESC
                    LIMIT ?
                """, (min_uncertainty, days_back, limit))
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
            cur.execute("""
                SELECT na.id, na.title,
                       COALESCE(na.content, '') AS content
                FROM news_articles na
                WHERE na.crawled_at >= datetime('now', '-' || ? || ' days')
                  AND na.id NOT IN (
                      SELECT news_id FROM sentiment_llm_evaluations
                      WHERE news_id IS NOT NULL
                  )
                ORDER BY na.crawled_at DESC
                LIMIT ?
            """, (days_back, limit))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def _persist(self, results: List[SentimentResult]) -> None:
        """Write into existing sentiment_llm_evaluations schema."""
        if not self.db_path:
            return
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("""
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
                    synced_to_feedback BOOLEAN DEFAULT 0
                )
            """)
            cur.executemany("""
                INSERT INTO sentiment_llm_evaluations
                (news_id, title, llm_score, llm_label, confidence, reasoning, model_used, evaluated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (r.article_id, r.title, r.score, r.label, r.confidence,
                 r.reasoning, r.model_used, r.evaluated_at)
                for r in results
                if r.source != "lexicon_fallback"  # don't pollute audit table with fallback rows
            ])
            conn.commit()
        finally:
            conn.close()

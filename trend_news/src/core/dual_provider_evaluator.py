"""
DualProviderEvaluator — routes articles to Groq or OpenAI based on content.

Routing logic:
  VN articles (title has Vietnamese chars)  → Groq llama-3.3-70b (fast, free)
  EN/CN articles or high-uncertainty        → OpenAI gpt-4o-mini (accurate)
  Either fails (rate limit, error)          → fallback to the other

Cost profile:
  Groq:   free tier 14,400 req/day — use for VN bulk
  OpenAI: ~$0.15/1M tokens (gpt-4o-mini) — use for complex/EN

Usage:
    evaluator = DualProviderEvaluator(db_path="output/trend_news.db")
    result = evaluator.evaluate_high_uncertainty_articles(days_back=7)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from src.core.llm_sentiment_evaluator import (
    LLMSentimentEvaluator,
    BatchEvaluationResult,
    LLMEvaluation,
)


# Vietnamese character detection (basic Unicode range)
_VN_PATTERN = re.compile(
    r"[àáạảãăắặẳẵâấậẩẫèéẹẻẽêếệểễìíịỉĩòóọỏõôốộổỗơớợởỡùúụủũưứựửữỳýỵỷỹđ"
    r"ÀÁẠẢÃĂẮẶẲẴÂẤẬẨẪÈÉẸẺẼÊẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỐỘỔỖƠỚỢỞỠÙÚỤỦŨƯỨỰỬỮỲÝỴỶỸĐ]",
    re.UNICODE,
)

def _is_vietnamese(text: str) -> bool:
    return bool(_VN_PATTERN.search(text))

def _detect_language(articles: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Split articles into Vietnamese and non-Vietnamese."""
    vn, other = [], []
    for a in articles:
        title = a.get("title", "")
        if _is_vietnamese(title):
            vn.append(a)
        else:
            other.append(a)
    return vn, other


class DualProviderEvaluator:
    """
    Routes batch evaluation across Groq and OpenAI based on article language.

    Priority:
      1. VN articles → Groq (free, fast, good at Vietnamese)
      2. EN/CN articles → OpenAI (gpt-4o-mini, more accurate for finance EN)
      3. Fallback: if primary fails, try secondary
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        groq_model: str = "llama-3.3-70b-versatile",
        openai_model: str = "gpt-4o-mini",
        batch_size: int = 15,
        uncertainty_threshold: float = 0.35,
    ):
        self.db_path = db_path
        self.batch_size = batch_size
        self.uncertainty_threshold = uncertainty_threshold

        self._groq: Optional[LLMSentimentEvaluator] = None
        self._openai: Optional[LLMSentimentEvaluator] = None

        # Init Groq
        try:
            self._groq = LLMSentimentEvaluator(
                db_path=db_path,
                model_provider="groq",
                model_name=groq_model,
                batch_size=batch_size,
                uncertainty_threshold=uncertainty_threshold,
            )
            print(f"  ✓ Groq provider ready ({groq_model})")
        except (ImportError, ValueError) as e:
            print(f"  ⚠ Groq unavailable: {e}")

        # Init OpenAI
        try:
            self._openai = LLMSentimentEvaluator(
                db_path=db_path,
                model_provider="openai",
                model_name=openai_model,
                batch_size=batch_size,
                uncertainty_threshold=uncertainty_threshold,
            )
            print(f"  ✓ OpenAI provider ready ({openai_model})")
        except (ImportError, ValueError) as e:
            print(f"  ⚠ OpenAI unavailable: {e}")

        if not self._groq and not self._openai:
            raise ValueError(
                "No LLM provider available. "
                "Set GROQ_API_KEY and/or OPENAI_API_KEY."
            )

    @property
    def _primary_vn(self) -> Optional[LLMSentimentEvaluator]:
        """Primary for VN: Groq preferred, OpenAI fallback."""
        return self._groq or self._openai

    @property
    def _primary_en(self) -> Optional[LLMSentimentEvaluator]:
        """Primary for EN: OpenAI preferred, Groq fallback."""
        return self._openai or self._groq

    def _run_with_fallback(
        self,
        articles: List[Dict],
        primary: LLMSentimentEvaluator,
        fallback: Optional[LLMSentimentEvaluator],
        label: str,
    ) -> BatchEvaluationResult:
        """Run batch evaluation with automatic fallback on failure."""
        if not articles:
            return BatchEvaluationResult(0, 0, 0, 0, [], "", 0)

        try:
            result = primary.evaluate_batch(articles)
            if result.failed > 0 and fallback and fallback is not primary:
                # Retry failed articles with fallback
                failed_ids = {
                    e.article_id for e in result.evaluations if e.sentiment_label == "error"
                }
                retry_articles = [a for a in articles if a.get("id") in failed_ids]
                if retry_articles:
                    print(f"  → Retrying {len(retry_articles)} failed {label} articles with fallback")
                    retry_result = fallback.evaluate_batch(retry_articles)
                    # Merge results
                    all_evals = result.evaluations + retry_result.evaluations
                    return BatchEvaluationResult(
                        total_articles=result.total_articles,
                        evaluated=result.evaluated + retry_result.evaluated,
                        skipped_cached=result.skipped_cached + retry_result.skipped_cached,
                        failed=retry_result.failed,
                        evaluations=all_evals,
                        model_used=f"{result.model_used}+{retry_result.model_used}",
                        tokens_estimated=result.tokens_estimated + retry_result.tokens_estimated,
                    )
            return result
        except Exception as e:
            if fallback and fallback is not primary:
                print(f"  ⚠ {label} primary failed ({e}), trying fallback...")
                return fallback.evaluate_batch(articles)
            raise

    def evaluate_batch(self, articles: List[Dict]) -> BatchEvaluationResult:
        """
        Evaluate a mixed list of articles, routing by language.

        VN articles → Groq
        EN/CN articles → OpenAI
        """
        vn_articles, other_articles = _detect_language(articles)

        print(f"  [DualProvider] VN={len(vn_articles)} → Groq | Other={len(other_articles)} → OpenAI")

        results = []

        if vn_articles:
            r = self._run_with_fallback(
                vn_articles, self._primary_vn, self._primary_en, "VN"
            )
            results.append(r)

        if other_articles:
            r = self._run_with_fallback(
                other_articles, self._primary_en, self._primary_vn, "EN/CN"
            )
            results.append(r)

        if not results:
            return BatchEvaluationResult(0, 0, 0, 0, [], "", 0)

        # Merge all results
        return BatchEvaluationResult(
            total_articles=sum(r.total_articles for r in results),
            evaluated=sum(r.evaluated for r in results),
            skipped_cached=sum(r.skipped_cached for r in results),
            failed=sum(r.failed for r in results),
            evaluations=[e for r in results for e in r.evaluations],
            model_used=" | ".join(r.model_used for r in results if r.model_used),
            tokens_estimated=sum(r.tokens_estimated for r in results),
        )

    def evaluate_high_uncertainty_articles(
        self,
        days_back: int = 7,
        min_uncertainty: Optional[float] = None,
        limit: int = 100,
    ) -> BatchEvaluationResult:
        """
        Pull high-uncertainty articles from DB and route to correct provider.

        Uses the same DB fetching logic as LLMSentimentEvaluator, but splits
        by language before calling evaluate_batch().
        """
        # Use any available evaluator to fetch articles from DB
        fetcher = self._groq or self._openai
        threshold = min_uncertainty or self.uncertainty_threshold
        articles = fetcher._fetch_high_uncertainty_articles(days_back, threshold, limit)

        if not articles:
            print("[DualProvider] No high-uncertainty articles to evaluate")
            return BatchEvaluationResult(0, 0, 0, 0, [], "", 0)

        print(f"[DualProvider] Evaluating {len(articles)} articles")
        return self.evaluate_batch(articles)

    def get_stats(self) -> Dict:
        """Return provider availability and routing summary."""
        return {
            "groq": {
                "available": self._groq is not None,
                "model": getattr(self._groq, "_llm", None) and getattr(
                    self._groq._llm, "model_name", getattr(self._groq._llm, "model", "?")
                ),
                "routes": "Vietnamese articles",
            },
            "openai": {
                "available": self._openai is not None,
                "model": getattr(self._openai, "_llm", None) and getattr(
                    self._openai._llm, "model_name", getattr(self._openai._llm, "model", "?")
                ),
                "routes": "English/Chinese articles",
            },
            "fallback": "automatic (language-based routing with error retry)",
        }

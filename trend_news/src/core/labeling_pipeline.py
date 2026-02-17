"""
Uncertainty-Based Admin Labeling Pipeline

Scores articles using two independent signals, computes an uncertainty score
from their disagreement, and queues the most uncertain articles for admin labeling.
"""
import os
import sqlite3
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.utils.sentiment import (
    _lexicon_score,
    _VI_POS_LEXICON,
    _VI_NEG_LEXICON,
    get_sentiment,
)
from src.core.sentiment_learning import SentimentLearningManager

try:
    from underthesea import sentiment as _uts_sentiment
    _uts_available = True
except ImportError:
    _uts_sentiment = None
    _uts_available = False


@dataclass
class UncertaintyResult:
    lexicon_score: float
    uts_label: Optional[str]           # 'positive' | 'negative' | 'neutral' | None
    final_score: float
    final_label: str
    uncertainty_score: float           # composite [0, 1]
    signal_conflict: float             # lexicon direction vs uts [0, 1]
    magnitude_uncertainty: float       # proximity to label boundaries [0, 1]
    match_sparsity: float              # 0 = dense lexicon hits, 1 = no hits
    fasttext_label: Optional[str] = None  # if fasttext loaded


# Label boundary thresholds (same as sentiment.py _score_to_label)
_BOUNDARIES = [-0.35, -0.15, 0.15, 0.35]
_BOUNDARY_RADIUS = 0.15

# Sparsity lookup: hit_count → sparsity value
_SPARSITY_MAP = {0: 1.0, 1: 0.7, 2: 0.4}
_SPARSITY_DENSE = 0.1  # 3+ hits


class LabelingPipeline:
    """
    Daily pipeline for surfacing uncertain articles to the admin for labeling.

    Uncertainty is computed from:
      - Signal conflict (45%): disagreement between lexicon direction and underthesea
      - Magnitude uncertainty (30%): proximity to label boundaries
      - Match sparsity (25%): how few lexicon terms matched

    If fasttext is available (FASTTEXT_MODEL_PATH env var), weights shift to
    0.35 / 0.25 / 0.20 / 0.20 with a fourth fasttext_conflict dimension.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            project_root = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            db_path = os.path.join(project_root, "output", "trend_news.db")
        self.db_path = db_path
        self._learning_manager = SentimentLearningManager(db_path)
        self._fasttext_model = None
        self._fasttext_available = self._try_load_fasttext()
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        conn = self._get_connection()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS labeling_queue (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    news_id               INTEGER NOT NULL,
                    news_title            TEXT NOT NULL,
                    news_url              TEXT DEFAULT '',
                    crawl_date            TEXT NOT NULL,
                    lexicon_score         REAL NOT NULL,
                    uts_label             TEXT,
                    final_score           REAL NOT NULL,
                    final_label           TEXT NOT NULL,
                    uncertainty_score     REAL NOT NULL,
                    signal_conflict       REAL NOT NULL,
                    magnitude_uncertainty REAL NOT NULL,
                    match_sparsity        REAL NOT NULL,
                    queue_date            TEXT NOT NULL,
                    status                TEXT NOT NULL DEFAULT 'pending',
                    priority_rank         INTEGER,
                    admin_score           REAL,
                    admin_label           TEXT,
                    admin_comment         TEXT,
                    feedback_id           INTEGER,
                    labeled_at            TIMESTAMP,
                    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (news_id) REFERENCES news_articles(id),
                    FOREIGN KEY (feedback_id) REFERENCES sentiment_feedback(id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_lq_unique_article
                    ON labeling_queue(news_id, queue_date);
                CREATE INDEX IF NOT EXISTS idx_lq_queue_date
                    ON labeling_queue(queue_date);
                CREATE INDEX IF NOT EXISTS idx_lq_status
                    ON labeling_queue(status);
            """)
            conn.commit()
        finally:
            conn.close()

    def _try_load_fasttext(self) -> bool:
        """Attempt to load a fasttext model; fail silently if unavailable."""
        try:
            import fasttext  # type: ignore
        except ImportError:
            return False

        candidate_paths = [
            os.environ.get("FASTTEXT_MODEL_PATH", ""),
            os.path.expanduser("~/.cache/trend_news/fasttext/vi_sentiment.bin"),
            "/data/models/fasttext/vi_sentiment.bin",
        ]
        for path in candidate_paths:
            if path and os.path.isfile(path):
                try:
                    self._fasttext_model = fasttext.load_model(path)
                    return True
                except Exception:
                    pass
        return False

    # ------------------------------------------------------------------
    # Pure computation helpers — no DB writes
    # ------------------------------------------------------------------

    def _count_lexicon_hits(self, title: str) -> int:
        """Count total lexicon term matches (positive + negative) in title."""
        text_lower = title.lower()
        count = 0
        matched_spans: List[Tuple[int, int]] = []

        def _scan(lexicon: List[Tuple[str, float]]) -> None:
            nonlocal count
            for term, _ in lexicon:
                start = 0
                while True:
                    idx = text_lower.find(term, start)
                    if idx == -1:
                        break
                    end = idx + len(term)
                    if not any(s <= idx < e or s < end <= e for s, e in matched_spans):
                        count += 1
                        matched_spans.append((idx, end))
                    start = idx + 1

        _scan(_VI_POS_LEXICON)
        _scan(_VI_NEG_LEXICON)
        return count

    def _compute_signal_conflict(self, lex_score: float, uts_label: Optional[str]) -> float:
        """
        Compute disagreement between lexicon direction and underthesea label.

        Returns a value in [0, 1]:
          - Near 0 = both signals agree strongly
          - Near 1 = signals strongly disagree
        """
        if uts_label is None or uts_label == "neutral":
            return 0.3 if abs(lex_score) < 0.1 else 0.5

        uts_sign = 1.0 if uts_label == "positive" else -1.0
        if lex_score > 0.05:
            lex_sign = 1.0
        elif lex_score < -0.05:
            lex_sign = -1.0
        else:
            lex_sign = 0.0

        if lex_sign == 0.0:
            return 0.4
        if lex_sign == uts_sign:
            # Agreement — stronger signal = less conflict
            return max(0.0, 0.2 - abs(lex_score) * 0.2)
        # Disagreement
        return min(1.0, abs(lex_score) * 0.9 + 0.1)

    def _compute_magnitude_uncertainty(self, final_score: float) -> float:
        """
        Compute uncertainty from proximity to label boundary values.

        Returns 0 when far from all boundaries, 1 when exactly on a boundary.
        """
        min_dist = min(abs(final_score - b) for b in _BOUNDARIES)
        if min_dist >= _BOUNDARY_RADIUS:
            return 0.0
        return 1.0 - (min_dist / _BOUNDARY_RADIUS)

    def _compute_match_sparsity(self, hit_count: int) -> float:
        """
        Returns 1.0 for zero lexicon hits, scaling down to 0.1 for 3+ hits.
        """
        return _SPARSITY_MAP.get(hit_count, _SPARSITY_DENSE)

    def _compute_fasttext_conflict(self, title: str, final_label: str) -> float:
        """Compute conflict between fasttext prediction and final_label."""
        if self._fasttext_model is None:
            return 0.0
        try:
            labels, probs = self._fasttext_model.predict(title[:512], k=1)
            ft_label = labels[0].replace("__label__", "").lower()
            # Normalize label names
            label_map = {
                "positive": "bullish", "negative": "bearish",
                "neutral": "neutral", "bullish": "bullish", "bearish": "bearish",
                "somewhat-bullish": "somewhat-bullish", "somewhat-bearish": "somewhat-bearish",
            }
            ft_norm = label_map.get(ft_label, ft_label)
            final_norm = label_map.get(final_label.lower(), final_label.lower())
            if ft_norm == final_norm:
                return max(0.0, 0.3 - probs[0] * 0.3)
            return min(1.0, 0.4 + (1.0 - probs[0]) * 0.6)
        except Exception:
            return 0.0

    def score_article_uncertainty(self, title: str) -> UncertaintyResult:
        """
        Score an article's uncertainty using all available signals.

        Flow:
          1. Compute raw lexicon score
          2. Get underthesea label (if available)
          3. Get blended final score/label via get_sentiment()
          4. Count lexicon hits for sparsity
          5. Compute 3 (or 4) uncertainty dimensions
          6. Return UncertaintyResult
        """
        lex_score = _lexicon_score(title, _VI_POS_LEXICON, _VI_NEG_LEXICON)

        uts_label: Optional[str] = None
        if _uts_available and _uts_sentiment is not None:
            try:
                uts_label = _uts_sentiment(title[:512])
            except Exception:
                uts_label = None

        final_score, final_label = get_sentiment(title)
        hit_count = self._count_lexicon_hits(title)

        signal_conflict = self._compute_signal_conflict(lex_score, uts_label)
        magnitude_uncertainty = self._compute_magnitude_uncertainty(final_score)
        match_sparsity = self._compute_match_sparsity(hit_count)

        fasttext_label: Optional[str] = None
        if self._fasttext_available:
            ft_conflict = self._compute_fasttext_conflict(title, final_label)
            try:
                labels, _ = self._fasttext_model.predict(title[:512], k=1)  # type: ignore
                fasttext_label = labels[0].replace("__label__", "")
            except Exception:
                pass
            uncertainty_score = min(
                1.0,
                0.35 * signal_conflict
                + 0.25 * magnitude_uncertainty
                + 0.20 * match_sparsity
                + 0.20 * ft_conflict,
            )
        else:
            uncertainty_score = min(
                1.0,
                0.45 * signal_conflict
                + 0.30 * magnitude_uncertainty
                + 0.25 * match_sparsity,
            )

        return UncertaintyResult(
            lexicon_score=lex_score,
            uts_label=uts_label,
            final_score=final_score,
            final_label=final_label,
            uncertainty_score=uncertainty_score,
            signal_conflict=signal_conflict,
            magnitude_uncertainty=magnitude_uncertainty,
            match_sparsity=match_sparsity,
            fasttext_label=fasttext_label,
        )

    # ------------------------------------------------------------------
    # DB operations
    # ------------------------------------------------------------------

    def get_latest_crawl_date(self) -> Optional[str]:
        """Return the most recent crawl_date present in news_articles, or None."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT MAX(crawl_date) FROM news_articles"
            ).fetchone()
            return row[0] if row and row[0] else None
        finally:
            conn.close()

    def build_daily_queue(self, date: str, limit: int = 25) -> Dict:
        """
        Score all articles for the given date and insert the top `limit`
        most uncertain ones into labeling_queue.

        Articles already in the queue for that date are skipped (UNIQUE index).

        Returns:
            Dict with keys: inserted, total_candidates, already_queued, date
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Total articles for this date
            total_for_date = cursor.execute(
                "SELECT COUNT(*) FROM news_articles WHERE crawl_date = ?", (date,)
            ).fetchone()[0]

            cursor.execute(
                """
                SELECT id, title, url
                FROM news_articles
                WHERE crawl_date = ?
                  AND id NOT IN (
                      SELECT news_id FROM labeling_queue WHERE queue_date = ?
                  )
                """,
                (date, date),
            )
            rows = [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

        already_queued = total_for_date - len(rows)

        if not rows:
            return {"inserted": 0, "total_candidates": total_for_date,
                    "already_queued": already_queued, "date": date}

        # Score each article
        scored: List[Tuple[dict, UncertaintyResult]] = []
        for row in rows:
            result = self.score_article_uncertainty(row["title"])
            scored.append((row, result))

        # Sort by uncertainty descending, take top N
        scored.sort(key=lambda x: x[1].uncertainty_score, reverse=True)
        top = scored[:limit]

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            inserted = 0
            for rank, (article, result) in enumerate(top, start=1):
                try:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO labeling_queue (
                            news_id, news_title, news_url, crawl_date,
                            lexicon_score, uts_label, final_score, final_label,
                            uncertainty_score, signal_conflict, magnitude_uncertainty,
                            match_sparsity, queue_date, status, priority_rank
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                        """,
                        (
                            article["id"],
                            article["title"],
                            article.get("url", ""),
                            date,
                            result.lexicon_score,
                            result.uts_label,
                            result.final_score,
                            result.final_label,
                            result.uncertainty_score,
                            result.signal_conflict,
                            result.magnitude_uncertainty,
                            result.match_sparsity,
                            date,
                            rank,
                        ),
                    )
                    inserted += cursor.rowcount
                except sqlite3.IntegrityError:
                    pass  # Already inserted
            conn.commit()
            return {"inserted": inserted, "total_candidates": total_for_date,
                    "already_queued": already_queued, "date": date}
        finally:
            conn.close()

    def get_queue(
        self, date: str, status_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Return queue items for the given date.

        Args:
            date: ISO date string (YYYY-MM-DD)
            status_filter: 'pending' | 'labeled' | 'skipped' | None (all)

        Returns:
            List of dicts ordered by priority_rank ASC.
        """
        conn = self._get_connection()
        try:
            if status_filter:
                cursor = conn.execute(
                    """
                    SELECT * FROM labeling_queue
                    WHERE queue_date = ? AND status = ?
                    ORDER BY priority_rank ASC
                    """,
                    (date, status_filter),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM labeling_queue
                    WHERE queue_date = ?
                    ORDER BY priority_rank ASC
                    """,
                    (date,),
                )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_queue_stats(self, date: str) -> Dict:
        """Return summary statistics for the labeling queue on a given date."""
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status = 'labeled' THEN 1 ELSE 0 END) AS labeled,
                    SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
                    AVG(uncertainty_score) AS avg_uncertainty,
                    MAX(uncertainty_score) AS max_uncertainty,
                    MIN(uncertainty_score) AS min_uncertainty
                FROM labeling_queue
                WHERE queue_date = ?
                """,
                (date,),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {
                "total": 0, "pending": 0, "labeled": 0, "skipped": 0,
                "avg_uncertainty": 0.0, "max_uncertainty": 0.0, "min_uncertainty": 0.0,
            }
        finally:
            conn.close()

    def submit_label(
        self,
        queue_id: int,
        user_score: float,
        user_label: str,
        comment: Optional[str] = None,
    ) -> int:
        """
        Record an admin label for a queue item and feed it into the learning loop.

        Returns:
            The feedback_id created in sentiment_feedback.

        Raises:
            ValueError: If the item doesn't exist or is already labeled.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM labeling_queue WHERE id = ?", (queue_id,)
            )
            row = cursor.fetchone()
        finally:
            conn.close()

        if row is None:
            raise ValueError(f"Queue item {queue_id} not found")
        if row["status"] == "labeled":
            raise ValueError(f"Queue item {queue_id} is already labeled")

        row_dict = dict(row)

        # Feed into the existing learning loop
        feedback_id = self._learning_manager.add_feedback(
            news_title=row_dict["news_title"],
            predicted_score=row_dict["final_score"],
            predicted_label=row_dict["final_label"],
            user_score=user_score,
            user_label=user_label,
            news_id=row_dict["news_id"],
            news_url=row_dict.get("news_url", ""),
            comment=comment,
        )

        # Update queue row
        conn = self._get_connection()
        try:
            conn.execute(
                """
                UPDATE labeling_queue
                SET status = 'labeled',
                    admin_score = ?,
                    admin_label = ?,
                    admin_comment = ?,
                    feedback_id = ?,
                    labeled_at = ?
                WHERE id = ?
                """,
                (
                    user_score,
                    user_label,
                    comment,
                    feedback_id,
                    datetime.now().isoformat(),
                    queue_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return feedback_id

    def skip_item(self, queue_id: int) -> None:
        """Mark a queue item as skipped."""
        conn = self._get_connection()
        try:
            conn.execute(
                "UPDATE labeling_queue SET status = 'skipped' WHERE id = ?",
                (queue_id,),
            )
            conn.commit()
        finally:
            conn.close()

"""Parse TradingAgents historical decisions from ``eval_results/``.

The TradingAgents graph writes one JSON per ``(ticker, trade_date)`` to
``eval_results/<TICKER>/TradingAgentsStrategy_logs/full_states_log_<date>.json``
containing the full agent state — markdown reports for each analyst plus
the final risk-manager judgment in ``final_trade_decision``.

This module turns that directory tree into a stream of
:class:`tradingagents.benchmark.models.Decision` objects suitable for
backtest replay. The interesting piece is :func:`infer_action`, which
classifies the free-text ``final_trade_decision`` into BUY / HOLD / SELL
via a keyword-scoring heuristic — the upstream prompt does *not*
constrain the LLM to a strict canonical phrase, so headings vary from
"# FINAL JUDGMENT: SELL" to "# Risk Management Judge's Final
Determination" with the action buried in the body.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from .models import Action, Decision

logger = logging.getLogger(__name__)

# Filename pattern used by trading_graph._log_state.
_FILENAME_RE = re.compile(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$")

# Keyword groups for action inference. Scores are weighted: a clear
# "SELL" heading is worth more than an inline mention of "selling
# pressure". Tuned against the heading samples observed across
# eval_results/ — see tests for the goldens.
_ACTION_KEYWORDS: Dict[Action, List[Tuple[str, int]]] = {
    Action.BUY: [
        (r"\bBUY\b", 4),
        (r"\bOVERWEIGHT\b", 3),
        (r"\bACCUMULATE\b", 3),
        (r"\bENTER LONG\b", 3),
        (r"\bSCALE IN\b", 2),
        (r"\bADD\b", 1),
    ],
    Action.SELL: [
        (r"\bSELL\b", 4),
        (r"\bUNDERWEIGHT\b", 3),
        (r"\bREDUCE\b", 3),
        (r"\bTRIM\b", 2),
        (r"\bEXIT\b", 2),
        (r"\bDE-?RISK\b", 2),
        (r"\bCUT\b", 1),
    ],
    Action.HOLD: [
        (r"\bHOLD\b", 4),
        (r"\bNEUTRAL\b", 3),
        (r"\bMAINTAIN\b", 2),
        (r"\bSTAY\b", 1),
        (r"\bWAIT\b", 1),
    ],
}

# How many leading characters of the decision text we score on. The action
# is virtually always stated in the first heading + executive summary; the
# rest of the body just defends it (and frequently mentions all three
# actions while arguing against them).
_SCORE_WINDOW_CHARS = 1500


def infer_action(decision_text: str) -> Action:
    """Classify a free-text Risk Manager verdict into BUY / HOLD / SELL.

    Strategy:

    1. Score the first ``_SCORE_WINDOW_CHARS`` chars by counting weighted
       matches of each action's keyword set.
    2. Pick the highest scoring action.
    3. Ties go to HOLD (conservative — don't trade on ambiguous signal).
    4. Empty / unscoreable text also returns HOLD.
    """
    if not decision_text:
        return Action.HOLD

    window = decision_text[:_SCORE_WINDOW_CHARS].upper()
    scores: Dict[Action, int] = defaultdict(int)
    for action, patterns in _ACTION_KEYWORDS.items():
        for pattern, weight in patterns:
            for _ in re.finditer(pattern, window):
                scores[action] += weight

    if not scores:
        return Action.HOLD

    best_action, best_score = max(scores.items(), key=lambda kv: kv[1])
    # Tie check — if any other action equals the best score, fall back to HOLD.
    if sum(1 for s in scores.values() if s == best_score) > 1:
        return Action.HOLD
    return best_action


def _normalize_ticker(ticker_dir: str) -> str:
    """Strip ``.VN`` so HPG and HPG.VN collapse to the same canonical key."""
    return ticker_dir.upper().replace(".VN", "")


def _read_state_file(path: str) -> Optional[Tuple[str, str, str]]:
    """Return ``(ticker, decision_date, decision_text)`` for one log file.

    Returns ``None`` and logs a warning on any malformed file rather than
    raising — a single bad log shouldn't break the whole parse pass.
    """
    match = _FILENAME_RE.search(path)
    if not match:
        return None
    date_from_filename = match.group(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot parse %s: %s", path, exc)
        return None

    # File schema is ``{date_key: {full_state_dict}}`` — one date per file
    # in practice. Use the filename's date as authoritative since the
    # state's ``trade_date`` is sometimes a string with timezone hints.
    if not isinstance(data, dict) or not data:
        logger.warning("Empty / non-dict log %s", path)
        return None
    state = next(iter(data.values()))
    if not isinstance(state, dict):
        logger.warning("Inner state not a dict in %s", path)
        return None

    ticker = state.get("company_of_interest") or ""
    ticker = _normalize_ticker(ticker)
    if not ticker:
        # Fall back to the parent directory name if state didn't record it.
        ticker_dir = os.path.basename(os.path.dirname(os.path.dirname(path)))
        ticker = _normalize_ticker(ticker_dir)

    decision_text = state.get("final_trade_decision") or ""
    return ticker, date_from_filename, decision_text


def load_decisions(
    eval_results_dir: str = "eval_results",
    *,
    strategy_id: str = "tradingagents",
    tickers: Optional[Iterable[str]] = None,
) -> List[Decision]:
    """Walk ``eval_results_dir`` and return all parseable decisions.

    Decisions are returned sorted by ``(decision_date, ticker)`` so a
    backtest can iterate them chronologically. Duplicate ``(ticker,
    date)`` entries (e.g. one in ``HPG/`` and one in ``HPG.VN/``) are
    deduplicated keeping the longer rationale.
    """
    ticker_filter = (
        {_normalize_ticker(t) for t in tickers} if tickers is not None else None
    )

    pattern = os.path.join(
        eval_results_dir, "*", "TradingAgentsStrategy_logs", "full_states_log_*.json"
    )
    paths = sorted(glob.glob(pattern))
    by_key: Dict[Tuple[str, str], Decision] = {}

    for path in paths:
        parsed = _read_state_file(path)
        if not parsed:
            continue
        ticker, date_str, decision_text = parsed
        if ticker_filter is not None and ticker not in ticker_filter:
            continue

        action = infer_action(decision_text)
        decision = Decision(
            strategy_id=strategy_id,
            ticker=ticker,
            decision_date=date_str,
            action=action,
            rationale=decision_text or None,
            source_path=path,
        )

        # Dedupe: prefer the entry with the richer rationale.
        key = (ticker, date_str)
        existing = by_key.get(key)
        if existing is None or len(decision.rationale or "") > len(existing.rationale or ""):
            by_key[key] = decision

    return sorted(by_key.values(), key=lambda d: (d.decision_date, d.ticker))

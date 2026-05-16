"""User's real portfolio — the positions they actually hold.

Lives in ``benchmarks/state/user_portfolio.json``. The daily orchestrator
reads this file at run-time and cross-references today's TradingAgents
signals so the user sees, for each ticker they actually own, what the
agent panel is saying (HOLD / SELL / etc.) plus mark-to-market P&L.

Schema is intentionally minimal — the user edits it by hand or via a
small dashboard form (Phase 5). No broker integration in scope.

Example::

    {
      "updated_at": "2026-05-16",
      "positions": [
        {"ticker": "HPG", "quantity": 1000, "entry_date": "2026-04-01",
         "entry_price": 30000, "notes": "DCA on Q1 earnings"},
        {"ticker": "VNM", "quantity": 500, "entry_date": "2026-05-01",
         "entry_price": 62000}
      ]
    }
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import Action, Decision

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join("benchmarks", "state", "user_portfolio.json")


@dataclass(frozen=True)
class UserPosition:
    """One row in the user's holdings.

    Values are normalized on load — ticker uppercased, ``.VN`` suffix
    stripped — so downstream lookups against the price book and
    TradingAgents decisions don't have to special-case suffix variants.
    """

    ticker: str
    quantity: int
    entry_date: str
    entry_price: float
    notes: Optional[str] = None

    def market_value(self, price_vnd: float) -> float:
        return self.quantity * price_vnd

    def unrealized_pnl(self, price_vnd: float) -> float:
        return (price_vnd - self.entry_price) * self.quantity

    def unrealized_return_pct(self, price_vnd: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (price_vnd / self.entry_price) - 1.0


@dataclass
class UserPortfolio:
    """Container of :class:`UserPosition` rows with file-backed persistence."""

    positions: List[UserPosition] = field(default_factory=list)
    updated_at: Optional[str] = None
    source_path: Optional[str] = None

    @property
    def tickers(self) -> List[str]:
        return [p.ticker for p in self.positions]

    def get(self, ticker: str) -> Optional[UserPosition]:
        upper = ticker.upper().replace(".VN", "")
        return next((p for p in self.positions if p.ticker == upper), None)

    @classmethod
    def load(cls, path: str = _DEFAULT_PATH) -> "UserPortfolio":
        """Load from JSON; returns an empty portfolio when the file is missing.

        Empty file is the expected state on first install — the dashboard
        / docs walk the user through populating it. We deliberately do
        NOT auto-create the file: the absence is a hint that the daily
        brief should skip the "your holdings" section.
        """
        if not os.path.exists(path):
            return cls(source_path=path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Cannot read user portfolio %s: %s — treating as empty", path, exc)
            return cls(source_path=path)

        positions: List[UserPosition] = []
        for row in data.get("positions") or []:
            if not isinstance(row, dict):
                continue
            try:
                positions.append(
                    UserPosition(
                        ticker=str(row["ticker"]).upper().replace(".VN", ""),
                        quantity=int(row["quantity"]),
                        entry_date=str(row["entry_date"])[:10],
                        entry_price=float(row["entry_price"]),
                        notes=(row.get("notes") or None),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skipping malformed user_portfolio row %s: %s", row, exc)
        return cls(positions=positions, updated_at=data.get("updated_at"), source_path=path)

    def save(self, path: Optional[str] = None) -> None:
        """Write the portfolio back to disk (sorted by ticker for readability)."""
        target = path or self.source_path or _DEFAULT_PATH
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        payload = {
            "updated_at": self.updated_at,
            "positions": [
                {
                    "ticker": p.ticker,
                    "quantity": p.quantity,
                    "entry_date": p.entry_date,
                    "entry_price": p.entry_price,
                    "notes": p.notes,
                }
                for p in sorted(self.positions, key=lambda x: x.ticker)
            ],
        }
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)


# ── Decision cross-reference ────────────────────────────────────────────


@dataclass(frozen=True)
class UserAction:
    """Today's recommended action for one user-held ticker."""

    position: UserPosition
    decision: Optional[Decision]   # None if no fresh agent run today
    today_close_vnd: Optional[float]

    @property
    def action(self) -> Optional[Action]:
        return self.decision.action if self.decision else None

    @property
    def urgency(self) -> str:
        """One-word tag for the daily brief ordering."""
        if self.action == Action.SELL:
            return "act"   # SELL on a held position is the highest-attention case
        if self.action == Action.BUY:
            return "noop"  # already held, agent says BUY → just keep
        if self.action == Action.HOLD:
            return "ok"
        return "stale"


def cross_reference(
    portfolio: UserPortfolio,
    decisions: List[Decision],
    today_prices: Dict[str, Optional[float]],
    decision_date: str,
) -> List[UserAction]:
    """For each held position, find today's decision and price.

    Decisions are filtered to ``decision_date`` only; older signals
    aren't surfaced as "today's action" — they'd belong in a separate
    history view.
    """
    decisions_by_ticker = {
        d.ticker: d for d in decisions if d.decision_date == decision_date
    }
    actions: List[UserAction] = []
    for position in portfolio.positions:
        actions.append(
            UserAction(
                position=position,
                decision=decisions_by_ticker.get(position.ticker),
                today_close_vnd=today_prices.get(position.ticker),
            )
        )
    return actions

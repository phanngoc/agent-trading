"""Data model for the benchmark pipeline.

Four frozen dataclasses form the entire schema written to disk and passed
between modules:

* :class:`Decision` — one (strategy, ticker, date, action) tuple. Produced
  by either ``eval_results`` replay (TradingAgents) or a baseline strategy.
* :class:`Position` — an open holding. Mutable state owned by Portfolio.
* :class:`Trade` — a closed round-trip with realized P&L. Append-only log.
* :class:`Portfolio` — cash + positions + closed trades + the unsettled-
  cash queue (for T+2.5 VN settlement).

All structures are JSON-serializable via :func:`asdict` / :func:`from_dict`
so we can checkpoint a portfolio's state between daily runs without
touching a database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date as date_cls, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────────────


class Action(str, Enum):
    """The three actions a strategy can emit.

    Stored as strings so JSON round-trips trivially and unknown values
    surface as a clear ``ValueError`` from :meth:`Action`.
    """

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


# ── Helpers ───────────────────────────────────────────────────────────────


def _iso_date(value) -> str:
    """Coerce a date / datetime / str to an ISO ``YYYY-MM-DD`` string."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date_cls):
        return value.isoformat()
    if isinstance(value, str):
        # Validate format — raises if malformed so we fail fast on bad input.
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    raise TypeError(f"Cannot convert {type(value).__name__} to ISO date")


# ── Decision ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Decision:
    """One strategy's verdict on one ticker on one day.

    ``confidence`` and ``rationale`` are optional — baselines won't set
    them but TradingAgents and (later) LSTM do. ``source_path`` records
    where the decision came from so we can audit a backtest result back
    to its eval_results JSON.
    """

    strategy_id: str          # 'tradingagents' | 'sma_crossover' | ...
    ticker: str               # bare symbol, no .VN suffix
    decision_date: str        # ISO date the decision was made (EOD)
    action: Action
    confidence: Optional[float] = None       # 0..1 if the strategy emits one
    rationale: Optional[str] = None          # markdown explanation
    source_path: Optional[str] = None        # provenance pointer

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action"] = self.action.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Decision":
        return cls(
            strategy_id=data["strategy_id"],
            ticker=data["ticker"].upper(),
            decision_date=_iso_date(data["decision_date"]),
            action=Action(data["action"]),
            confidence=data.get("confidence"),
            rationale=data.get("rationale"),
            source_path=data.get("source_path"),
        )


# ── Position ──────────────────────────────────────────────────────────────


@dataclass
class Position:
    """An open holding inside a Portfolio.

    ``quantity`` is in shares, ``avg_cost`` in VND per share (already
    inclusive of buy fees so realized P&L math is simple subtraction).
    ``opened_date`` is the fill date of the BUY (not the decision date).
    """

    ticker: str
    quantity: int
    avg_cost: float
    opened_date: str
    opened_by_decision_date: str   # decision date that triggered the BUY

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_cost) * self.quantity

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Position":
        return cls(
            ticker=data["ticker"].upper(),
            quantity=int(data["quantity"]),
            avg_cost=float(data["avg_cost"]),
            opened_date=_iso_date(data["opened_date"]),
            opened_by_decision_date=_iso_date(data["opened_by_decision_date"]),
        )


# ── Trade (closed round-trip) ─────────────────────────────────────────────


@dataclass(frozen=True)
class Trade:
    """A closed round-trip (BUY followed by matching SELL).

    All fees baked into ``entry_price``/``exit_price`` already so
    ``realized_pnl_vnd`` is the literal cash delta.
    """

    ticker: str
    quantity: int
    entry_date: str
    entry_price: float            # incl. buy fees, so VND/share paid
    exit_date: str
    exit_price: float             # incl. sell fees, so VND/share received
    decision_strategy_id: str     # who made the call
    entry_decision_date: str
    exit_decision_date: str

    @property
    def realized_pnl_vnd(self) -> float:
        return (self.exit_price - self.entry_price) * self.quantity

    @property
    def realized_return_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.exit_price / self.entry_price) - 1.0

    @property
    def holding_days(self) -> int:
        entry = datetime.strptime(self.entry_date, "%Y-%m-%d").date()
        exit_ = datetime.strptime(self.exit_date, "%Y-%m-%d").date()
        return (exit_ - entry).days

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["realized_pnl_vnd"] = self.realized_pnl_vnd
        d["realized_return_pct"] = self.realized_return_pct
        d["holding_days"] = self.holding_days
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trade":
        return cls(
            ticker=data["ticker"].upper(),
            quantity=int(data["quantity"]),
            entry_date=_iso_date(data["entry_date"]),
            entry_price=float(data["entry_price"]),
            exit_date=_iso_date(data["exit_date"]),
            exit_price=float(data["exit_price"]),
            decision_strategy_id=data["decision_strategy_id"],
            entry_decision_date=_iso_date(data["entry_decision_date"]),
            exit_decision_date=_iso_date(data["exit_decision_date"]),
        )


# ── Unsettled-cash entry (T+2.5 gating) ──────────────────────────────────


@dataclass
class UnsettledCash:
    """Cash from a recent SELL that isn't usable until ``available_on``.

    Models HOSE/HNX T+2.5 settlement. The Portfolio's "buying power"
    excludes any UnsettledCash whose date hasn't arrived yet.
    """

    amount_vnd: float
    available_on: str   # ISO date the cash unlocks (inclusive)


# ── Portfolio ────────────────────────────────────────────────────────────


@dataclass
class Portfolio:
    """A paper portfolio for one strategy.

    Mutable: ``cash``, ``positions``, ``closed_trades``, and the
    ``unsettled_cash`` queue all evolve as the simulator processes
    decisions in chronological order. The Portfolio is the *only* place
    that owns state; everything else (Decision, baselines, metrics) is
    a pure function.
    """

    strategy_id: str
    initial_capital_vnd: float
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    closed_trades: List[Trade] = field(default_factory=list)
    unsettled_cash: List[UnsettledCash] = field(default_factory=list)
    # Date the strategy was last advanced to. Used to detect replays that
    # try to act on a past date (which would be lookahead bias).
    last_advanced_to: Optional[str] = None

    # ── Cash + buying power ──────────────────────────────────────────
    def available_cash(self, as_of_date: str) -> float:
        """Cash that has finished settling by ``as_of_date`` (inclusive)."""
        target = _iso_date(as_of_date)
        settled = sum(
            u.amount_vnd for u in self.unsettled_cash if u.available_on <= target
        )
        return self.cash + settled

    def nav(self, prices: Dict[str, float], as_of_date: str) -> float:
        """Mark-to-market: cash (incl. unsettled) + positions at given prices."""
        equity = sum(p.market_value(prices.get(p.ticker, p.avg_cost)) for p in self.positions.values())
        all_cash = self.cash + sum(u.amount_vnd for u in self.unsettled_cash)
        return all_cash + equity

    # ── Serialization ────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "initial_capital_vnd": self.initial_capital_vnd,
            "cash": self.cash,
            "positions": [p.to_dict() for p in self.positions.values()],
            "closed_trades": [t.to_dict() for t in self.closed_trades],
            "unsettled_cash": [asdict(u) for u in self.unsettled_cash],
            "last_advanced_to": self.last_advanced_to,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Portfolio":
        return cls(
            strategy_id=data["strategy_id"],
            initial_capital_vnd=float(data["initial_capital_vnd"]),
            cash=float(data["cash"]),
            positions={
                p["ticker"].upper(): Position.from_dict(p) for p in data.get("positions", [])
            },
            closed_trades=[Trade.from_dict(t) for t in data.get("closed_trades", [])],
            unsettled_cash=[
                UnsettledCash(amount_vnd=float(u["amount_vnd"]), available_on=_iso_date(u["available_on"]))
                for u in data.get("unsettled_cash", [])
            ],
            last_advanced_to=data.get("last_advanced_to"),
        )

    @classmethod
    def empty(cls, strategy_id: str, initial_capital_vnd: float) -> "Portfolio":
        """Factory for a freshly capitalized portfolio (Day 0)."""
        return cls(
            strategy_id=strategy_id,
            initial_capital_vnd=float(initial_capital_vnd),
            cash=float(initial_capital_vnd),
        )

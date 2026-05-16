"""Trading-day calendar for HOSE / HNX / UPCOM.

Source of truth is the cached VNINDEX price file — every date that appears
there was a trading session, so we don't need a separately maintained
holiday list (which would inevitably drift). The helper exposed here is
:func:`is_trading_day`, used by the daily orchestrator to skip weekends
and Vietnamese holidays without firing TradingAgents pointlessly.

When the cache is stale (e.g. weekend mornings before the new week's
calendar has been backfilled), the helper falls back to a weekday check —
better to over-run than to silently skip.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

import pandas as pd


_VNINDEX_FILE_DEFAULT = os.path.join("benchmarks", "state", "prices", "VNINDEX.csv")


def _load_cached_sessions(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    try:
        df = pd.read_csv(path, usecols=["Date"])
    except (ValueError, OSError):
        return set()
    return set(df["Date"].astype(str).str.slice(0, 10).tolist())


def is_trading_day(d: str | date, vnindex_path: str = _VNINDEX_FILE_DEFAULT) -> bool:
    """Return True if ``d`` is (or was) an HOSE trading session.

    Strategy:

    1. If we have a cached row for that exact date in VNINDEX.csv, it's
       a trading day.
    2. If the date is in the future (or beyond cache reach), fall back
       to a weekday check — VN holidays can't be detected that way, but
       it's the right default since the orchestrator runs same-day at
       market close and the price cache will already include today.
    3. Saturdays/Sundays are never trading days.
    """
    if isinstance(d, date):
        d_iso = d.isoformat()
    else:
        d_iso = d[:10]

    dt = datetime.strptime(d_iso, "%Y-%m-%d").date()
    # Weekend short-circuit — never a session.
    if dt.weekday() >= 5:
        return False

    sessions = _load_cached_sessions(vnindex_path)
    if not sessions:
        # No cache yet: trust the weekday check.
        return True
    if d_iso in sessions:
        return True
    # Date is within cache range but not present → holiday.
    earliest, latest = min(sessions), max(sessions)
    if earliest <= d_iso <= latest:
        return False
    # Outside the cached range → trust weekday fallback.
    return True


def latest_trading_day(today: Optional[str | date] = None, vnindex_path: str = _VNINDEX_FILE_DEFAULT) -> Optional[str]:
    """Return the most recent ``date`` ≤ ``today`` that is a trading day.

    Useful when you're running a batch that wants to label its output
    with the latest session even on a weekend or holiday.
    """
    if today is None:
        today = date.today()
    if isinstance(today, date):
        cursor = today
    else:
        cursor = datetime.strptime(today[:10], "%Y-%m-%d").date()

    for _ in range(10):  # bounded scan — VN holidays cluster at Tết but never longer than ~9d
        if is_trading_day(cursor, vnindex_path):
            return cursor.isoformat()
        cursor = date.fromordinal(cursor.toordinal() - 1)
    return None

"""
Signal Broadcaster — WebSocket hub for real-time ticker signal updates.

Architecture:
  - ConnectionManager: tracks active WS connections per ticker subscription
  - SignalWatcher: background task polling DB for new articles → emit on change
  - Clients subscribe with: ws://host/api/v3/stream?tickers=VCB,HPG&apikey=xxx

Message format (JSON):
  {
    "type": "signal_update",
    "ticker": "VCB",
    "score": 0.35,
    "label": "Bullish",
    "delta": 0.12,          // score change since last emission
    "article_count": 15,
    "latest_headline": "...",
    "timestamp": "2026-03-23T06:00:00Z"
  }

  {
    "type": "market_update",
    "market_score": 0.07,
    "market_label": "Neutral",
    "global_risk": "HIGH",
    "timestamp": "..."
  }

  {
    "type": "intel_alert",
    "threat_level": "critical",
    "title": "Iran war...",
    "wm_category": "geopolitical",
    "geo_relevance": 0.8,
    "timestamp": "..."
  }
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

from src.core.ticker_mapper import TICKER_ALIASES
from src.utils.sentiment import get_sentiment, _score_to_label


# ── Connection Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """Tracks WebSocket connections and routes messages to subscribers."""

    def __init__(self):
        # ticker → set of WebSockets subscribed
        self._subscriptions: Dict[str, Set[WebSocket]] = defaultdict(set)
        # WebSocket → set of tickers it subscribed to
        self._client_tickers: Dict[WebSocket, Set[str]] = defaultdict(set)
        # broadcast channel (all clients)
        self._all: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket, tickers: List[str]) -> None:
        await ws.accept()
        self._all.add(ws)
        for t in tickers:
            self._subscriptions[t.upper()].add(ws)
            self._client_tickers[ws].add(t.upper())
        await ws.send_text(json.dumps({
            "type": "connected",
            "subscribed_tickers": [t.upper() for t in tickers],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }))

    def disconnect(self, ws: WebSocket) -> None:
        self._all.discard(ws)
        for t in self._client_tickers.pop(ws, []):
            self._subscriptions[t].discard(ws)

    async def emit_ticker(self, ticker: str, payload: dict) -> None:
        """Send signal update to all subscribers of this ticker."""
        dead = set()
        for ws in list(self._subscriptions.get(ticker, [])):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast(self, payload: dict) -> None:
        """Broadcast to ALL connected clients."""
        dead = set()
        for ws in list(self._all):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def connected_count(self) -> int:
        return len(self._all)

    def ticker_subscriber_count(self, ticker: str) -> int:
        return len(self._subscriptions.get(ticker, []))


# Global singleton
manager = ConnectionManager()


# ── Signal Watcher ────────────────────────────────────────────────────────────

class SignalWatcher:
    """
    Background task that polls DB for new articles and emits WS updates
    when ticker signal scores change significantly.
    """

    POLL_INTERVAL = 60       # seconds between polls
    DELTA_THRESHOLD = 0.10   # min score change to emit update
    WM_CHECK_INTERVAL = 120  # seconds between WM intel checks

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._last_scores: Dict[str, float] = {}
        self._last_article_count: Dict[str, int] = {}
        self._last_wm_count: int = 0
        self._running = False

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _compute_ticker_score(self, ticker: str) -> tuple[float, int, str]:
        """Returns (avg_score, article_count, latest_headline)."""
        aliases = TICKER_ALIASES.get(ticker, [ticker])
        conn = self._db()
        try:
            c = conn.cursor()
            since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            conds = " OR ".join(["title LIKE ?" for _ in aliases])
            c.execute(f"""
                SELECT title, sentiment_score FROM news_articles
                WHERE ({conds}) AND crawled_at >= ?
                ORDER BY crawled_at DESC LIMIT 30
            """, [f"%{a}%" for a in aliases] + [since])
            rows = c.fetchall()
        finally:
            conn.close()

        if not rows:
            return 0.0, 0, ""

        scores = []
        for title, db_score in rows:
            if db_score is not None:
                scores.append(float(db_score))
            else:
                s, _ = get_sentiment(title)
                scores.append(s)

        avg = sum(scores) / len(scores)
        latest = rows[0][0] if rows else ""
        return round(avg, 4), len(rows), latest

    def _get_new_wm_critical(self) -> List[dict]:
        """Fetch WM critical articles added since last check."""
        conn = self._db()
        try:
            c = conn.cursor()
            today = date.today().isoformat()
            c.execute("""
                SELECT id, title, wm_category, threat_level, geo_relevance
                FROM wm_articles
                WHERE crawl_date = ? AND threat_level IN ('critical','high')
                ORDER BY id DESC LIMIT 5
            """, [today])
            cols = [d[0] for d in c.description]
            rows = [dict(zip(cols, r)) for r in c.fetchall()]
            # Filter truly new ones
            max_id = max((r["id"] for r in rows), default=0)
            new = [r for r in rows if r["id"] > self._last_wm_count]
            self._last_wm_count = max_id
            return new
        except Exception:
            return []
        finally:
            conn.close()

    async def _check_tickers(self) -> None:
        """Poll all subscribed tickers and emit updates on score changes."""
        subscribed = list(manager._subscriptions.keys())
        if not subscribed:
            return

        for ticker in subscribed:
            try:
                score, count, headline = self._compute_ticker_score(ticker)
                prev_score = self._last_scores.get(ticker, score)
                delta = score - prev_score

                # Emit if score changed significantly OR new articles arrived
                prev_count = self._last_article_count.get(ticker, count)
                should_emit = (abs(delta) >= self.DELTA_THRESHOLD or
                               count > prev_count + 2)

                self._last_scores[ticker] = score
                self._last_article_count[ticker] = count

                if should_emit and manager.ticker_subscriber_count(ticker) > 0:
                    await manager.emit_ticker(ticker, {
                        "type": "signal_update",
                        "ticker": ticker,
                        "score": score,
                        "label": _score_to_label(score),
                        "delta": round(delta, 4),
                        "article_count": count,
                        "latest_headline": headline[:100] if headline else "",
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    })
            except Exception as e:
                pass  # Don't crash watcher on individual ticker failure

    async def _check_wm_intel(self) -> None:
        """Broadcast new WM critical/high events to all clients."""
        new_alerts = self._get_new_wm_critical()
        for alert in new_alerts:
            if manager.connected_count > 0:
                await manager.broadcast({
                    "type": "intel_alert",
                    "threat_level": alert.get("threat_level"),
                    "title": alert.get("title", ""),
                    "wm_category": alert.get("wm_category", ""),
                    "geo_relevance": alert.get("geo_relevance", 0.0),
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                })

    async def run(self) -> None:
        """Main watch loop. Run as background asyncio task."""
        self._running = True
        wm_ticks = 0
        while self._running:
            await asyncio.sleep(self.POLL_INTERVAL)
            if manager.connected_count == 0:
                continue
            await self._check_tickers()
            wm_ticks += self.POLL_INTERVAL
            if wm_ticks >= self.WM_CHECK_INTERVAL:
                await self._check_wm_intel()
                wm_ticks = 0

    def stop(self) -> None:
        self._running = False

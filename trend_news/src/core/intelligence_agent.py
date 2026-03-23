"""
TrendRadar Intelligence Agent

Runs daily at 6:00 AM to generate morning briefing reports.
Synthesizes VN news sentiment + WM global intel → actionable report.

Usage:
    agent = IntelligenceAgent(db_path="output/trend_news.db")
    report = agent.run_morning_brief(watchlist=["VCB","HPG","VIC","GAS","VNM"])
    agent.save_report(report)
    agent.send_telegram(report, chat_id="...")
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Dict, List, Optional, Any

import requests

from src.utils.sentiment import get_sentiment
from src.core.ticker_mapper import TICKER_ALIASES
from src.core.sector_mapper import SECTOR_TICKERS, SECTOR_DISPLAY, TICKER_SECTOR


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TickerSignal:
    ticker: str
    company: str
    score: float
    label: str
    confidence: float
    article_count: int
    top_headlines: List[str]
    wm_threat: str = "info"
    market_signal: str = "neutral"
    sector: str = ""
    price_change_pct: Optional[float] = None

    @property
    def icon(self) -> str:
        icons = {"Bullish": "⬆️", "Somewhat-Bullish": "↗️",
                 "Neutral": "➡️", "Somewhat-Bearish": "↘️", "Bearish": "⬇️"}
        return icons.get(self.label, "➡️")

    @property
    def emoji(self) -> str:
        if self.score >= 0.20: return "🟢"
        if self.score <= -0.20: return "🔴"
        return "⚪"


@dataclass
class SectorSignal:
    sector: str
    display_name: str
    avg_score: float
    label: str
    ticker_count: int
    bullish: int
    bearish: int
    neutral: int
    top_tickers: List[str]
    wm_impact: str = "neutral"     # how WM events affect this sector


@dataclass
class MorningReport:
    report_date: str
    market_outlook: str                  # Bullish/Bearish/Neutral
    market_score: float
    global_risk: str                     # HIGH/MEDIUM/LOW
    critical_events: int
    high_events: int
    ticker_signals: List[TickerSignal]
    sector_signals: List[SectorSignal]
    top_picks: List[TickerSignal]        # Top 3 bullish
    risk_alerts: List[TickerSignal]      # Top 3 bearish
    global_context: List[Dict]           # WM critical articles
    synthesis: str                       # LLM-generated summary (vi)
    generated_at: str = ""

    def to_telegram_md(self) -> str:
        """Format report for Telegram markdown."""
        lines = []
        date_str = self.report_date
        risk_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(self.global_risk, "⚪")
        outlook_icon = {"Bullish": "🟢", "Bearish": "🔴", "Neutral": "⚪"}.get(
            self.market_outlook, "⚪")

        lines.append(f"📊 *TRENDRADAR MORNING BRIEF — {date_str}*")
        lines.append("")

        # Global context
        lines.append("🌍 *BỐI CẢNH TOÀN CẦU*")
        for e in self.global_context[:3]:
            lvl = e.get("threat_level","")
            icon = "🔴" if lvl == "critical" else "🟠" if lvl == "high" else "⚠️"
            lines.append(f"  {icon} {e.get('title','')[:70]}")
        lines.append("")

        # Market outlook
        lines.append("📈 *THỊ TRƯỜNG HÔM NAY*")
        lines.append(f"  Tâm lý: {outlook_icon} *{self.market_outlook}* "
                     f"(score: {self.market_score:+.2f})")
        lines.append(f"  Rủi ro toàn cầu: {risk_icon} *{self.global_risk}* "
                     f"({self.critical_events} critical, {self.high_events} high events)")
        lines.append("")

        # LLM synthesis
        if self.synthesis:
            lines.append("🤖 *PHÂN TÍCH AI*")
            lines.append(f"  {self.synthesis}")
            lines.append("")

        # Top picks
        if self.top_picks:
            lines.append("🎯 *THEO DÕI HÔM NAY*")
            for i, t in enumerate(self.top_picks[:5], 1):
                headline = t.top_headlines[0][:60] if t.top_headlines else ""
                lines.append(f"  {i}\\. *{t.ticker}* {t.icon} {t.label}  —  {headline}")
            lines.append("")

        # Risk alerts
        if self.risk_alerts:
            lines.append("⚠️ *RỦI RO CẦN THEO DÕI*")
            for t in self.risk_alerts[:3]:
                headline = t.top_headlines[0][:60] if t.top_headlines else ""
                lines.append(f"  🔴 *{t.ticker}* {t.label}  —  {headline}")
            lines.append("")

        # Sector heatmap
        lines.append("🗂️ *PHÂN TÍCH NGÀNH*")
        for s in sorted(self.sector_signals, key=lambda x: x.avg_score, reverse=True)[:6]:
            icon = "🟢" if s.avg_score >= 0.15 else "🔴" if s.avg_score <= -0.15 else "⚪"
            lines.append(f"  {icon} {s.display_name}: {s.label} "
                         f"({s.bullish}↑/{s.neutral}➡/{s.bearish}↓)")
        lines.append("")

        lines.append("📌 _Đây là phân tích dữ liệu, không phải khuyến nghị đầu tư\\._")
        lines.append(f"_Tạo lúc: {self.generated_at}_")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


# ── Intelligence Agent ────────────────────────────────────────────────────────

class IntelligenceAgent:
    """
    Daily intelligence agent that synthesizes market data into actionable reports.
    Designed to run as a cron job at 6:00 AM.
    """

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    GROQ_MODEL   = "llama-3.3-70b-versatile"

    def __init__(
        self,
        db_path: str = "output/trend_news.db",
        groq_api_key: Optional[str] = None,
        days_back: int = 1,
    ):
        self.db_path = db_path
        self.groq_api_key = groq_api_key or os.environ.get("GROQ_API_KEY", "")
        self.days_back = days_back

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ── Data fetching ─────────────────────────────────────────────────────────

    def _fetch_ticker_articles(self, ticker: str, limit: int = 30) -> List[Dict]:
        """Fetch recent articles matching ticker aliases from DB."""
        from src.core.ticker_mapper import TICKER_ALIASES
        aliases = TICKER_ALIASES.get(ticker, [ticker])
        conn = self._db()
        try:
            c = conn.cursor()
            conditions = " OR ".join(["title LIKE ?" for _ in aliases])
            params = [f"%{a}%" for a in aliases]
            c.execute(f"""
                SELECT title, url, sentiment_score, sentiment_label, crawled_at, source_id
                FROM news_articles
                WHERE ({conditions})
                  AND crawled_at >= datetime('now', '-{self.days_back} days')
                ORDER BY crawled_at DESC
                LIMIT ?
            """, params + [limit])
            cols = [d[0] for d in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        finally:
            conn.close()

    def _fetch_wm_intel(self, threat_levels: Optional[List[str]] = None) -> List[Dict]:
        """Fetch today's WM articles, filtered by threat level."""
        conn = self._db()
        try:
            c = conn.cursor()
            today = date.today().isoformat()
            if threat_levels:
                placeholders = ",".join("?" * len(threat_levels))
                c.execute(f"""
                    SELECT title, source_name, wm_category, threat_level, geo_relevance, url
                    FROM wm_articles
                    WHERE crawl_date = ? AND threat_level IN ({placeholders})
                    ORDER BY geo_relevance DESC, threat_level ASC
                    LIMIT 20
                """, [today] + threat_levels)
            else:
                c.execute("""
                    SELECT title, source_name, wm_category, threat_level, geo_relevance, url
                    FROM wm_articles
                    WHERE crawl_date = ?
                    ORDER BY geo_relevance DESC
                    LIMIT 20
                """, [today])
            cols = [d[0] for d in c.description]
            return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []
        finally:
            conn.close()

    def _wm_stats(self) -> Dict:
        """Get WM threat stats for today."""
        conn = self._db()
        try:
            c = conn.cursor()
            today = date.today().isoformat()
            c.execute("""
                SELECT threat_level, COUNT(*) FROM wm_articles
                WHERE crawl_date = ? GROUP BY threat_level
            """, [today])
            return dict(c.fetchall())
        except Exception:
            return {}
        finally:
            conn.close()

    # ── Signal computation ────────────────────────────────────────────────────

    def _compute_ticker_signal(self, ticker: str) -> TickerSignal:
        """Compute sentiment signal for a single ticker."""
        articles = self._fetch_ticker_articles(ticker)
        company = TICKER_ALIASES.get(ticker, [ticker])[0]
        sector = TICKER_SECTOR.get(ticker, "")

        if not articles:
            return TickerSignal(
                ticker=ticker, company=company, score=0.0,
                label="Neutral", confidence=0.3, article_count=0,
                top_headlines=[], sector=sector,
            )

        scores = []
        for a in articles:
            db_score = a.get("sentiment_score")
            if db_score is not None:
                scores.append((float(db_score), 0.85))
            else:
                s, _ = get_sentiment(a["title"])
                scores.append((s, 0.50))

        # Weighted average
        total_w = sum(c for _, c in scores)
        avg_score = sum(s * c for s, c in scores) / total_w if total_w else 0.0
        avg_conf = total_w / len(scores) if scores else 0.5

        # Label
        from src.utils.sentiment import _score_to_label
        label = _score_to_label(avg_score)

        # WM threat context (sector-aware)
        wm_threat = "info"
        wm_signal = "neutral"
        wm_today = self._fetch_wm_intel(["critical", "high"])
        if wm_today and sector:
            sector_finance = {"banking", "securities", "real_estate"}
            sector_energy = {"energy"}
            relevant = []
            if sector in sector_finance:
                relevant = [w for w in wm_today if w.get("wm_category") == "finance"]
            elif sector in sector_energy:
                relevant = [w for w in wm_today if "oil" in w.get("title","").lower()
                            or "energy" in w.get("title","").lower()
                            or w.get("wm_category") == "finance"]
            else:
                relevant = [w for w in wm_today if w.get("wm_category") in ("vietnam","asia")]

            if relevant:
                wm_threat = max((w.get("threat_level","info") for w in relevant),
                                key=lambda x: ["info","low","medium","high","critical"].index(x))
                bearish_count = sum(1 for w in relevant
                                    if any(word in w.get("title","").lower()
                                           for word in ["war","crash","fall","sanction","recession"]))
                wm_signal = "bearish" if bearish_count > len(relevant) // 2 else "neutral"

        return TickerSignal(
            ticker=ticker,
            company=company,
            score=round(avg_score, 4),
            label=label,
            confidence=round(avg_conf, 2),
            article_count=len(articles),
            top_headlines=[a["title"] for a in articles[:3]],
            wm_threat=wm_threat,
            market_signal=wm_signal,
            sector=sector,
        )

    def _compute_sector_signals(self, ticker_signals: Dict[str, TickerSignal]) -> List[SectorSignal]:
        """Aggregate ticker signals into sector-level signals."""
        from src.utils.sentiment import _score_to_label

        sector_data: Dict[str, List[TickerSignal]] = {}
        for sig in ticker_signals.values():
            if sig.sector:
                sector_data.setdefault(sig.sector, []).append(sig)

        results = []
        for sector, sigs in sector_data.items():
            if not sigs:
                continue
            scores = [s.score for s in sigs]
            avg = sum(scores) / len(scores)
            bull = sum(1 for s in sigs if s.score >= 0.20)
            bear = sum(1 for s in sigs if s.score <= -0.20)
            neu  = len(sigs) - bull - bear
            top = sorted(sigs, key=lambda x: abs(x.score), reverse=True)[:3]

            # WM sector impact
            wm_impact = "neutral"
            if sector in ("energy",) and any(
                "oil" in e.get("title","").lower() or "iran" in e.get("title","").lower()
                for e in self._fetch_wm_intel(["critical","high"])
            ):
                wm_impact = "bullish"  # Iran war → higher oil prices → energy sector bullish

            results.append(SectorSignal(
                sector=sector,
                display_name=SECTOR_DISPLAY.get(sector, sector),
                avg_score=round(avg, 4),
                label=_score_to_label(avg),
                ticker_count=len(sigs),
                bullish=bull, bearish=bear, neutral=neu,
                top_tickers=[s.ticker for s in top],
                wm_impact=wm_impact,
            ))

        return sorted(results, key=lambda x: x.avg_score, reverse=True)

    # ── LLM synthesis ─────────────────────────────────────────────────────────

    def _synthesize(
        self,
        ticker_signals: Dict[str, TickerSignal],
        wm_intel: List[Dict],
        market_score: float,
    ) -> str:
        """Generate Vietnamese market synthesis using Groq."""
        if not self.groq_api_key:
            return ""

        # Build context
        top_vn = sorted(ticker_signals.values(), key=lambda x: abs(x.score), reverse=True)[:5]
        wm_critical = [w for w in wm_intel if w.get("threat_level") == "critical"][:3]

        vn_summary = "\n".join(
            f"- {s.ticker} ({s.company}): {s.label} (score={s.score:+.2f}, "
            f"{s.article_count} bài)"
            for s in top_vn
        )
        global_summary = "\n".join(
            f"- [{w.get('wm_category','')}] {w.get('title','')[:80]}"
            for w in wm_critical
        )
        from src.utils.sentiment import _score_to_label
        market_label = _score_to_label(market_score)

        system = (
            "Bạn là chuyên gia phân tích thị trường chứng khoán Việt Nam. "
            "Viết 2-3 câu tóm tắt ngắn gọn bằng tiếng Việt về tâm lý thị trường hôm nay, "
            "kết hợp dữ liệu VN và bối cảnh toàn cầu. "
            "Không dùng thuật ngữ tài chính phức tạp. Không khuyến nghị đầu tư cụ thể."
        )
        user = (
            f"Tâm lý thị trường VN hôm nay: {market_label} (score={market_score:+.2f})\n\n"
            f"Cổ phiếu nổi bật:\n{vn_summary}\n\n"
            f"Sự kiện toàn cầu quan trọng:\n{global_summary if global_summary else '(không có)'}\n\n"
            f"Tóm tắt 2-3 câu:"
        )

        try:
            resp = requests.post(
                self.GROQ_API_URL,
                headers={"Authorization": f"Bearer {self.groq_api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.GROQ_MODEL, "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ], "temperature": 0.3, "max_tokens": 200},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"  ⚠ Groq synthesis error: {e}")
            return ""

    # ── Main entry point ──────────────────────────────────────────────────────

    def run_morning_brief(
        self,
        watchlist: Optional[List[str]] = None,
    ) -> MorningReport:
        """
        Generate morning briefing report.

        Args:
            watchlist: List of tickers to analyze. Defaults to VN30 core.

        Returns:
            MorningReport with full analysis.
        """
        if watchlist is None:
            watchlist = ["VCB", "HPG", "VIC", "GAS", "VNM",
                         "MWG", "TCB", "VHM", "MSN", "FPT",
                         "SSI", "VPB", "ACB", "REE", "PLX"]

        print(f"[IntelAgent] Generating morning brief for {len(watchlist)} tickers...")

        # Compute ticker signals
        ticker_signals: Dict[str, TickerSignal] = {}
        for t in watchlist:
            sig = self._compute_ticker_signal(t)
            ticker_signals[t] = sig
            print(f"  {sig.emoji} {t:5s} {sig.label:20s} {sig.score:+.3f} ({sig.article_count} articles)")

        # Market-level score
        scores = [s.score for s in ticker_signals.values() if s.article_count > 0]
        market_score = sum(scores) / len(scores) if scores else 0.0
        from src.utils.sentiment import _score_to_label
        market_label = _score_to_label(market_score)

        # Sector signals
        sector_signals = self._compute_sector_signals(ticker_signals)

        # WM global intel
        wm_stats = self._wm_stats()
        critical_count = wm_stats.get("critical", 0)
        high_count = wm_stats.get("high", 0)
        global_risk = "HIGH" if critical_count >= 5 else "MEDIUM" if critical_count >= 2 else "LOW"
        wm_intel = self._fetch_wm_intel(["critical", "high"])

        # Top picks and risk alerts
        sorted_sigs = sorted(ticker_signals.values(), key=lambda x: x.score, reverse=True)
        top_picks   = [s for s in sorted_sigs if s.score >= 0.20 and s.article_count > 0][:5]
        risk_alerts = [s for s in sorted_sigs[::-1] if s.score <= -0.15 and s.article_count > 0][:3]

        # LLM synthesis
        print("  [IntelAgent] Generating LLM synthesis...")
        synthesis = self._synthesize(ticker_signals, wm_intel, market_score)

        report = MorningReport(
            report_date=date.today().isoformat(),
            market_outlook=market_label,
            market_score=round(market_score, 4),
            global_risk=global_risk,
            critical_events=critical_count,
            high_events=high_count,
            ticker_signals=list(ticker_signals.values()),
            sector_signals=sector_signals,
            top_picks=top_picks,
            risk_alerts=risk_alerts,
            global_context=wm_intel[:5],
            synthesis=synthesis,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        print(f"  [IntelAgent] Report ready: {market_label}, risk={global_risk}")
        return report

    def save_report(self, report: MorningReport) -> int:
        """Save report to DB and return report ID."""
        conn = self._db()
        try:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date     TEXT NOT NULL,
                    report_type     TEXT DEFAULT 'morning_brief',
                    market_outlook  TEXT,
                    global_risk     TEXT,
                    market_score    REAL,
                    content_json    TEXT,
                    generated_at    TEXT,
                    sent_at         TIMESTAMP,
                    UNIQUE(report_date, report_type)
                )
            """)
            c.execute("""
                INSERT OR REPLACE INTO reports
                    (report_date, report_type, market_outlook, global_risk,
                     market_score, content_json, generated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                report.report_date, "morning_brief",
                report.market_outlook, report.global_risk,
                report.market_score, report.to_json(),
                report.generated_at,
            ))
            conn.commit()
            report_id = c.lastrowid
            print(f"  [IntelAgent] Report saved (id={report_id})")
            return report_id
        finally:
            conn.close()

    def send_telegram(self, report: MorningReport, bot_token: str, chat_id: str) -> bool:
        """Send report to Telegram channel."""
        text = report.to_telegram_md()
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            resp.raise_for_status()
            print(f"  [IntelAgent] Telegram sent to {chat_id}")
            return True
        except Exception as e:
            print(f"  [IntelAgent] Telegram error: {e}")
            return False

"""
TrendRadar Intelligence Dashboard

Streamlit dashboard for retail investors — shows morning brief, heatmap,
sector analysis, and AI-generated market synthesis.

Run:
    streamlit run trend_news/intelligence_dashboard.py
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, date

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.sector_mapper import SECTOR_TICKERS, SECTOR_DISPLAY, TICKER_SECTOR, all_sectors
from src.core.ticker_mapper import TICKER_ALIASES
from src.utils.sentiment import get_sentiment, _score_to_label

DB_PATH = os.path.join(os.path.dirname(__file__), "output", "trend_news.db")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TrendRadar Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.big-metric { font-size: 2.5rem; font-weight: bold; }
.bullish  { color: #00c853; }
.bearish  { color: #d32f2f; }
.neutral  { color: #9e9e9e; }
.risk-high { color: #d32f2f; font-weight: bold; }
.risk-med  { color: #f57c00; font-weight: bold; }
.risk-low  { color: #00c853; font-weight: bold; }
.card { background: #1e1e2e; border-radius: 8px; padding: 12px; margin: 4px 0; }
</style>
""", unsafe_allow_html=True)


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_latest_report():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT report_date, market_outlook, global_risk, market_score,
                   content_json, generated_at
            FROM reports ORDER BY report_date DESC, rowid DESC LIMIT 1
        """)
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        cols = ["report_date","market_outlook","global_risk","market_score","content_json","generated_at"]
        d = dict(zip(cols, row))
        d["content"] = json.loads(d.pop("content_json", "{}"))
        return d
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_ticker_articles(ticker: str, days: int = 7) -> pd.DataFrame:
    aliases = TICKER_ALIASES.get(ticker, [ticker])
    try:
        conn = sqlite3.connect(DB_PATH)
        conds = " OR ".join(["title LIKE ?" for _ in aliases])
        params = [f"%{a}%" for a in aliases]
        df = pd.read_sql_query(f"""
            SELECT title, source_id, sentiment_score, sentiment_label, crawled_at, url
            FROM news_articles
            WHERE ({conds}) AND crawled_at >= datetime('now', '-{days} days')
            ORDER BY crawled_at DESC LIMIT 50
        """, conn, params=params)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_wm_intel(threat_levels=None, days=1):
    try:
        conn = sqlite3.connect(DB_PATH)
        since = (date.today() - timedelta(days=days)).isoformat()
        if threat_levels:
            placeholders = ",".join("?" * len(threat_levels))
            df = pd.read_sql_query(f"""
                SELECT title, source_name, wm_category, threat_level,
                       geo_relevance, crawl_date, url
                FROM wm_articles
                WHERE crawl_date >= ? AND threat_level IN ({placeholders})
                ORDER BY geo_relevance DESC, threat_level ASC
            """, conn, params=[since] + list(threat_levels))
        else:
            df = pd.read_sql_query("""
                SELECT title, source_name, wm_category, threat_level,
                       geo_relevance, crawl_date, url
                FROM wm_articles
                WHERE crawl_date >= ?
                ORDER BY geo_relevance DESC
            """, conn, params=[since])
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def compute_sector_heatmap(days=1):
    rows = []
    since = (date.today() - timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(DB_PATH)
        for sector, tickers in SECTOR_TICKERS.items():
            for ticker in tickers:
                aliases = TICKER_ALIASES.get(ticker, [ticker])
                conds = " OR ".join(["title LIKE ?" for _ in aliases])
                params = [f"%{a}%" for a in aliases]
                df = pd.read_sql_query(f"""
                    SELECT sentiment_score, title FROM news_articles
                    WHERE ({conds}) AND crawled_at >= ? LIMIT 30
                """, conn, params=params + [since])
                if df.empty:
                    score = 0.0
                    count = 0
                else:
                    valid = df["sentiment_score"].dropna()
                    if valid.empty:
                        score_list = [get_sentiment(t)[0] for t in df["title"].tolist()]
                        score = sum(score_list)/len(score_list) if score_list else 0.0
                    else:
                        score = float(valid.mean())
                    count = len(df)
                rows.append({
                    "sector": SECTOR_DISPLAY.get(sector, sector),
                    "ticker": ticker,
                    "company": TICKER_ALIASES.get(ticker, [ticker])[0],
                    "score": round(score, 3),
                    "label": _score_to_label(score),
                    "articles": count,
                })
        conn.close()
    except Exception as e:
        st.error(f"Heatmap error: {e}")
    return pd.DataFrame(rows)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://via.placeholder.com/200x50/1a1a2e/00c853?text=TrendRadar", use_column_width=True)
    st.markdown("### 🔧 Cài đặt")
    days_back = st.slider("Số ngày phân tích", 1, 7, 1)
    selected_sectors = st.multiselect(
        "Chọn ngành",
        options=all_sectors(),
        default=["banking", "real_estate", "energy"],
        format_func=lambda x: SECTOR_DISPLAY.get(x, x),
    )
    st.markdown("---")
    if st.button("🔄 Làm mới dữ liệu"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.markdown("📌 *Phân tích dữ liệu, không phải khuyến nghị đầu tư.*")


# ── Main content ──────────────────────────────────────────────────────────────

st.title("📊 TrendRadar Intelligence Dashboard")
st.caption(f"Cập nhật: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

# ── Section 1: Morning Brief ──────────────────────────────────────────────────

st.header("🌅 Morning Brief Hôm Nay")
report = load_latest_report()

if report:
    content = report.get("content", {})
    outlook = report.get("market_outlook", "Neutral")
    risk    = report.get("global_risk", "LOW")
    score   = report.get("market_score", 0.0)

    outlook_color = {"Bullish": "bullish", "Bearish": "bearish"}.get(outlook, "neutral")
    risk_color    = {"HIGH": "risk-high", "MEDIUM": "risk-med", "LOW": "risk-low"}.get(risk, "")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Tâm lý thị trường", outlook, delta=f"{score:+.3f}")
    with col2:
        st.metric("Rủi ro toàn cầu", risk,
                  delta=f"{content.get('critical_events',0)} critical events",
                  delta_color="inverse")
    with col3:
        picks = content.get("top_picks", [])
        st.metric("Top picks", len(picks), delta=f"{', '.join(p['ticker'] for p in picks[:3])}")
    with col4:
        st.metric("Ngày báo cáo", report.get("report_date",""), delta=report.get("generated_at","")[-8:])

    # AI synthesis
    synthesis = content.get("synthesis", "")
    if synthesis:
        st.info(f"🤖 **AI Synthesis:** {synthesis}")

    # Top picks + risk alerts
    col_picks, col_risks = st.columns(2)
    with col_picks:
        st.subheader("🎯 Cổ phiếu theo dõi")
        for p in content.get("top_picks", [])[:5]:
            icon = "🟢" if p["score"] > 0 else "🔴" if p["score"] < -0.15 else "⚪"
            st.markdown(f"{icon} **{p['ticker']}** — {p['label']} ({p['score']:+.3f})")

    with col_risks:
        st.subheader("⚠️ Rủi ro cần theo dõi")
        alerts = content.get("risk_alerts", [])
        if alerts:
            for a in alerts[:3]:
                st.markdown(f"🔴 **{a['ticker']}** — {a['label']} ({a['score']:+.3f})")
        else:
            st.success("Không có cảnh báo đặc biệt")

    # Global context
    with st.expander("🌍 Bối cảnh toàn cầu (WM Intel)"):
        for e in content.get("global_context", [])[:5]:
            icon = "🔴" if e.get("threat_level") == "critical" else "🟠"
            st.markdown(f"{icon} [{e.get('wm_category','')}] {e.get('title','')}")
else:
    st.warning("⚠️ Chưa có báo cáo. Chạy: `python morning_brief.py --skip-fetch` để tạo báo cáo.")
    if st.button("🚀 Tạo báo cáo ngay"):
        with st.spinner("Đang tạo báo cáo..."):
            from src.core.intelligence_agent import IntelligenceAgent
            agent = IntelligenceAgent(db_path=DB_PATH,
                                      groq_api_key=os.environ.get("GROQ_API_KEY",""))
            r = agent.run_morning_brief()
            agent.save_report(r)
            st.cache_data.clear()
            st.rerun()

st.divider()

# ── Section 2: Market Heatmap ─────────────────────────────────────────────────

st.header("🗺️ Market Heatmap")

with st.spinner("Loading heatmap..."):
    heatmap_df = compute_sector_heatmap(days=days_back)

if not heatmap_df.empty:
    # Filter selected sectors
    if selected_sectors:
        sector_display_filter = [SECTOR_DISPLAY.get(s, s) for s in selected_sectors]
        filtered_df = heatmap_df[heatmap_df["sector"].isin(sector_display_filter)]
    else:
        filtered_df = heatmap_df

    if not filtered_df.empty:
        fig = px.treemap(
            filtered_df,
            path=["sector", "ticker"],
            values="articles",
            color="score",
            color_continuous_scale=["#d32f2f","#f57c00","#9e9e9e","#43a047","#00c853"],
            color_continuous_midpoint=0,
            hover_data={"company": True, "score": ":.3f", "label": True, "articles": True},
            title=f"Tâm lý theo ngành & cổ phiếu ({days_back} ngày qua)",
        )
        fig.update_layout(height=500, margin=dict(t=40,b=0,l=0,r=0))
        st.plotly_chart(fig, use_container_width=True)

        # Sector bar chart
        sector_agg = filtered_df.groupby("sector")["score"].mean().reset_index()
        sector_agg["color"] = sector_agg["score"].apply(
            lambda s: "#00c853" if s > 0.1 else "#d32f2f" if s < -0.1 else "#9e9e9e"
        )
        fig2 = go.Figure(go.Bar(
            x=sector_agg["sector"], y=sector_agg["score"],
            marker_color=sector_agg["color"],
            text=sector_agg["score"].apply(lambda x: f"{x:+.3f}"),
            textposition="outside",
        ))
        fig2.update_layout(title="Điểm tâm lý trung bình theo ngành",
                           yaxis_title="Sentiment Score", height=350,
                           plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                           font_color="white")
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Section 3: Global Intel ────────────────────────────────────────────────────

st.header("🌍 Global Intel (WorldMonitor)")
col_intel1, col_intel2 = st.columns([2, 1])

with col_intel1:
    wm_df = load_wm_intel(threat_levels=["critical","high"], days=days_back)
    if not wm_df.empty:
        st.subheader(f"⚠️ Critical & High Events ({len(wm_df)})")
        for _, row in wm_df.iterrows():
            icon = "🔴" if row["threat_level"] == "critical" else "🟠"
            geo  = f"🇻🇳 {row['geo_relevance']:.0%}" if row["geo_relevance"] > 0.2 else ""
            st.markdown(f"{icon} **[{row['wm_category']}]** {row['title'][:80]} {geo}")
    else:
        st.info("Không có sự kiện critical/high hôm nay")

with col_intel2:
    all_wm = load_wm_intel(days=days_back)
    if not all_wm.empty:
        threat_counts = all_wm["threat_level"].value_counts()
        colors = {"critical": "#d32f2f","high": "#f57c00","medium": "#ffd54f",
                  "low": "#81c784","info": "#90a4ae"}
        fig3 = go.Figure(go.Pie(
            labels=threat_counts.index,
            values=threat_counts.values,
            marker_colors=[colors.get(l,"#9e9e9e") for l in threat_counts.index],
            hole=0.4,
        ))
        fig3.update_layout(title="Phân bổ mức độ rủi ro", height=300,
                           paper_bgcolor="#0e1117", font_color="white",
                           showlegend=True, margin=dict(t=40,b=0,l=0,r=0))
        st.plotly_chart(fig3, use_container_width=True)

st.divider()

# ── Section 4: Ticker deep-dive ────────────────────────────────────────────────

st.header("🔍 Phân tích cổ phiếu")
ticker_input = st.text_input("Nhập mã cổ phiếu (VD: VCB, HPG, VIC)", value="VCB").upper()

if ticker_input and ticker_input in TICKER_ALIASES:
    company = TICKER_ALIASES[ticker_input][0]
    sector  = TICKER_SECTOR.get(ticker_input, "N/A")
    st.subheader(f"{ticker_input} — {company} ({SECTOR_DISPLAY.get(sector, sector)})")

    art_df = load_ticker_articles(ticker_input, days=days_back)
    if not art_df.empty:
        # Compute scores
        scores = []
        for _, row in art_df.iterrows():
            s = row.get("sentiment_score")
            if s is not None and not pd.isna(s):
                scores.append(float(s))
            else:
                sc, _ = get_sentiment(row["title"])
                scores.append(sc)

        avg_score = sum(scores)/len(scores)
        label = _score_to_label(avg_score)
        bull  = sum(1 for s in scores if s >= 0.20)
        bear  = sum(1 for s in scores if s <= -0.20)
        neu   = len(scores) - bull - bear

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Sentiment", label, delta=f"{avg_score:+.3f}")
        m2.metric("Số bài viết", len(art_df))
        m3.metric("Tích cực", bull)
        m4.metric("Tiêu cực", bear)

        # Timeline chart
        art_df["score_val"] = scores
        art_df["crawled_at"] = pd.to_datetime(art_df["crawled_at"])
        art_df = art_df.sort_values("crawled_at")

        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(
            x=art_df["crawled_at"], y=art_df["score_val"],
            mode="markers+lines", name="Sentiment",
            marker=dict(
                color=art_df["score_val"].apply(
                    lambda s: "#00c853" if s > 0.15 else "#d32f2f" if s < -0.15 else "#9e9e9e"
                ),
                size=8,
            ),
            line=dict(color="#5e81f4", width=1),
        ))
        fig4.add_hline(y=0, line_dash="dot", line_color="#555")
        fig4.update_layout(
            title=f"{ticker_input} Sentiment Timeline",
            yaxis_title="Score", height=300,
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117", font_color="white",
        )
        st.plotly_chart(fig4, use_container_width=True)

        # Headlines table
        with st.expander(f"📰 Tin tức ({len(art_df)} bài)"):
            display_df = art_df[["crawled_at","title","source_id","score_val"]].copy()
            display_df.columns = ["Thời gian","Tiêu đề","Nguồn","Score"]
            display_df["Score"] = display_df["Score"].apply(lambda x: f"{x:+.3f}")
            st.dataframe(display_df, use_container_width=True, height=300)
    else:
        st.info(f"Không tìm thấy bài viết về {ticker_input} trong {days_back} ngày qua")
elif ticker_input and ticker_input not in TICKER_ALIASES:
    st.warning(f"Không tìm thấy ticker '{ticker_input}' trong danh sách")

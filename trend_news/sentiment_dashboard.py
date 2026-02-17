"""
Sentiment Learning Dashboard - Streamlit UI

Giao diện quản lý và cải thiện sentiment analysis system
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force reload modules to pick up code changes
import importlib
from src.core import sentiment_learning
from src.core import keyword_extractor
from src.core import labeling_pipeline
from src.utils import sentiment

importlib.reload(sentiment_learning)
importlib.reload(keyword_extractor)
importlib.reload(labeling_pipeline)
importlib.reload(sentiment)

from src.core.sentiment_learning import SentimentLearningManager, DynamicLexiconManager
from src.core.keyword_extractor import KeywordExtractor
from src.core.labeling_pipeline import LabelingPipeline
from src.utils.sentiment import get_sentiment, _VI_POSITIVE, _VI_NEGATIVE, refresh_auto_learned_cache

# Page config
st.set_page_config(
    page_title="Sentiment Learning Dashboard",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .positive-keyword {
        background-color: #d4edda;
        padding: 0.3rem 0.6rem;
        border-radius: 0.3rem;
        margin: 0.2rem;
        display: inline-block;
    }
    .negative-keyword {
        background-color: #f8d7da;
        padding: 0.3rem 0.6rem;
        border-radius: 0.3rem;
        margin: 0.2rem;
        display: inline-block;
    }
</style>
""", unsafe_allow_html=True)

# Initialize managers
# Initialize managers (force reload on each run due to importlib.reload above)
# Using suppress_st_warning to avoid hash issues with reloaded modules
@st.cache_resource(hash_funcs={SentimentLearningManager: lambda x: None, 
                                DynamicLexiconManager: lambda x: None,
                                KeywordExtractor: lambda x: None,
                                LabelingPipeline: lambda x: None})
def get_managers():
    # Use default path (output/trend_news.db) - will be auto-detected
    learning_manager = SentimentLearningManager()
    lexicon_manager = DynamicLexiconManager(learning_manager)
    keyword_extractor = KeywordExtractor()
    labeling_pipeline_obj = LabelingPipeline()
    return learning_manager, lexicon_manager, keyword_extractor, labeling_pipeline_obj

learning_mgr, lexicon_mgr, extractor, labeling_pipeline = get_managers()

# Sidebar navigation
st.sidebar.markdown("# 🎯 Sentiment Learning")
page = st.sidebar.radio(
    "Navigation",
    ["📊 Dashboard", "🔤 Keyword Management", "📈 Analytics", "🧪 Test Sentiment", "📋 Daily Labeling Queue"]
)

# ============================================================================
# PAGE 1: DASHBOARD
# ============================================================================
if page == "📊 Dashboard":
    st.markdown('<div class="main-header">📊 Sentiment Learning Dashboard</div>', unsafe_allow_html=True)
    
    # Stats overview
    stats = learning_mgr.get_feedback_stats(days=7)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Feedback (7d)", stats['total_feedback'])
    with col2:
        st.metric("Accuracy Rate", f"{stats['accuracy_rate']}%")
    with col3:
        st.metric("Avg Error", stats['avg_error'])
    with col4:
        learned_kw = learning_mgr.get_approved_keywords()
        total_learned = len(learned_kw['positive']) + len(learned_kw['negative'])
        st.metric("Learned Keywords", total_learned)
    
    st.markdown("---")
    
    # Lexicon overview
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🟢 Positive Keywords")
        combined = lexicon_mgr.get_combined_lexicon()
        pos_df = pd.DataFrame([
            {'Keyword': k, 'Weight': v, 'Source': 'Learned' if k not in _VI_POSITIVE else 'Static'}
            for k, v in sorted(combined['positive'].items(), key=lambda x: -x[1])[:20]
        ])
        st.dataframe(pos_df, use_container_width=True, height=400)
    
    with col2:
        st.subheader("🔴 Negative Keywords")
        neg_df = pd.DataFrame([
            {'Keyword': k, 'Weight': v, 'Source': 'Learned' if k not in _VI_NEGATIVE else 'Static'}
            for k, v in sorted(combined['negative'].items(), key=lambda x: -x[1])[:20]
        ])
        st.dataframe(neg_df, use_container_width=True, height=400)
    
    st.markdown("---")
    
    # Quick suggestions
    st.subheader("💡 Improvement Suggestions")
    
    with st.spinner("Analyzing data..."):
        suggestions = extractor.suggest_improvements()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**Positive Candidates:** {suggestions['summary']['positive_candidates']}")
        if suggestions['pattern_based']['positive']:
            top_pos = suggestions['pattern_based']['positive'][:5]
            for item in top_pos:
                st.markdown(f"• `{item['keyword']}` (freq: {item['frequency']}, weight: {item['suggested_weight']:.2f})")
    
    with col2:
        st.write(f"**Negative Candidates:** {suggestions['summary']['negative_candidates']}")
        if suggestions['pattern_based']['negative']:
            top_neg = suggestions['pattern_based']['negative'][:5]
            for item in top_neg:
                st.markdown(f"• `{item['keyword']}` (freq: {item['frequency']}, weight: {item['suggested_weight']:.2f})")

# ============================================================================
# PAGE 2: KEYWORD MANAGEMENT
# ============================================================================
elif page == "🔤 Keyword Management":
    st.markdown('<div class="main-header">🔤 Keyword Management</div>', unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["Suggested Keywords", "Manual Add", "Current Lexicon"])
    
    with tab1:
        st.subheader("Keywords Extracted from Feedback")
        
        # Sub-tabs cho Extract và Review
        extract_tab, review_tab = st.tabs(["🔍 Extract New Patterns", "📋 Review Suggestions"])
        
        with extract_tab:
            col1, col2 = st.columns([1, 3])
            with col1:
                min_freq = st.slider("Min Frequency", 1, 10, 3, key="extract_freq")
            with col2:
                days = st.slider("Look back (days)", 7, 90, 30, key="extract_days")
            
            if st.button("🔍 Analyze & Extract Keywords", type="primary"):
                with st.spinner("Extracting keywords from feedback patterns..."):
                    patterns = extractor.analyze_sentiment_patterns(days=days, min_frequency=min_freq)
                    
                    # Lưu patterns vào session state để hiển thị
                    st.session_state['extracted_patterns'] = patterns
                    st.success(f"Found {len(patterns['positive'])} positive and {len(patterns['negative'])} negative candidates!")
                    st.rerun()
            
            # Hiển thị kết quả extract nếu có
            if 'extracted_patterns' in st.session_state:
                patterns = st.session_state['extracted_patterns']
                
                st.markdown("### 🟢 Positive Keyword Candidates")
                for item in patterns['positive'][:20]:
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    with col1:
                        st.markdown(f"**{item['keyword']}**")
                        if item['examples']:
                            with st.expander("Examples"):
                                for ex in item['examples']:
                                    st.text(ex)
                    with col2:
                        st.text(f"Freq: {item['frequency']}")
                    with col3:
                        st.text(f"Weight: {item['suggested_weight']:.2f}")
                    with col4:
                        if st.button("✅ Approve", key=f"extract_pos_{item['keyword']}"):
                            learning_mgr.approve_keyword(
                                item['keyword'], 
                                'positive', 
                                item['suggested_weight']
                            )
                            st.success("Approved!")
                            lexicon_mgr.refresh_cache()
                            st.rerun()
                
                st.markdown("---")
                st.markdown("### 🔴 Negative Keyword Candidates")
                for item in patterns['negative'][:20]:
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    with col1:
                        st.markdown(f"**{item['keyword']}**")
                        if item['examples']:
                            with st.expander("Examples"):
                                for ex in item['examples']:
                                    st.text(ex)
                    with col2:
                        st.text(f"Freq: {item['frequency']}")
                    with col3:
                        st.text(f"Weight: {item['suggested_weight']:.2f}")
                    with col4:
                        if st.button("✅ Approve", key=f"extract_neg_{item['keyword']}"):
                            learning_mgr.approve_keyword(
                                item['keyword'],
                                'negative',
                                item['suggested_weight']
                            )
                            st.success("Approved!")
                            lexicon_mgr.refresh_cache()
                            st.rerun()
        
        with review_tab:
            st.markdown("### 📋 Raw Suggestions")
            st.caption("Review và remove các keyword suggestions được extract từ feedback.")
            
            # Stats
            total_pending = learning_mgr.get_pending_suggestions_count()
            
            col_filter, col_stats = st.columns([2, 3])
            with col_filter:
                sentiment_filter = st.selectbox(
                    "Filter",
                    ["All", "Positive", "Negative"]
                )
            with col_stats:
                st.metric("Total Suggestions", total_pending)
            
            if total_pending == 0:
                st.info("🎉 No suggestions to review!")
            else:
                # Pagination
                items_per_page = st.selectbox("Items per page", [10, 20, 50], index=1)
                total_pages = max(1, (total_pending + items_per_page - 1) // items_per_page)
                
                col_prev, col_page, col_next = st.columns([1, 3, 1])
                
                if 'review_page' not in st.session_state:
                    st.session_state['review_page'] = 1
                
                with col_prev:
                    if st.button("◀ Previous", disabled=st.session_state['review_page'] <= 1):
                        st.session_state['review_page'] -= 1
                        st.rerun()
                
                with col_page:
                    page_number = st.number_input(
                        "Page", min_value=1, max_value=total_pages,
                        value=st.session_state['review_page']
                    )
                    st.session_state['review_page'] = page_number
                    st.caption(f"Page {page_number} of {total_pages}")
                
                with col_next:
                    if st.button("Next ▶", disabled=st.session_state['review_page'] >= total_pages):
                        st.session_state['review_page'] += 1
                        st.rerun()
                
                # Fetch data
                offset = (st.session_state['review_page'] - 1) * items_per_page
                db_filter = {"Positive": "positive", "Negative": "negative"}.get(sentiment_filter)
                
                suggestions = learning_mgr.get_pending_suggestions_paginated(
                    offset=offset, limit=items_per_page, sentiment_filter=db_filter
                )
                
                if not suggestions:
                    st.info("No suggestions on this page.")
                else:
                    # Display as simple list
                    for item in suggestions:
                        emoji = "🟢" if item['sentiment_type'] == 'positive' else "🔴"
                        with st.container():
                            col1, col2, col3 = st.columns([4, 1, 1])
                            
                            with col1:
                                st.markdown(f"**{emoji} {item['keyword']}**")
                                if item['examples']:
                                    with st.expander(f"{len(item['examples'])} examples"):
                                        for ex in item['examples'][:3]:
                                            st.text(ex)
                            
                            with col2:
                                st.caption(f"Freq: {item['frequency']}")
                            
                            with col3:
                                if st.button("🗑️ Remove", key=f"rm_{item['id']}"):
                                    learning_mgr.reject_keyword(item['id'])
                                    st.rerun()
                            
                            st.divider()
    
    with tab2:
        st.subheader("Manually Add Keyword")
        
        with st.form("add_keyword_form"):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                keyword = st.text_input("Keyword*")
            with col2:
                sentiment_type = st.selectbox("Type", ["positive", "negative"])
            with col3:
                weight = st.slider("Weight", 0.1, 1.0, 0.5, 0.1)
            
            if st.form_submit_button("Add Keyword", type="primary"):
                if keyword:
                    success = learning_mgr.approve_keyword(keyword, sentiment_type, weight)
                    if success:
                        st.success(f"✅ Added '{keyword}' as {sentiment_type} with weight {weight}")
                        lexicon_mgr.refresh_cache()
                    else:
                        st.error("Failed to add keyword")
    
    with tab3:
        st.subheader("Current Lexicon (Static + Learned)")
        
        combined = lexicon_mgr.get_combined_lexicon()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🟢 Positive")
            pos_df = pd.DataFrame([
                {
                    'Keyword': k, 
                    'Weight': v, 
                    'Source': 'Learned' if k not in _VI_POSITIVE else 'Static'
                }
                for k, v in sorted(combined['positive'].items(), key=lambda x: -x[1])
            ])
            st.dataframe(pos_df, use_container_width=True, height=600)
        
        with col2:
            st.markdown("### 🔴 Negative")
            neg_df = pd.DataFrame([
                {
                    'Keyword': k,
                    'Weight': v,
                    'Source': 'Learned' if k not in _VI_NEGATIVE else 'Static'
                }
                for k, v in sorted(combined['negative'].items(), key=lambda x: -x[1])
            ])
            st.dataframe(neg_df, use_container_width=True, height=600)

# ============================================================================
# PAGE 4: ANALYTICS
# ============================================================================
elif page == "📈 Analytics":
    st.markdown('<div class="main-header">📈 Performance Analytics</div>', unsafe_allow_html=True)
    
    # Accuracy over time
    st.subheader("Accuracy Trends")
    
    periods = [7, 14, 30, 60]
    stats_data = []
    
    for period in periods:
        stats = learning_mgr.get_feedback_stats(days=period)
        stats_data.append({
            'Period': f'{period}d',
            'Accuracy': stats['accuracy_rate'],
            'Total Feedback': stats['total_feedback'],
            'Avg Error': stats['avg_error']
        })
    
    df_stats = pd.DataFrame(stats_data)
    
    col1, col2 = st.columns(2)
    
    with col1:
        fig = px.bar(df_stats, x='Period', y='Accuracy', 
                     title='Accuracy Rate by Period',
                     color='Accuracy',
                     color_continuous_scale='RdYlGn')
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = px.line(df_stats, x='Period', y='Total Feedback',
                      title='Feedback Volume',
                      markers=True)
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Misclassification analysis
    st.subheader("Misclassification Analysis")
    
    misclassified = extractor.analyze_misclassified_news()
    
    if misclassified:
        df_misc = pd.DataFrame(misclassified)
        
        st.write(f"Found {len(misclassified)} cases with error > 0.4")
        
        for idx, item in enumerate(misclassified[:10]):
            with st.expander(f"#{idx+1} | Error: {item['error']} | {item['title'][:80]}..."):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Predicted:**")
                    st.write(f"Score: {item['predicted']['score']:.2f}")
                    st.write(f"Label: {item['predicted']['label']}")
                with col2:
                    st.markdown("**Actual:**")
                    st.write(f"Score: {item['actual']['score']:.2f}")
                    st.write(f"Label: {item['actual']['label']}")
                
                st.markdown("**Potential Keywords:**")
                st.write(", ".join(item['potential_keywords']))
    else:
        st.info("No significant misclassifications found!")

# ============================================================================
# PAGE 5: TEST SENTIMENT
# ============================================================================
elif page == "🧪 Test Sentiment":
    st.markdown('<div class="main-header">🧪 Test Sentiment Analysis</div>', unsafe_allow_html=True)
    
    st.write("Test how the current model performs on custom text")
    
    test_text = st.text_area(
        "Enter text to analyze:",
        placeholder="Giá vàng tăng mạnh...",
        height=100
    )
    
    if st.button("Analyze", type="primary"):
        if test_text:
            score, label = get_sentiment(test_text)
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("Sentiment Score", f"{score:.3f}")
            with col2:
                st.metric("Sentiment Label", label)
            
            # Visual representation
            color_map = {
                "Bearish": "red",
                "Somewhat-Bearish": "orange",
                "Neutral": "gray",
                "Somewhat-Bullish": "lightgreen",
                "Bullish": "green"
            }
            
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=score,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Sentiment Score"},
                gauge={
                    'axis': {'range': [-1, 1]},
                    'bar': {'color': color_map.get(label, 'gray')},
                    'steps': [
                        {'range': [-1, -0.35], 'color': "lightcoral"},
                        {'range': [-0.35, -0.15], 'color': "lightyellow"},
                        {'range': [-0.15, 0.15], 'color': "lightgray"},
                        {'range': [0.15, 0.35], 'color': "lightyellow"},
                        {'range': [0.35, 1], 'color': "lightgreen"}
                    ],
                    'threshold': {
                        'line': {'color': "red", 'width': 4},
                        'thickness': 0.75,
                        'value': score
                    }
                }
            ))
            
            st.plotly_chart(fig, use_container_width=True)
            
            # Add feedback button
            st.markdown("---")
            st.subheader("Is this correct?")
            
            col1, col2, col3 = st.columns([1, 1, 2])
            
            with col1:
                if st.button("✅ Correct"):
                    learning_mgr.add_feedback(
                        news_title=test_text,
                        predicted_score=score,
                        predicted_label=label,
                        user_score=score,
                        user_label=label
                    )
                    st.success("Thanks for the feedback!")
            
            with col2:
                if st.button("❌ Incorrect"):
                    st.session_state['show_feedback_form'] = True
            
            if st.session_state.get('show_feedback_form', False):
                st.markdown("### Provide Correct Label")
                correct_label = st.select_slider(
                    "What should it be?",
                    options=["Bearish", "Somewhat-Bearish", "Neutral", "Somewhat-Bullish", "Bullish"]
                )
                
                label_to_score = {
                    "Bearish": -0.6,
                    "Somewhat-Bearish": -0.25,
                    "Neutral": 0.0,
                    "Somewhat-Bullish": 0.25,
                    "Bullish": 0.6
                }
                
                if st.button("Submit Correction"):
                    learning_mgr.add_feedback(
                        news_title=test_text,
                        predicted_score=score,
                        predicted_label=label,
                        user_score=label_to_score[correct_label],
                        user_label=correct_label
                    )
                    st.success("Feedback recorded! This will help improve the model.")
                    st.session_state['show_feedback_form'] = False

# ============================================================================
# PAGE 6: DAILY LABELING QUEUE
# ============================================================================
elif page == "📋 Daily Labeling Queue":
    st.markdown('<p class="main-header">📋 Daily Labeling Queue</p>', unsafe_allow_html=True)
    st.markdown("Surface the most uncertain articles for admin review to close the learning loop.")

    # Suggest latest available date — query DB directly so cache misses don't break this
    from datetime import date as _date
    import sqlite3 as _sqlite3
    _db_path = labeling_pipeline.db_path
    try:
        _conn = _sqlite3.connect(_db_path)
        _row = _conn.execute("SELECT MAX(crawl_date) FROM news_articles").fetchone()
        latest_date = _row[0] if _row and _row[0] else None
        _conn.close()
    except Exception:
        latest_date = None
    default_date = datetime.strptime(latest_date, "%Y-%m-%d").date() if latest_date else _date.today()

    col_date, col_btn, col_limit = st.columns([2, 1, 1])
    with col_date:
        queue_date = st.date_input("Queue Date", value=default_date).strftime("%Y-%m-%d")
        if latest_date and queue_date != latest_date:
            st.caption(f"Latest crawled date: **{latest_date}**")
    with col_limit:
        queue_limit = st.number_input("Max items", min_value=5, max_value=100, value=25, step=5)
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🔄 Build / Refresh Queue"):
            try:
                with st.spinner("Scoring articles…"):
                    result = labeling_pipeline.build_daily_queue(queue_date, limit=int(queue_limit))
                total = result["total_candidates"]
                inserted = result["inserted"]
                already = result["already_queued"]
                if total == 0:
                    st.warning(
                        f"No articles found for **{queue_date}** in the database.  \n"
                        f"Latest crawled date is **{latest_date}**. Please select that date."
                    )
                elif inserted > 0:
                    st.success(f"Added **{inserted}** new items to the queue (from {total} articles).")
                    st.rerun()
                else:
                    st.info(f"Queue already up-to-date — {already} items already queued from {total} articles.")
            except Exception as e:
                st.error(f"Error building queue: {e}")

    # Stats row
    stats = labeling_pipeline.get_queue_stats(queue_date)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total", stats["total"])
    m2.metric("Pending", stats["pending"])
    m3.metric("Labeled", stats["labeled"])
    m4.metric("Skipped", stats["skipped"])
    avg_unc = stats["avg_uncertainty"] or 0.0
    m5.metric("Avg Uncertainty", f"{avg_unc:.2f}")

    st.markdown("---")

    # Pending items
    pending = labeling_pipeline.get_queue(queue_date, status_filter="pending")
    if not pending:
        st.info("No pending items. Click 'Build / Refresh Queue' to populate.")
    else:
        st.markdown(f"### Pending Items ({len(pending)})")
        label_to_score = {
            "Bearish": -0.6,
            "Somewhat-Bearish": -0.25,
            "Neutral": 0.0,
            "Somewhat-Bullish": 0.25,
            "Bullish": 0.6,
        }
        for item in pending:
            expander_title = (
                f"[#{item['priority_rank']}] {item['news_title'][:80]}{'…' if len(item['news_title']) > 80 else ''}"
                f"  —  uncertainty: **{item['uncertainty_score']:.2f}**"
            )
            with st.expander(expander_title):
                sig_col1, sig_col2, sig_col3 = st.columns(3)
                sig_col1.metric("Signal Conflict", f"{item['signal_conflict']:.2f}")
                sig_col2.metric("Magnitude Unc.", f"{item['magnitude_uncertainty']:.2f}")
                sig_col3.metric("Match Sparsity", f"{item['match_sparsity']:.2f}")

                pred_col1, pred_col2 = st.columns(2)
                pred_col1.info(f"**System label:** {item['final_label']}  ({item['final_score']:.3f})")
                if item.get("news_url"):
                    pred_col2.markdown(f"[Open article]({item['news_url']})")

                with st.form(key=f"label_form_{item['id']}"):
                    chosen_label = st.select_slider(
                        "Correct label",
                        options=["Bearish", "Somewhat-Bearish", "Neutral", "Somewhat-Bullish", "Bullish"],
                        value="Neutral",
                    )
                    comment = st.text_input("Comment (optional)", key=f"comment_{item['id']}")
                    submit_col, skip_col = st.columns(2)
                    with submit_col:
                        submitted = st.form_submit_button("✅ Submit Label")
                    with skip_col:
                        skipped = st.form_submit_button("⏭ Skip")

                if submitted:
                    labeling_pipeline.submit_label(
                        queue_id=item["id"],
                        user_score=label_to_score[chosen_label],
                        user_label=chosen_label,
                        comment=comment or None,
                    )
                    st.success(f"Label '{chosen_label}' recorded and fed into learning loop.")
                    st.rerun()
                elif skipped:
                    labeling_pipeline.skip_item(item["id"])
                    st.rerun()

    # Labeled items
    labeled = labeling_pipeline.get_queue(queue_date, status_filter="labeled")
    if labeled:
        with st.expander(f"✅ Already Labeled ({len(labeled)})"):
            df_labeled = pd.DataFrame(labeled)[
                ["priority_rank", "news_title", "final_label", "admin_label", "admin_score", "uncertainty_score", "labeled_at"]
            ]
            df_labeled.columns = ["Rank", "Title", "System Label", "Admin Label", "Admin Score", "Uncertainty", "Labeled At"]
            st.dataframe(df_labeled, use_container_width=True)

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Statistics")
stats = learning_mgr.get_feedback_stats(days=30)
st.sidebar.metric("30-day Accuracy", f"{stats['accuracy_rate']}%")
st.sidebar.metric("Total Feedback", stats['total_feedback'])

learned = learning_mgr.get_approved_keywords()
total_learned = len(learned['positive']) + len(learned['negative'])
st.sidebar.metric("Learned Keywords", total_learned)

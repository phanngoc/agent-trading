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

from src.core.sentiment_learning import SentimentLearningManager, DynamicLexiconManager
from src.core.keyword_extractor import KeywordExtractor
from src.utils.sentiment import get_sentiment, _VI_POSITIVE, _VI_NEGATIVE

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
@st.cache_resource
def get_managers():
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "output", "trend_news.db")
    learning_manager = SentimentLearningManager(db_path)
    lexicon_manager = DynamicLexiconManager(learning_manager)
    keyword_extractor = KeywordExtractor(db_path)
    return learning_manager, lexicon_manager, keyword_extractor

learning_mgr, lexicon_mgr, extractor = get_managers()

# Sidebar navigation
st.sidebar.markdown("# 🎯 Sentiment Learning")
page = st.sidebar.radio(
    "Navigation",
    ["📊 Dashboard", "💬 Feedback Management", "🔤 Keyword Management", "📈 Analytics", "🧪 Test Sentiment"]
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
# PAGE 2: FEEDBACK MANAGEMENT
# ============================================================================
elif page == "💬 Feedback Management":
    st.markdown('<div class="main-header">💬 Feedback Management</div>', unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["Add New Feedback", "View Feedback History"])
    
    with tab1:
        st.subheader("Add Sentiment Feedback")
        
        with st.form("feedback_form"):
            news_title = st.text_input("News Title*", placeholder="Enter news title...")
            news_url = st.text_input("URL (optional)", placeholder="https://...")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.write("**System Prediction:**")
                if news_title:
                    pred_score, pred_label = get_sentiment(news_title)
                    st.info(f"Score: {pred_score:.2f} | Label: {pred_label}")
                else:
                    pred_score, pred_label = 0.0, "Neutral"
                    st.info("Enter title to see prediction")
            
            with col2:
                st.write("**Your Assessment:**")
                user_label = st.select_slider(
                    "Sentiment",
                    options=["Bearish", "Somewhat-Bearish", "Neutral", "Somewhat-Bullish", "Bullish"],
                    value="Neutral"
                )
                
                # Map label to score
                label_to_score = {
                    "Bearish": -0.6,
                    "Somewhat-Bearish": -0.25,
                    "Neutral": 0.0,
                    "Somewhat-Bullish": 0.25,
                    "Bullish": 0.6
                }
                user_score = label_to_score[user_label]
            
            user_comment = st.text_area("Comment (optional)", placeholder="Why do you think this is the correct sentiment?")
            
            submitted = st.form_submit_button("Submit Feedback", type="primary")
            
            if submitted and news_title:
                feedback_id = learning_mgr.add_feedback(
                    news_title=news_title,
                    predicted_score=pred_score,
                    predicted_label=pred_label,
                    user_score=user_score,
                    user_label=user_label,
                    news_url=news_url if news_url else None,
                    comment=user_comment if user_comment else None
                )
                st.success(f"✅ Feedback saved! ID: {feedback_id}")
                
                # Show difference
                diff = abs(user_score - pred_score)
                if diff > 0.3:
                    st.warning(f"⚠️ Large discrepancy detected ({diff:.2f}). Keywords will be auto-extracted for review.")
    
    with tab2:
        st.subheader("Recent Feedback")
        
        # Get recent feedback from DB
        import sqlite3
        conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "..", "output", "trend_news.db"))
        df = pd.read_sql_query("""
            SELECT 
                news_title,
                predicted_label,
                user_label,
                ABS(user_score - predicted_score) as error,
                created_at
            FROM sentiment_feedback
            ORDER BY created_at DESC
            LIMIT 50
        """, conn)
        conn.close()
        
        if not df.empty:
            df['created_at'] = pd.to_datetime(df['created_at'])
            st.dataframe(df, use_container_width=True, height=400)
        else:
            st.info("No feedback data yet. Add some feedback to see history!")

# ============================================================================
# PAGE 3: KEYWORD MANAGEMENT
# ============================================================================
elif page == "🔤 Keyword Management":
    st.markdown('<div class="main-header">🔤 Keyword Management</div>', unsafe_allow_html=True)
    
    tab1, tab2, tab3 = st.tabs(["Suggested Keywords", "Manual Add", "Current Lexicon"])
    
    with tab1:
        st.subheader("Keywords Extracted from Feedback")
        
        col1, col2 = st.columns([1, 3])
        with col1:
            min_freq = st.slider("Min Frequency", 1, 10, 3)
        with col2:
            days = st.slider("Look back (days)", 7, 90, 30)
        
        if st.button("🔍 Analyze & Extract Keywords", type="primary"):
            with st.spinner("Extracting keywords..."):
                patterns = extractor.analyze_sentiment_patterns(days=days, min_frequency=min_freq)
            
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
                    if st.button("✅ Approve", key=f"pos_{item['keyword']}"):
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
                    if st.button("✅ Approve", key=f"neg_{item['keyword']}"):
                        learning_mgr.approve_keyword(
                            item['keyword'],
                            'negative',
                            item['suggested_weight']
                        )
                        st.success("Approved!")
                        lexicon_mgr.refresh_cache()
                        st.rerun()
    
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

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("### 📚 Statistics")
stats = learning_mgr.get_feedback_stats(days=30)
st.sidebar.metric("30-day Accuracy", f"{stats['accuracy_rate']}%")
st.sidebar.metric("Total Feedback", stats['total_feedback'])

learned = learning_mgr.get_approved_keywords()
total_learned = len(learned['positive']) + len(learned['negative'])
st.sidebar.metric("Learned Keywords", total_learned)

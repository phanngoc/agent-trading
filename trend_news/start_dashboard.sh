#!/bin/bash

# Sentiment Learning Dashboard - Launch Script

echo "🎯 Starting Sentiment Learning Dashboard..."
echo ""

# Check if in correct directory
if [ ! -f "sentiment_dashboard.py" ]; then
    echo "❌ Error: sentiment_dashboard.py not found"
    echo "Please run this script from the trend_news directory"
    exit 1
fi

# Check if streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "📦 Installing Streamlit..."
    pip install streamlit plotly pandas
fi

# Initialize database tables
echo "🗄️  Initializing learning database tables..."
python3 -c "
from src.core.sentiment_learning import SentimentLearningManager

# Use default path (output/trend_news.db)
manager = SentimentLearningManager()
print(f'✅ Database initialized at: {manager.db_path}')
"

echo ""
echo "🚀 Launching Dashboard..."
echo "   URL: http://localhost:8501"
echo ""
echo "Press Ctrl+C to stop"
echo ""

streamlit run sentiment_dashboard.py --server.port 8501

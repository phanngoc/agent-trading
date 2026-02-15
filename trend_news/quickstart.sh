#!/bin/bash

# Quick Start - Sentiment Learning System
# Run this to see a complete demo

echo "🚀 Sentiment Learning System - Quick Start"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required"
    exit 1
fi

echo "📦 Installing dependencies..."
pip install -q streamlit plotly pandas 2>/dev/null || pip3 install -q streamlit plotly pandas

echo ""
echo "🎯 Running demo..."
echo ""

python3 demo_learning_system.py

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
read -p "Launch Dashboard now? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    ./start_dashboard.sh
fi

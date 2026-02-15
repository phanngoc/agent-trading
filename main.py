from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv
import argparse
from datetime import datetime, timedelta

# Load environment variables from .env file
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser(description="Run TradingAgents analysis on a stock")
parser.add_argument("--ticker", type=str, default="NVDA", help="Stock ticker symbol (e.g., VIC.VN, NVDA)")
parser.add_argument("--date", type=str, default=None, help="Analysis date (YYYY-MM-DD format). Default: today")
parser.add_argument("--vendor", type=str, default="trend_news", help="News data vendor (trend_news, yfinance, alpha_vantage)")
args = parser.parse_args()

# Use today's date if not specified
if args.date is None:
    args.date = datetime.now().strftime("%Y-%m-%d")

# Create a custom config
config = DEFAULT_CONFIG.copy()
config["deep_think_llm"] = "gpt-5-mini"  # Use a different model
config["quick_think_llm"] = "gpt-5-mini"  # Use a different model
config["max_debate_rounds"] = 1  # Increase debate rounds

# Configure data vendors
config["data_vendors"] = {
    "core_stock_apis": "yfinance",           # Options: alpha_vantage, yfinance
    "technical_indicators": "yfinance",      # Options: alpha_vantage, yfinance
    "fundamental_data": "yfinance",          # Options: alpha_vantage, yfinance
    "news_data": args.vendor,                # Use vendor from command line (default: trend_news)
}

print(f"Analyzing {args.ticker} on {args.date} using news from {args.vendor}...")

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate
_, decision = ta.propagate(args.ticker, args.date)
print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns

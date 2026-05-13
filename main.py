"""TradingAgents CLI entry point.

Honors TRADINGAGENTS_* env vars via DEFAULT_CONFIG's env-var overlay
(see tradingagents/default_config.py) so a `.env` file can drive
provider/model/limits without code edits. Explicit `--*` flags still win
over env vars where set.
"""

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

from dotenv import load_dotenv
import argparse
import os
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser(description="Run TradingAgents analysis on a stock")
parser.add_argument("--ticker", type=str, default="NVDA",
                    help="Stock ticker symbol (e.g., VIC.VN, NVDA)")
parser.add_argument("--date", type=str, default=None,
                    help="Analysis date (YYYY-MM-DD format). Default: today")
parser.add_argument("--vendor", type=str, default=None,
                    help="News data vendor (trend_news, yfinance, alpha_vantage). "
                         "Default: from config (trend_news for VN-friendly setup)")
parser.add_argument("--provider", type=str, default=None,
                    help="LLM provider (anthropic, openai, google, ollama, openrouter, ...). "
                         "Default: from TRADINGAGENTS_LLM_PROVIDER env or config")
parser.add_argument("--deep-model", type=str, default=None,
                    help="Deep-thinking model id. Default: from TRADINGAGENTS_DEEP_THINK_LLM env or config")
parser.add_argument("--quick-model", type=str, default=None,
                    help="Quick-thinking model id. Default: from TRADINGAGENTS_QUICK_THINK_LLM env or config")
parser.add_argument("--analysts", type=str, default="market,social,news,fundamentals",
                    help="Comma-separated analyst types. "
                         "Options: market, social, sentiment, news, fundamentals. "
                         "Use 'sentiment' for upstream's StockTwits+Reddit analyst (US tickers); "
                         "'social' for the local trend_news-friendly analyst (VN tickers).")
parser.add_argument("--debug", action="store_true", help="Print intermediate messages while streaming")
args = parser.parse_args()

if args.date is None:
    args.date = datetime.now().strftime("%Y-%m-%d")

# Build config. DEFAULT_CONFIG already had TRADINGAGENTS_* env overlay
# applied at import time; CLI flags override those.
config = DEFAULT_CONFIG.copy()

if args.provider:
    config["llm_provider"] = args.provider
elif config.get("llm_provider") == "openai" and not os.environ.get("TRADINGAGENTS_LLM_PROVIDER"):
    # Backward-compat default for this fork: prefer Anthropic when no
    # provider was explicitly chosen (matches pre-upgrade behavior).
    config["llm_provider"] = "anthropic"
    config["deep_think_llm"] = "claude-3-haiku-20240307"
    config["quick_think_llm"] = "claude-3-haiku-20240307"
    config["backend_url"] = None  # let anthropic client pick its endpoint

if args.deep_model:
    config["deep_think_llm"] = args.deep_model
if args.quick_model:
    config["quick_think_llm"] = args.quick_model

if args.vendor:
    config["data_vendors"] = dict(config["data_vendors"], news_data=args.vendor)

selected_analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]

print(
    f"Analyzing {args.ticker} on {args.date} "
    f"via {config['llm_provider']}/{config['deep_think_llm']} "
    f"(news: {config['data_vendors']['news_data']}, analysts: {selected_analysts})"
)

ta = TradingAgentsGraph(
    selected_analysts=selected_analysts,
    debug=args.debug,
    config=config,
)

_, decision = ta.propagate(args.ticker, args.date)
print(decision)

# Outcome reflection (call once realized returns are known):
#   ta.reflect_and_remember(returns_losses=...)

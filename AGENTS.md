# TradingAgents Project - AI Coding Assistant Guide

**Version**: 1.0  
**Last Updated**: February 15, 2026  
**Purpose**: Help AI assistants quickly understand and work with this multi-agent trading system

---

## 🎯 Project Overview

**TradingAgents** is a multi-agent AI debate system for stock trading analysis. It uses a **collaborative reasoning framework** where specialized analyst agents gather data, researcher agents debate perspectives, and a risk management panel makes final decisions.

### Key Features
- ✅ Multi-agent debate architecture with 10+ specialized agents
- ✅ Vendor-agnostic data pipeline (yfinance, Alpha Vantage, trend_news)
- ✅ Vietnamese stock market support with sentiment analysis
- ✅ LangGraph-based workflow orchestration
- ✅ Multiple LLM provider support (OpenAI, Google, Anthropic)
- ✅ Reflection and memory system for learning from past decisions

---

## 📁 Critical File Locations

### Core System Files
```
tradingagents/
├── graph/
│   ├── trading_graph.py          # Main orchestration graph
│   ├── setup.py                  # Graph node setup and configuration
│   ├── conditional_logic.py      # Routing logic between nodes
│   ├── propagation.py            # Forward propagation functions
│   └── reflection.py             # Reflection and memory system
│
├── agents/
│   ├── analysts/                 # Layer 1: Data gathering agents
│   │   ├── market_analyst.py    # Technical analysis (price, volume, indicators)
│   │   ├── news_analyst.py      # News trends and sentiment
│   │   ├── social_media_analyst.py  # Company news and sentiment
│   │   └── fundamentals_analyst.py  # Financial statements
│   │
│   ├── researchers/              # Layer 2: Debate agents
│   │   ├── bull_researcher.py   # Arguments for buying
│   │   └── bear_researcher.py   # Arguments for selling
│   │
│   ├── managers/                 # Layer 3: Decision makers
│   │   ├── research_manager.py  # Synthesizes research debate
│   │   └── risk_manager.py      # Final risk assessment
│   │
│   ├── risk_mgmt/                # Risk debate panel
│   │   ├── aggressive_debator.py
│   │   ├── conservative_debator.py
│   │   └── neutral_debator.py
│   │
│   ├── trader/
│   │   └── trader.py            # Executes final trade decision
│   │
│   └── utils/                    # Tools exposed to agents
│       ├── core_stock_tools.py  # OHLCV data tools
│       ├── technical_indicators_tools.py
│       ├── fundamental_data_tools.py
│       ├── news_data_tools.py   # News fetching tools
│       ├── agent_states.py      # State definitions
│       └── memory.py            # Memory management
│
├── dataflows/                    # Data vendor integrations
│   ├── interface.py             # ⭐ VENDOR ROUTING SYSTEM
│   ├── y_finance.py             # yfinance implementation
│   ├── yfinance_news.py         # yfinance news
│   ├── alpha_vantage.py         # Alpha Vantage APIs
│   ├── alpha_vantage_news.py    # Alpha Vantage news
│   ├── trend_news_api.py        # Vietnamese news API (NEW)
│   └── config.py                # Configuration management
│
├── llm_clients/                  # LLM provider abstraction
│   ├── factory.py               # Client factory
│   ├── openai_client.py         # OpenAI/compatible APIs
│   ├── anthropic_client.py      # Claude
│   ├── google_client.py         # Gemini
│   └── base_client.py           # Base interface
│
└── default_config.py            # ⭐ MAIN CONFIGURATION FILE
```

### Entry Points
- **main.py** - CLI entry point for running analysis
- **test.py** - Unit tests
- **test_trend_news_integration.py** - Integration tests for Vietnamese news

---

## 🔄 System Architecture

### Multi-Agent Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    START (User Input)                       │
│                  ticker: VIC.VN, date: 2026-02-13          │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              LAYER 1: ANALYST AGENTS (Parallel)             │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Market     │  │     News     │  │    Social    │     │
│  │   Analyst    │  │   Analyst    │  │    Media     │     │
│  │  (Technical) │  │  (Trending)  │  │   Analyst    │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                  │                  │              │
│         │  ┌──────────────────────┐          │              │
│         └──│  Fundamentals        │──────────┘              │
│            │  Analyst             │                          │
│            │  (Financials)        │                          │
│            └──────────┬───────────┘                          │
│                       │                                      │
│         Each generates specialized report                   │
└───────────────────────┼─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              LAYER 2: RESEARCH DEBATE                       │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐         ┌──────────────┐                 │
│  │     Bull     │  ←───→  │     Bear     │                 │
│  │  Researcher  │         │  Researcher  │                 │
│  │ (Buy Args)   │         │ (Sell Args)  │                 │
│  └──────┬───────┘         └──────┬───────┘                 │
│         │                         │                          │
│         └────────┬────────────────┘                          │
│                  │                                           │
│                  ▼                                           │
│         ┌────────────────┐                                  │
│         │   Research     │                                  │
│         │   Manager      │                                  │
│         │  (Synthesis)   │                                  │
│         └────────┬───────┘                                  │
└──────────────────┼─────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    TRADER DECISION                          │
├─────────────────────────────────────────────────────────────┤
│              ┌────────────────┐                             │
│              │     Trader     │                             │
│              │   (Decision)   │                             │
│              └────────┬───────┘                             │
└──────────────────────┼─────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              LAYER 3: RISK MANAGEMENT DEBATE                │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │  Aggressive  │←→│   Neutral    │←→│ Conservative │     │
│  │   Debator    │  │   Debator    │  │   Debator    │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                  │                  │              │
│         └──────────┬───────┴──────────────────┘              │
│                    │                                         │
│                    ▼                                         │
│           ┌────────────────┐                                │
│           │  Risk Manager  │                                │
│           │ (Final Judge)  │                                │
│           └────────┬───────┘                                │
└────────────────────┼───────────────────────────────────────┘
                     │
                     ▼
              ┌──────────────┐
              │  FINAL RESULT│
              │  - Decision  │
              │  - Rationale │
              │  - Risk Level│
              └──────────────┘
```

### State Flow

State is passed through the graph and accumulates information:

```python
AgentState = {
    "ticker": "VIC.VN",
    "date": "2026-02-13",
    
    # Layer 1 outputs
    "market_report": "Technical analysis...",
    "news_report": "News from Vietnamese sources...",
    "sentiment_report": "Company sentiment...",
    "fundamentals_report": "Financial statement analysis...",
    
    # Layer 2 outputs
    "bull_arguments": "Reasons to buy...",
    "bear_arguments": "Reasons to sell...",
    "research_recommendation": "Overall assessment...",
    
    # Layer 3 outputs
    "trader_decision": "BUY/SELL/HOLD with reasoning",
    "aggressive_risk_view": "...",
    "conservative_risk_view": "...",
    "neutral_risk_view": "...",
    "final_risk_assessment": "...",
    
    # Metadata
    "messages": [...],  # Conversation history
    "memory": {...},    # Past learnings
}
```

---

## 🔌 Vendor Routing System

**Location**: `tradingagents/dataflows/interface.py`

### How It Works

The system uses a **flexible vendor routing architecture** that allows:
- ✅ Switch data providers via config (no code changes)
- ✅ Automatic fallback if primary vendor fails
- ✅ Tool-level and category-level vendor selection
- ✅ Easy addition of new vendors

### Architecture

```python
# Data is organized by categories
TOOLS_CATEGORIES = {
    "news_data": {
        "tools": ["get_news", "get_global_news", "get_insider_transactions"]
    },
    "core_stock_apis": {
        "tools": ["get_stock_data"]
    },
    "technical_indicators": {
        "tools": ["get_indicators"]
    },
    "fundamental_data": {
        "tools": ["get_fundamentals", "get_balance_sheet", ...]
    }
}

# Each tool maps to vendor implementations
VENDOR_METHODS = {
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "trend_news": get_trend_news,  # Vietnamese news
    }
}
```

### Configuration

```python
# In default_config.py or custom config
config = {
    "data_vendors": {
        "news_data": "trend_news",        # Category-level default
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
    },
    "tool_vendors": {
        # Tool-level overrides (takes precedence)
        "get_news": "alpha_vantage",  # Override for specific tool
    }
}
```

### Calling Flow

```python
# Agent calls tool (doesn't know about vendors)
result = get_news("VIC.VN", "2026-02-01", "2026-02-15")

# Internally routes through vendor system:
route_to_vendor("get_news", "VIC.VN", "2026-02-01", "2026-02-15")
  ↓
# 1. Determine primary vendor from config
vendor = get_vendor("news_data", "get_news")  # Returns "trend_news"
  ↓
# 2. Try primary vendor
try:
    return get_trend_news("VIC.VN", "2026-02-01", "2026-02-15")
except AlphaVantageRateLimitError:
    # 3. Fallback to next vendor
    return get_news_yfinance("VIC.VN", "2026-02-01", "2026-02-15")
```

---

## 🇻🇳 Vietnamese Stock Market Integration

### New trend_news Vendor (Added Feb 15, 2026)

**Purpose**: Fetch Vietnamese market news with sentiment analysis from local database

**Files**:
- `tradingagents/dataflows/trend_news_api.py` - Integration implementation
- `trend_news/server.py` - FastAPI server (port 8000)
- `trend_news/output/trend_news.db` - SQLite database with news articles

**Supported Tickers**:
```python
VIETNAMESE_TICKER_MAP = {
    "VIC.VN": ["Vingroup", "Vinhomes"],
    "VNM.VN": ["Vinamilk"],
    "VCB.VN": ["Vietcombank"],
    "VHM.VN": ["Vinhomes"],
    "FPT.VN": ["FPT"],
    "HPG.VN": ["Hòa Phát", "Hoa Phat"],
    "TCB.VN": ["Techcombank"],
    "MSN.VN": ["Masan"],
    # ... 15 total
}
```

**API Endpoints**:
```bash
# Alpha Vantage compatible
GET /query?function=NEWS_SENTIMENT&tickers=Vingroup&time_from=20260201T0000&time_to=20260215T0000

# Native format
GET /api/v1/news?start_date=2026-02-01&end_date=2026-02-15&limit=50
```

**Response Format** (converted to markdown for LLM):
```markdown
## VIC.VN News from Vietnamese Sources, 2026-02-01 to 2026-02-15:
**Company**: Vingroup
**Total Articles**: 12

### Vingroup công bố kế hoạch mở rộng Vinfast
**[Sentiment: Bullish (0.45)]**
**Source**: vnexpress_kinhdoanh
**Published**: 2026-02-10 14:30:00
**Link**: https://...
```

**Configuration**:
```python
config = {
    "data_vendors": {
        "news_data": "trend_news",  # Use Vietnamese news
    },
    "trend_news_api_url": "http://localhost:8000",
    "trend_news_sources": [],  # Empty = all sources
}
```

**Usage**:
```bash
# Start server first
cd trend_news && python server.py

# Run analysis
python main.py --ticker VIC.VN --date 2026-02-13
```

---

## 🛠 Adding New Features

### Adding a New Agent

1. **Create agent file** in appropriate category:
   ```python
   # tradingagents/agents/analysts/crypto_analyst.py
   from langchain.agents import create_react_agent
   from tradingagents.llm_clients import create_llm_client
   
   def create_crypto_analyst(config):
       llm = create_llm_client(config, "quick_think_llm")
       tools = [get_crypto_data, get_onchain_metrics]
       
       prompt = """You are a cryptocurrency analyst..."""
       
       return create_react_agent(llm, tools, prompt)
   ```

2. **Register in graph** (`tradingagents/graph/setup.py`):
   ```python
   def setup_nodes(workflow, config):
       # Add node
       workflow.add_node("crypto_analyst", create_crypto_analyst_node(config))
       
       # Add edges
       workflow.add_edge("crypto_analyst", "research_manager")
   ```

3. **Update state** (`tradingagents/agents/utils/agent_states.py`):
   ```python
   class AgentState(TypedDict):
       crypto_report: Annotated[str, operator.add]
   ```

### Adding a New Data Vendor

1. **Create vendor module**:
   ```python
   # tradingagents/dataflows/new_vendor.py
   def get_news(ticker, start_date, end_date):
       """Fetch news from new vendor."""
       # Implementation
       return formatted_news_string
   ```

2. **Register in interface.py**:
   ```python
   from .new_vendor import get_news as get_new_vendor_news
   
   VENDOR_LIST.append("new_vendor")
   
   VENDOR_METHODS["get_news"]["new_vendor"] = get_new_vendor_news
   ```

3. **Add configuration**:
   ```python
   # default_config.py
   config["data_vendors"]["news_data"] = "new_vendor"
   config["new_vendor_api_key"] = "..."
   ```

### Adding a New Tool

1. **Create tool function**:
   ```python
   # tradingagents/agents/utils/custom_tools.py
   from langchain.tools import tool
   
   @tool
   def get_options_data(ticker: str) -> str:
       """Retrieve options chain data for a ticker."""
       # Implementation
       return result
   ```

2. **Register in category** (`interface.py`):
   ```python
   TOOLS_CATEGORIES["options_data"] = {
       "description": "Options market data",
       "tools": ["get_options_data"]
   }
   
   VENDOR_METHODS["get_options_data"] = {
       "yfinance": get_yfinance_options,
       "cboe": get_cboe_options,
   }
   ```

3. **Add to agent tools**:
   ```python
   # In analyst setup
   tools = [get_stock_data, get_news, get_options_data]
   ```

---

## 🧪 Testing and Debugging

### Quick Tests

```bash
# Test vendor routing
python test_trend_news_integration.py

# Test specific agent
cd tradingagents/agents/analysts
python -c "from news_analyst import create_news_analyst; print(create_news_analyst({}))"

# Run full analysis with debug
python main.py --ticker VIC.VN --date 2026-02-13
```

### Debug Mode

Set `debug=True` in TradingAgentsGraph initialization:
```python
ta = TradingAgentsGraph(debug=True, config=config)
```

This prints:
- Each agent's input
- Tool calls and results
- Agent outputs
- State transitions

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'google.auth'`
```bash
# Solution: Use virtual environment
source venv/bin/activate
pip install -r requirements.txt
```

**Issue**: `Error fetching news from trend_news API: 404`
```bash
# Solution: Start trend_news server
cd trend_news && python server.py
```

**Issue**: Agent using wrong ticker
```bash
# Solution: Check main.py argument parsing
python main.py --ticker VIC.VN  # Not NVDA
```

**Issue**: Rate limit errors from Alpha Vantage
```bash
# Solution: Switch to different vendor or use fallback
config["data_vendors"]["news_data"] = "trend_news"
```

---

## 📊 Performance Optimization

### Cost Reduction
- Use `quick_think_llm` for routine analysis (gpt-5-mini)
- Use `deep_think_llm` for complex decisions (gpt-5.2)
- Limit debate rounds: `max_debate_rounds: 1`

### Speed Optimization
- Cache stock data in `dataflows/data_cache/`
- Use local trend_news instead of external APIs
- Reduce look-back periods for news (7 days default)

### Quality Improvement
- Increase debate rounds for important decisions
- Enable reflection: `ta.reflect_and_remember(returns)`
- Use memory from past analyses

---

## 🔑 Key Design Principles

### 1. **Separation of Concerns**
- Agents don't know about data vendors
- Tools abstract data fetching
- LLM clients abstract model providers

### 2. **Fail-Safe Design**
- Automatic vendor fallback
- Graceful degradation if data unavailable
- Default values in configuration

### 3. **Extensibility**
- New agents via node addition
- New vendors via method mapping
- New tools via decorator

### 4. **Transparency**
- Full conversation history in state
- Debug mode for troubleshooting
- Clear reports from each agent

---

## 🚀 Quick Start for AI Assistants

When helping with this project:

1. **Check configuration first**: `tradingagents/default_config.py`
2. **Understand the workflow**: Read graph setup in `trading_graph.py`
3. **Find the right file**: Use the directory structure above
4. **Test changes**: Use `test_trend_news_integration.py` or create simple tests
5. **Follow patterns**: Look at existing agents/vendors for examples

### Common Tasks

**"Add support for cryptocurrency"**
→ Create `crypto_analyst.py`, add crypto data tools, register in graph

**"Switch to different LLM provider"**
→ Modify `config["llm_provider"]` and set API keys in `.env`

**"Add new data source for Vietnamese stocks"**
→ Create vendor module, add to `VENDOR_METHODS`, update config

**"Improve news analysis"**
→ Modify prompt in `news_analyst.py`, add more tools, adjust report format

**"Debug why agent uses wrong data"**
→ Check `interface.py` routing, verify config, test vendor directly

---

## 📚 Additional Resources

### Related Files
- `README.md` - User documentation
- `pyproject.toml` - Dependencies
- `.env.example` - Environment variables template
- `requirements.txt` - Python packages

### External Dependencies
- **LangChain** - Agent framework
- **LangGraph** - Workflow orchestration
- **yfinance** - Stock data (primary)
- **FastAPI** - trend_news API server
- **OpenAI/Anthropic/Google APIs** - LLM providers

### Vietnamese Market Data
- **trend_news** - Local news database with sentiment
- **Sources**: VnExpress, CafeF, Dân Trí, Money24h (30 total)
- **Update frequency**: Real-time scraping
- **Sentiment**: Lexicon-based with learning system

---

## 🔄 Recent Changes

### February 15, 2026
- ✅ Added trend_news vendor for Vietnamese market news
- ✅ Created ticker mapping for VN stocks (VIC.VN, VNM.VN, etc.)
- ✅ Integrated sentiment analysis in news reports
- ✅ Fixed main.py to accept --ticker argument
- ✅ Added test suite for trend_news integration
- ✅ Updated default config to use trend_news for news_data

### Configuration Changes
```python
# OLD
config["data_vendors"]["news_data"] = "yfinance"

# NEW
config["data_vendors"]["news_data"] = "trend_news"
config["trend_news_api_url"] = "http://localhost:8000"
```

---

## 💡 Tips for AI Assistants

1. **Always check if trend_news server is running** when working with Vietnamese stocks
2. **Use debug mode** to see what's happening in the agent workflow
3. **Check vendor routing** if data fetching fails - it may be using wrong source
4. **Respect the state flow** - don't skip agents or modify state structure
5. **Test with Vietnamese tickers** (VIC.VN) to verify new features work
6. **Keep tool signatures consistent** - all get_news() should have same parameters
7. **Format output for LLMs** - use markdown strings, not raw JSON
8. **Handle errors gracefully** - return informative messages, not exceptions

---

**Made by**: phanngoc  
**Repository**: agent-trading  
**License**: See LICENSE file  
**Contact**: Check repository for issues and discussions

from langchain_core.prompts import ChatPromptTemplate
from tradingagents.agents.utils.agent_utils import get_stock_data, get_indicators
from tradingagents.agents.utils.analyst_runner import run_analyst_loop


SYSTEM_PROMPT = """You are a trading assistant tasked with analyzing financial markets. Your role is to select the **most relevant indicators** for a given market condition or trading strategy from the following list. The goal is to choose up to **8 indicators** that provide complementary insights without redundancy.

Moving Averages:
- close_50_sma: 50 SMA — medium-term trend, dynamic support/resistance.
- close_200_sma: 200 SMA — long-term benchmark, golden/death cross setups.
- close_10_ema: 10 EMA — short-term momentum, quick shifts.

MACD Related:
- macd: MACD — momentum via EMA differences, look for crossovers.
- macds: MACD Signal — smoothing of MACD, crossover triggers.
- macdh: MACD Histogram — momentum strength, divergence early warning.

Momentum:
- rsi: RSI — overbought/oversold (70/30 thresholds), divergence signals.

Volatility:
- boll: Bollinger Middle — 20 SMA, dynamic benchmark.
- boll_ub: Bollinger Upper — overbought/breakout zone.
- boll_lb: Bollinger Lower — oversold zone.
- atr: ATR — volatility measure for stop-loss sizing.

Volume:
- vwma: VWMA — volume-weighted moving average, trend confirmation.

Instructions:
1. Call get_stock_data ONCE first to retrieve price CSV.
2. Then call get_indicators for each selected indicator (one at a time).
3. Do NOT call get_stock_data again after the first call.
4. Write a detailed, nuanced report with specific values — avoid vague "mixed" statements.
5. Append a Markdown table summarizing key indicators and signals at the end."""


def create_market_analyst(llm):
    tools = [get_stock_data, get_indicators]

    def market_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]

        prompt = (
            f"Analyze the market technicals for {ticker} as of {current_date}. "
            f"Available tools: {', '.join(t.name for t in tools)}.\n\n"
            f"{SYSTEM_PROMPT}"
        )

        chain = (
            ChatPromptTemplate.from_messages([("human", "{input}")])
            | llm.bind_tools(tools)
        )
        # Wrap chain to accept message list directly
        class _Chain:
            def invoke(self, messages):
                # Pass messages directly to llm.bind_tools
                return llm.bind_tools(tools).invoke(messages)

        report = run_analyst_loop(
            chain=_Chain(),
            tools=tools,
            initial_prompt=prompt,
        )

        return {
            "messages": [],  # No messages to add to global state
            "market_report": report,
        }

    return market_analyst_node

from tradingagents.agents.utils.agent_utils import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
)
from tradingagents.agents.utils.analyst_runner import run_analyst_loop


SYSTEM_PROMPT = """You are a fundamentals analyst tasked with analyzing a company's financial health.

Available tools:
- get_fundamentals: Company overview, ratios, key metrics
- get_balance_sheet: Assets, liabilities, equity
- get_income_statement: Revenue, profit, margins
- get_cashflow: Cash flow from operations, investing, financing

Instructions:
1. Call get_fundamentals first for the overview.
2. Then call get_income_statement and get_balance_sheet for detail.
3. Analyze financial strength, growth trends, and key ratios.
4. Write a comprehensive report covering:
   - Revenue and profitability trends
   - Balance sheet health (debt, liquidity)
   - Key financial ratios (P/E, ROE, debt/equity)
   - Any red flags or strengths
5. Append a Markdown table with key financial metrics."""


def create_fundamentals_analyst(llm):
    tools = [get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement]

    def fundamentals_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]

        prompt = (
            f"Analyze the fundamental financials for {ticker} as of {current_date}. "
            f"Available tools: {', '.join(t.name for t in tools)}.\n\n"
            f"{SYSTEM_PROMPT}"
        )

        class _Chain:
            def invoke(self, messages):
                return llm.bind_tools(tools).invoke(messages)

        report = run_analyst_loop(
            chain=_Chain(),
            tools=tools,
            initial_prompt=prompt,
        )

        return {
            "messages": [],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node

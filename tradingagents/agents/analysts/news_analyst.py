from tradingagents.agents.utils.agent_utils import get_news, get_global_news
from tradingagents.agents.utils.analyst_runner import run_analyst_loop


SYSTEM_PROMPT = """You are a news analyst tasked with analyzing recent news and its impact on a company's stock.

Instructions:
1. Use get_news to fetch company-specific news for the ticker.
2. Use get_global_news to fetch relevant macro/global news.
3. Analyze sentiment, key events, and potential market impact.
4. Write a comprehensive report covering:
   - Key news events and their implications
   - Overall sentiment (bullish/bearish/neutral)
   - Potential catalysts or risks
5. Append a Markdown table summarizing news sentiment and key events."""


def create_news_analyst(llm):
    tools = [get_news, get_global_news]

    def news_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]

        prompt = (
            f"Analyze recent news for {ticker} as of {current_date}. "
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
            "news_report": report,
        }

    return news_analyst_node

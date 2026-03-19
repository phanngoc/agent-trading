from tradingagents.agents.utils.agent_utils import get_news
from tradingagents.agents.utils.analyst_runner import run_analyst_loop


SYSTEM_PROMPT = """You are a social media and sentiment analyst tasked with gauging market sentiment for a company.

Instructions:
1. Use get_news to fetch recent coverage and public sentiment signals.
2. Analyze the tone, frequency, and key themes in recent mentions.
3. Write a sentiment report covering:
   - Overall market/public sentiment (bullish/bearish/neutral)
   - Key themes driving sentiment
   - Notable social signals or unusual activity
   - Sentiment trend over recent period
4. Append a Markdown table summarizing sentiment signals."""


def create_social_media_analyst(llm):
    tools = [get_news]

    def social_media_analyst_node(state):
        ticker = state["company_of_interest"]
        current_date = state["trade_date"]

        prompt = (
            f"Analyze social media sentiment and public perception for {ticker} as of {current_date}. "
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
            "sentiment_report": report,
        }

    return social_media_analyst_node

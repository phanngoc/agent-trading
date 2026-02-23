"""
Chainlit chatbot UI — Vietnamese Financial News Assistant.

Run:
    PYTHONPATH=/path/to/TradingAgents/trend_news \
        chainlit run trend_news/chatbot/app.py --port 8001
"""

import uuid
import os
import sys

import chainlit as cl

# Ensure trend_news is on path when Chainlit runs from project root
_TREND_NEWS_DIR = os.path.dirname(os.path.dirname(__file__))
if _TREND_NEWS_DIR not in sys.path:
    sys.path.insert(0, _TREND_NEWS_DIR)

from chatbot.agent import agent_graph, ChatbotState
from chatbot.prompts import WELCOME_MESSAGE, SENTIMENT_ICONS


@cl.on_chat_start
async def on_chat_start():
    """Initialise a new chat session with a unique user_id."""
    session_id = str(uuid.uuid4())
    cl.user_session.set("user_id", session_id)

    await cl.Message(content=WELCOME_MESSAGE).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Process each user message through the LangGraph agent."""
    user_id: str = cl.user_session.get("user_id")

    # Build initial state
    state: ChatbotState = {
        "query": message.content,
        "user_id": user_id,
        "user_preferences": {},
        "personalized_query": "",
        "raw_news_results": [],
        "ranked_news": [],
        "response": "",
    }

    # Show intermediate status
    async with cl.Step(name="Đang tìm kiếm tin tức...") as step:
        result = await agent_graph.ainvoke(state)
        found = len(result.get("ranked_news", []))
        step.output = f"Tìm thấy {found} bài viết liên quan"

    # Build source elements from top 5 articles
    elements = []
    for article in result.get("ranked_news", [])[:5]:
        title = article.get("title", "")
        url = article.get("url") or article.get("mobile_url") or ""
        source = article.get("source_id", "")
        label = article.get("sentiment_label") or "Neutral"
        icon = SENTIMENT_ICONS.get(label, "⚪")

        if url:
            elements.append(
                cl.Text(
                    name=f"{icon} {source}",
                    content=f"{title}\n{url}",
                    display="inline",
                )
            )

    response_msg = cl.Message(content=result["response"], elements=elements)
    await response_msg.send()

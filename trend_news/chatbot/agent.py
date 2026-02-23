"""
LangGraph agent for the Vietnamese Financial News Chatbot.

Graph:
  retrieve_and_query (mem0 + cognee in parallel)
      |
  if graph_response → direct_response → update_preferences → END
  if chunks ≥3    → rank_and_filter → generate_response → update_preferences → END
  if empty        → sqlite_fallback → rank_and_filter → generate_response → update_preferences → END
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

# Ensure trend_news src is importable
_TREND_NEWS_DIR = os.path.dirname(os.path.dirname(__file__))
if _TREND_NEWS_DIR not in sys.path:
    sys.path.insert(0, _TREND_NEWS_DIR)

from chatbot.config import (
    DB_PATH,
    LLM_PROVIDER,
    OPENAI_API_KEY,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    MEM0_CONFIG,
    MAX_NEWS_RESULTS,
    NEWS_DAYS_LOOKBACK,
    COGNEE_LLM_CONFIG,
    COGNEE_EMBEDDING_ENV,
    COGNEE_DB_PATH,
    setup_cognee_paths,
)
from chatbot.prompts import SYSTEM_PROMPT, NO_NEWS_MESSAGE, COGNEE_GRAPH_SYSTEM_PROMPT
from chatbot.utils import (
    extract_tickers_from_query,
    format_news_for_prompt,
    parse_cognee_results,
    parse_mem0_results,
)


# ---------------------------------------------------------------------------
# Lazy singletons — initialised on first use to avoid import-time side effects
# ---------------------------------------------------------------------------

_memory = None
_llm = None


def _get_memory():
    global _memory
    if _memory is None:
        from mem0 import Memory
        _memory = Memory.from_config(MEM0_CONFIG)
    return _memory


def _get_llm():
    global _llm
    if _llm is None:
        if LLM_PROVIDER == "openai" and OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            _llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                api_key=OPENAI_API_KEY,
                temperature=0.3,
            )
        elif LLM_PROVIDER == "google" and GEMINI_API_KEY:
            from langchain_google_genai import ChatGoogleGenerativeAI
            _llm = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=GEMINI_API_KEY,
                temperature=0.3,
            )
        elif LLM_PROVIDER == "groq" and GROQ_API_KEY:
            from langchain_groq import ChatGroq
            _llm = ChatGroq(model="llama3-8b-8192", groq_api_key=GROQ_API_KEY, temperature=0.3)
        else:
            raise RuntimeError(
                "No LLM configured. Set OPENAI_API_KEY (or GEMINI_API_KEY / GROQ_API_KEY) "
                "and LLM_PROVIDER in .env."
            )
    return _llm


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class ChatbotState(TypedDict):
    query: str
    user_id: str
    user_preferences: Dict[str, Any]
    personalized_query: str
    raw_news_results: List[Dict]
    ranked_news: List[Dict]
    response: str
    graph_response: Optional[str]   # GRAPH_COMPLETION narrative, or None


# ---------------------------------------------------------------------------
# Internal helpers — safe to run concurrently inside asyncio.gather
# ---------------------------------------------------------------------------


async def _run_mem0_search(query: str, user_id: str) -> Dict[str, Any]:
    """Run mem0 preference search (blocking call wrapped in thread)."""
    empty: Dict[str, Any] = {
        "sectors": [], "tickers": [], "topics": [],
        "sentiment_bias": None, "raw_memories": [],
    }
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                _get_memory().search,
                query=query,
                user_id=user_id,
                limit=10,
            ),
            timeout=8.0,
        )
        data = results.get("results", results) if isinstance(results, dict) else results
        return parse_mem0_results(data)
    except asyncio.TimeoutError:
        print("[Agent] mem0 search timed out (8s) — using empty preferences")
        return empty
    except Exception as exc:
        print(f"[Agent] mem0 search error (non-fatal): {exc}")
        return empty


async def _run_cognee_search(query: str) -> tuple:
    """
    Run cognee GRAPH_COMPLETION search.

    Returns (raw_news: List[Dict], graph_response: Optional[str]):
    - If cognee returns a narrative string → graph_response is set, raw_news=[]
    - On timeout / error / empty → graph_response=None, raw_news=[]
      (triggers SQLite fallback downstream)
    """
    try:
        # Path env vars must be set before importing cognee (pydantic-settings reads at import)
        setup_cognee_paths()
        for key, value in COGNEE_EMBEDDING_ENV.items():
            os.environ.setdefault(key, value)

        import cognee
        from cognee.api.v1.search import SearchType

        cognee.config.set_llm_config(COGNEE_LLM_CONFIG)

        results = await asyncio.wait_for(
            cognee.search(
                query_text=query,
                query_type=SearchType.GRAPH_COMPLETION,
                system_prompt=COGNEE_GRAPH_SYSTEM_PROMPT,
                top_k=10,
            ),
            timeout=25.0,
        )

        # GRAPH_COMPLETION returns List[dict] where each dict has a 'search_result' key
        # containing a list of narrative strings.
        narrative = None
        if results:
            first = results[0]
            if isinstance(first, dict):
                parts = first.get("search_result", [])
                if parts and isinstance(parts[0], str) and len(parts[0]) > 50:
                    narrative = "\n\n".join(parts)
            elif isinstance(first, str) and len(first) > 50:
                narrative = first

        if narrative:
            return [], narrative
        return [], None

    except asyncio.TimeoutError:
        print("[Agent] Cognee GRAPH_COMPLETION timed out (20s) — falling back to SQLite")
        return [], None
    except Exception as exc:
        print(f"[Agent] Cognee search error (fallback to SQLite): {exc}")
        return [], None


# ---------------------------------------------------------------------------
# Node: retrieve_and_query  (replaces retrieve_preferences + build_personalized_query + query_cognee)
# ---------------------------------------------------------------------------


async def retrieve_and_query(state: ChatbotState) -> ChatbotState:
    """Run mem0 preference lookup and cognee graph search concurrently."""
    preferences, (raw_news, graph_response) = await asyncio.gather(
        _run_mem0_search(state["query"], state["user_id"]),
        _run_cognee_search(state["query"]),
    )

    # Build personalized query (used by sqlite_fallback path)
    enrichments: List[str] = []
    enrichments.extend(preferences.get("tickers", [])[:3])
    enrichments.extend(preferences.get("topics", [])[:2])
    personalized = state["query"]
    if enrichments:
        personalized = f"{personalized} {' '.join(enrichments)}"

    return {
        **state,
        "user_preferences": preferences,
        "personalized_query": personalized.strip(),
        "raw_news_results": raw_news,
        "graph_response": graph_response,
    }


# ---------------------------------------------------------------------------
# Node: direct_response — use GRAPH_COMPLETION output, skip LLM call
# ---------------------------------------------------------------------------


async def direct_response(state: ChatbotState) -> ChatbotState:
    """Return cognee's GRAPH_COMPLETION answer directly. Zero extra LLM calls."""
    return {**state, "response": state["graph_response"], "ranked_news": []}


# ---------------------------------------------------------------------------
# Node: sqlite_fallback
# ---------------------------------------------------------------------------


def sqlite_fallback(state: ChatbotState) -> ChatbotState:
    """Direct SQLite FTS5 search using the existing DatabaseManager."""
    try:
        from src.core.database import DatabaseManager

        db = DatabaseManager(DB_PATH)
        tickers_str = extract_tickers_from_query(state["query"])
        start_date = (datetime.now() - timedelta(days=NEWS_DAYS_LOOKBACK)).strftime("%Y-%m-%d")

        results = db.get_filtered_news(
            tickers=tickers_str or None,
            start_date=start_date,
            limit=MAX_NEWS_RESULTS * 2,
        )
    except Exception as exc:
        print(f"[Agent] SQLite fallback error: {exc}")
        results = []

    return {**state, "raw_news_results": results}


# ---------------------------------------------------------------------------
# Node: rank_and_filter
# ---------------------------------------------------------------------------


def rank_and_filter(state: ChatbotState) -> ChatbotState:
    """Re-score with ViVADER, deduplicate, sort and limit results."""
    from src.utils.vivader import ViVADERSentimentAnalyzer

    vivader = ViVADERSentimentAnalyzer()
    results = list(state["raw_news_results"])
    prefs = state["user_preferences"]

    # Re-score articles that have no sentiment score
    for article in results:
        if article.get("sentiment_score") is None:
            score = vivader.polarity_scores(article.get("title", "")).get("compound", 0.0)
            article["sentiment_score"] = score
            if score >= 0.35:
                article["sentiment_label"] = "Bullish"
            elif score >= 0.15:
                article["sentiment_label"] = "Somewhat-Bullish"
            elif score <= -0.35:
                article["sentiment_label"] = "Bearish"
            elif score <= -0.15:
                article["sentiment_label"] = "Somewhat-Bearish"
            else:
                article["sentiment_label"] = "Neutral"

    # Filter by sentiment bias
    bias = prefs.get("sentiment_bias")
    if bias == "bullish":
        results = [r for r in results if (r.get("sentiment_score") or 0) > -0.15]
    elif bias == "bearish":
        results = [r for r in results if (r.get("sentiment_score") or 0) < 0.15]

    # Deduplicate by URL then by title prefix
    seen_urls: set = set()
    unique: List[Dict] = []
    for r in results:
        key = r.get("url") or r.get("mobile_url") or r.get("title", "")[:80]
        if key and key not in seen_urls:
            seen_urls.add(key)
            unique.append(r)

    # Sort: recency first, then by sentiment magnitude
    def _sort_key(a: Dict):
        date_str = a.get("crawled_at") or a.get("crawl_date") or "1970-01-01"
        return (date_str, abs(a.get("sentiment_score") or 0))

    unique.sort(key=_sort_key, reverse=True)

    return {**state, "ranked_news": unique[:MAX_NEWS_RESULTS]}


# ---------------------------------------------------------------------------
# Node: generate_response
# ---------------------------------------------------------------------------


async def generate_response(state: ChatbotState) -> ChatbotState:
    """Generate a Vietnamese natural-language response with the LLM."""
    from langchain_core.messages import HumanMessage, SystemMessage

    ranked = state["ranked_news"]
    prefs = state["user_preferences"]

    if not ranked:
        response = NO_NEWS_MESSAGE.format(query=state["query"])
        return {**state, "response": response}

    news_context = format_news_for_prompt(ranked)
    memories = prefs.get("raw_memories", [])
    prefs_summary = "\n".join(f"- {m}" for m in memories[:5]) if memories else "Chưa có thông tin sở thích."

    system_content = SYSTEM_PROMPT.format(
        date=datetime.now().strftime("%d/%m/%Y %H:%M"),
        user_prefs=prefs_summary,
        news_context=news_context,
    )

    try:
        llm = _get_llm()
        ai_msg = await asyncio.wait_for(
            llm.ainvoke(
                [SystemMessage(content=system_content), HumanMessage(content=state["query"])]
            ),
            timeout=25.0,
        )
        response = ai_msg.content
    except asyncio.TimeoutError:
        print("[Agent] generate_response LLM timed out (25s) — returning formatted news")
        response = f"Đây là những tin tức liên quan:\n\n{news_context}"
    except Exception as exc:
        print(f"[Agent] LLM error: {exc}")
        response = f"Đây là những tin tức liên quan:\n\n{news_context}"

    return {**state, "response": response}


# ---------------------------------------------------------------------------
# Node: update_preferences
# ---------------------------------------------------------------------------


async def update_preferences(state: ChatbotState) -> ChatbotState:
    """Store this interaction in mem0 as a fire-and-forget background task."""
    async def _add_memory():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    _get_memory().add,
                    messages=[
                        {"role": "user", "content": state["query"]},
                        {"role": "assistant", "content": state["response"]},
                    ],
                    user_id=state["user_id"],
                ),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            print("[Agent] mem0 add timed out (10s) — memory not saved")
        except Exception as exc:
            print(f"[Agent] mem0 add error (non-fatal): {exc}")

    # Fire-and-forget: don't block the response
    asyncio.create_task(_add_memory())
    return state


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------


def _route_after_search(state: ChatbotState) -> str:
    """Route to direct_response (graph answer), rank_and_filter (chunks), or SQLite fallback."""
    if state.get("graph_response"):
        return "direct_response"
    if len(state.get("raw_news_results", [])) >= 3:
        return "rank_and_filter"
    return "sqlite_fallback"


def create_agent_graph():
    graph = StateGraph(ChatbotState)

    graph.add_node("retrieve_and_query", retrieve_and_query)
    graph.add_node("sqlite_fallback", sqlite_fallback)
    graph.add_node("rank_and_filter", rank_and_filter)
    graph.add_node("direct_response", direct_response)
    graph.add_node("generate_response", generate_response)
    graph.add_node("update_preferences", update_preferences)

    graph.set_entry_point("retrieve_and_query")
    graph.add_conditional_edges("retrieve_and_query", _route_after_search)
    graph.add_edge("sqlite_fallback", "rank_and_filter")
    graph.add_edge("rank_and_filter", "generate_response")
    graph.add_edge("direct_response", "update_preferences")
    graph.add_edge("generate_response", "update_preferences")
    graph.add_edge("update_preferences", END)

    return graph.compile()


# Singleton agent graph — imported by app.py
agent_graph = create_agent_graph()

"""
Integration tests: mem0 memory add & retrieve for the chatbot agent.

Verifies that:
  1. _run_mem0_search returns a valid (possibly empty) preference dict.
  2. After adding a conversation via mem0.add(), the same query can be
     retrieved back — raw_memories is non-empty.
  3. parse_mem0_results correctly shapes the raw mem0 payload.
  4. The full agent graph produces a non-empty `response` for the
     canonical stock-market query (cognee + SQLite both mocked away so no
     external services are required).

Run (from trend_news/ directory):
    pytest tests/test_chatbot_mem0_integration.py -v

To run ONLY the faster unit tests (no real mem0 I/O):
    pytest tests/test_chatbot_mem0_integration.py -v -m "not slow"

To include the real mem0 round-trip tests:
    pytest tests/test_chatbot_mem0_integration.py -v -m slow
"""

import asyncio
import os
import sys
import uuid
import tempfile
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_TREND_NEWS_DIR = os.path.dirname(os.path.dirname(__file__))
if _TREND_NEWS_DIR not in sys.path:
    sys.path.insert(0, _TREND_NEWS_DIR)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STOCK_QUERY = "Thị trường chứng khoán hôm nay thế nào?"
SAMPLE_RESPONSE = (
    "Thị trường chứng khoán hôm nay đang cho thấy bức tranh lạc quan "
    "với VN-Index tăng nhẹ, cảm xúc Bullish."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_temp_mem0_config(tmp_dir: str) -> Dict[str, Any]:
    """Build a mem0 config that stores data in a temporary directory."""
    from chatbot.config import (
        OPENAI_API_KEY,
        GEMINI_API_KEY,
        _MEM0_LLM,        # type: ignore[attr-defined]
        _MEM0_EMBEDDER,   # type: ignore[attr-defined]
    )

    return {
        "version": "v1.0",
        "history_db_path": os.path.join(tmp_dir, "mem0_history_test.db"),
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "test_user_memories",
                "path": os.path.join(tmp_dir, "mem0_chromadb_test"),
            },
        },
        "llm": _MEM0_LLM,
        "embedder": _MEM0_EMBEDDER,
    }


# ---------------------------------------------------------------------------
# Unit tests (fast, no real mem0 / cognee I/O)
# ---------------------------------------------------------------------------

class TestParseMemResults:
    """Unit-test the parse_mem0_results helper."""

    def test_returns_expected_keys(self):
        from chatbot.utils import parse_mem0_results

        result = parse_mem0_results([])
        assert set(result.keys()) == {"sectors", "tickers", "topics", "sentiment_bias", "raw_memories"}

    def test_empty_input_gives_empty_lists(self):
        from chatbot.utils import parse_mem0_results

        result = parse_mem0_results([])
        assert result["sectors"] == []
        assert result["tickers"] == []
        assert result["topics"] == []
        assert result["sentiment_bias"] is None
        assert result["raw_memories"] == []

    def test_raw_memories_populated(self):
        from chatbot.utils import parse_mem0_results

        memories = [
            {"memory": "Người dùng quan tâm đến VIC", "score": 0.9},
            {"memory": "Thị trường chứng khoán", "score": 0.7},
        ]
        result = parse_mem0_results(memories)
        assert len(result["raw_memories"]) == 2
        assert "VIC" in " ".join(result["raw_memories"])


class TestRunMem0SearchMocked:
    """Unit-test _run_mem0_search with mem0.Memory fully mocked."""

    def test_returns_empty_on_exception(self):
        from chatbot import agent as agent_module

        mock_memory = MagicMock()
        mock_memory.search.side_effect = RuntimeError("connection error")

        with patch.object(agent_module, "_get_memory", return_value=mock_memory):
            result = asyncio.run(
                agent_module._run_mem0_search(STOCK_QUERY, "user-test-1")
            )

        assert result["sectors"] == []
        assert result["tickers"] == []
        assert result["raw_memories"] == []

    def test_returns_parsed_memories_on_success(self):
        from chatbot import agent as agent_module
        from chatbot.utils import parse_mem0_results

        raw = [{"memory": "Người dùng hỏi về thị trường chứng khoán", "score": 0.85}]
        mock_memory = MagicMock()
        mock_memory.search.return_value = {"results": raw}

        with patch.object(agent_module, "_get_memory", return_value=mock_memory):
            result = asyncio.run(
                agent_module._run_mem0_search(STOCK_QUERY, "user-test-2")
            )

        assert len(result["raw_memories"]) == 1
        assert "chứng khoán" in result["raw_memories"][0].lower()

    def test_timeout_returns_empty(self):
        from chatbot import agent as agent_module

        # mem0.search is a sync blocking call wrapped in asyncio.to_thread.
        # Simulate a very slow blocking call by sleeping long enough that
        # wait_for (8 s timeout) triggers. We patch at the thread level
        # by making the sync method block forever via an Event.
        import threading

        _block = threading.Event()

        def _slow_blocking_search(*args, **kwargs):
            # Block for 60 s — wait_for(8 s) will cancel this thread task first
            _block.wait(timeout=60)
            return {"results": []}

        mock_memory = MagicMock()
        mock_memory.search.side_effect = _slow_blocking_search

        with patch.object(agent_module, "_get_memory", return_value=mock_memory):
            result = asyncio.run(
                agent_module._run_mem0_search(STOCK_QUERY, "user-test-timeout")
            )

        _block.set()  # unblock the lingering thread
        # Timeout should yield empty preferences without raising
        assert result["raw_memories"] == []


class TestAgentGraphWithMocks:
    """Integration test for the full graph with cognee + SQLite mocked."""

    @pytest.fixture()
    def mock_cognee_empty(self):
        """Patch _run_cognee_search to always return ([], None) — forces SQLite path."""
        from chatbot import agent as agent_module

        with patch.object(
            agent_module,
            "_run_cognee_search",
            new=AsyncMock(return_value=([], None)),
        ):
            yield

    @pytest.fixture()
    def mock_cognee_narrative(self):
        """Patch _run_cognee_search to return a narrative string — forces direct_response path."""
        from chatbot import agent as agent_module

        with patch.object(
            agent_module,
            "_run_cognee_search",
            new=AsyncMock(return_value=([], SAMPLE_RESPONSE)),
        ):
            yield

    @pytest.fixture()
    def mock_mem0_empty(self):
        """Patch _run_mem0_search to return empty preferences."""
        from chatbot import agent as agent_module

        empty = {
            "sectors": [], "tickers": [], "topics": [],
            "sentiment_bias": None, "raw_memories": [],
        }
        with patch.object(
            agent_module,
            "_run_mem0_search",
            new=AsyncMock(return_value=empty),
        ):
            yield

    @pytest.fixture()
    def mock_mem0_with_memory(self):
        """Patch _run_mem0_search to return already-stored memory."""
        from chatbot import agent as agent_module

        prefs = {
            "sectors": ["securities"],
            "tickers": [],
            "topics": ["thị trường chứng khoán"],
            "sentiment_bias": None,
            "raw_memories": ["Người dùng đã hỏi về thị trường chứng khoán trước đây"],
        }
        with patch.object(
            agent_module,
            "_run_mem0_search",
            new=AsyncMock(return_value=prefs),
        ):
            yield

    @pytest.fixture()
    def mock_sqlite_articles(self):
        """Patch sqlite_fallback to return 3 realistic articles."""
        from chatbot import agent as agent_module

        articles = [
            {
                "title": "VN-Index tăng 0.52% phiên sáng",
                "url": "https://vnexpress.net/vn-index-tang.html",
                "source_id": "vnexpress",
                "sentiment_score": 0.45,
                "sentiment_label": "Bullish",
                "crawled_at": "2026-02-15T08:30:00",
            },
            {
                "title": "Chứng khoán chờ VN-Index vượt mốc 1.829",
                "url": "https://cafef.vn/vn-index-moc.html",
                "source_id": "cafef",
                "sentiment_score": 0.2,
                "sentiment_label": "Somewhat-Bullish",
                "crawled_at": "2026-02-15T07:00:00",
            },
            {
                "title": "Thanh khoản thị trường cải thiện",
                "url": "https://24hmoney.vn/thanh-khoan.html",
                "source_id": "24hmoney",
                "sentiment_score": 0.1,
                "sentiment_label": "Neutral",
                "crawled_at": "2026-02-14T18:00:00",
            },
        ]
        original_sqlite = agent_module.sqlite_fallback

        def _patched_sqlite(state):
            return {**state, "raw_news_results": articles}

        with patch.object(agent_module, "sqlite_fallback", side_effect=_patched_sqlite):
            yield articles

    @pytest.fixture()
    def mock_update_preferences(self):
        """Patch update_preferences so mem0.add is not called in unit tests."""
        from chatbot import agent as agent_module

        async def _noop(state):
            return state

        with patch.object(agent_module, "update_preferences", side_effect=_noop):
            yield

    # -----------------------------------------------------------------------
    # Test: cognee returns narrative → direct_response path
    # -----------------------------------------------------------------------
    def test_direct_response_path(
        self,
        mock_cognee_narrative,
        mock_mem0_empty,
        mock_update_preferences,
    ):
        """When cognee returns a narrative, response == narrative and ranked_news == []."""
        from chatbot.agent import agent_graph, ChatbotState

        state: ChatbotState = {
            "query": STOCK_QUERY,
            "user_id": "test-user-direct",
            "user_preferences": {},
            "personalized_query": "",
            "raw_news_results": [],
            "ranked_news": [],
            "response": "",
            "graph_response": None,
        }
        result = asyncio.run(agent_graph.ainvoke(state))

        assert result["response"] == SAMPLE_RESPONSE
        assert result["ranked_news"] == []

    # -----------------------------------------------------------------------
    # Test: cognee empty + SQLite has articles → generate_response path
    # -----------------------------------------------------------------------
    def test_sqlite_fallback_path_with_llm_mock(
        self,
        mock_cognee_empty,
        mock_mem0_empty,
        mock_sqlite_articles,
        mock_update_preferences,
    ):
        """SQLite fallback + LLM generate path produces a non-empty response."""
        from chatbot import agent as agent_module
        from chatbot.agent import agent_graph, ChatbotState

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content=SAMPLE_RESPONSE))

        with patch.object(agent_module, "_get_llm", return_value=mock_llm):
            state: ChatbotState = {
                "query": STOCK_QUERY,
                "user_id": "test-user-sqlite",
                "user_preferences": {},
                "personalized_query": "",
                "raw_news_results": [],
                "ranked_news": [],
                "response": "",
                "graph_response": None,
            }
            result = asyncio.run(agent_graph.ainvoke(state))

        assert result["response"]
        assert len(result["ranked_news"]) > 0
        assert result["ranked_news"][0]["title"]

    # -----------------------------------------------------------------------
    # Test: personalized_query contains topics from stored memory
    # -----------------------------------------------------------------------
    def test_personalized_query_enriched_from_memory(
        self,
        mock_cognee_empty,
        mock_mem0_with_memory,
        mock_update_preferences,
    ):
        """When mem0 returns topics, personalized_query includes them."""
        from chatbot import agent as agent_module
        from chatbot.agent import retrieve_and_query, ChatbotState

        # Run only the retrieve_and_query node
        with patch.object(
            agent_module, "_run_cognee_search", new=AsyncMock(return_value=([], None))
        ):
            state: ChatbotState = {
                "query": STOCK_QUERY,
                "user_id": "test-user-enrich",
                "user_preferences": {},
                "personalized_query": "",
                "raw_news_results": [],
                "ranked_news": [],
                "response": "",
                "graph_response": None,
            }
            result_state = asyncio.run(retrieve_and_query(state))

        assert "thị trường chứng khoán" in result_state["personalized_query"].lower()


# ---------------------------------------------------------------------------
# Slow / real integration tests — require actual LLM API keys
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestMem0RealRoundTrip:
    """
    Real mem0 add → search round-trip.

    Prerequisites:
      - OPENAI_API_KEY or GEMINI_API_KEY set in environment / .env
      - pip install mem0ai chromadb

    Skip automatically if no API key is configured.
    """

    @pytest.fixture(autouse=True)
    def _skip_without_key(self):
        from chatbot.config import OPENAI_API_KEY, GEMINI_API_KEY
        if not OPENAI_API_KEY and not GEMINI_API_KEY:
            pytest.skip("No LLM API key configured — skipping real mem0 test")

    @pytest.fixture()
    def tmp_mem0(self, tmp_path):
        """Provide a temporary mem0 Memory instance isolated from production data."""
        config = _make_temp_mem0_config(str(tmp_path))
        from mem0 import Memory
        return Memory.from_config(config)

    def test_add_and_retrieve_stock_market_query(self, tmp_mem0):
        """
        Adds the stock market conversation to mem0 then searches for it.
        The retrieved memories must contain the stored interaction.
        """
        user_id = f"integration_test_{uuid.uuid4().hex[:8]}"

        # 1. Add interaction
        tmp_mem0.add(
            messages=[
                {"role": "user", "content": STOCK_QUERY},
                {"role": "assistant", "content": SAMPLE_RESPONSE},
            ],
            user_id=user_id,
        )

        # 2. Search
        results = tmp_mem0.search(query=STOCK_QUERY, user_id=user_id, limit=5)
        data = results.get("results", results) if isinstance(results, dict) else results

        assert data, "mem0.search() returned empty results after add()"
        memory_texts = [m.get("memory", "") for m in data if isinstance(m, dict)]
        assert any(memory_texts), "No non-empty memory entries found"

        # At least one memory should be semantically related to stock market
        combined = " ".join(memory_texts).lower()
        # Check for either Vietnamese or English keywords that mem0 may have extracted
        stock_keywords = ["chứng khoán", "thị trường", "vn-index", "stock", "market", "bullish"]
        assert any(kw in combined for kw in stock_keywords), (
            f"Expected stock-related keyword in memories, got: {memory_texts}"
        )

    def test_add_twice_no_duplicate(self, tmp_mem0):
        """
        Adding the same query twice should not create duplicate raw memories.
        mem0 deduplicates by semantic similarity.
        """
        user_id = f"integration_test_dedup_{uuid.uuid4().hex[:8]}"

        for _ in range(2):
            tmp_mem0.add(
                messages=[
                    {"role": "user", "content": STOCK_QUERY},
                    {"role": "assistant", "content": SAMPLE_RESPONSE},
                ],
                user_id=user_id,
            )

        results = tmp_mem0.search(query=STOCK_QUERY, user_id=user_id, limit=10)
        data = results.get("results", results) if isinstance(results, dict) else results

        # mem0 should collapse duplicates — expect ≤ 3 memories
        assert len(data) <= 3, (
            f"Expected mem0 to deduplicate, got {len(data)} memories: {data}"
        )

    def test_run_mem0_search_helper_with_real_memory(self, tmp_mem0):
        """
        Verifies _run_mem0_search returns populated raw_memories after a real add.
        """
        from chatbot import agent as agent_module
        from chatbot.utils import parse_mem0_results

        user_id = f"integration_test_helper_{uuid.uuid4().hex[:8]}"

        # Add via real mem0
        tmp_mem0.add(
            messages=[
                {"role": "user", "content": STOCK_QUERY},
                {"role": "assistant", "content": SAMPLE_RESPONSE},
            ],
            user_id=user_id,
        )

        # Patch _get_memory to return our isolated test instance
        with patch.object(agent_module, "_get_memory", return_value=tmp_mem0):
            result = asyncio.run(
                agent_module._run_mem0_search(STOCK_QUERY, user_id)
            )

        # raw_memories must be non-empty after store
        assert result["raw_memories"], (
            "_run_mem0_search returned empty raw_memories despite stored memory"
        )

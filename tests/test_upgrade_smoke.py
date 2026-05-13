"""Smoke tests for tradingagents — runs without network or API keys.

Regression net for the upstream port. Each phase must keep these passing.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
os.environ.setdefault("GOOGLE_API_KEY", "test-dummy")


def test_default_config_loads():
    from tradingagents.default_config import DEFAULT_CONFIG

    assert "llm_provider" in DEFAULT_CONFIG
    assert "data_vendors" in DEFAULT_CONFIG
    assert "trend_news_api_url" in DEFAULT_CONFIG, "VN customization must be preserved"


def test_llm_factory_dispatches_known_providers():
    from tradingagents.llm_clients import create_llm_client

    for provider in ("openai", "anthropic", "google"):
        client = create_llm_client(provider=provider, model="dummy-model")
        assert client is not None


def test_dataflows_interface_imports():
    from tradingagents.dataflows import interface  # noqa: F401


def test_vn_market_modules_present():
    from tradingagents.dataflows import vnstock_api  # noqa: F401
    from tradingagents.dataflows import trend_news_api  # noqa: F401


def test_local_risk_manager_present():
    from tradingagents.agents.managers import risk_manager  # noqa: F401


def test_analyst_runner_present():
    from tradingagents.agents.utils import analyst_runner  # noqa: F401


def test_trading_graph_constructs():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "anthropic"
    config["deep_think_llm"] = "claude-3-haiku-20240307"
    config["quick_think_llm"] = "claude-3-haiku-20240307"

    ta = TradingAgentsGraph(debug=False, config=config)
    assert ta.graph is not None
    assert ta.bull_memory is not None
    assert ta.bear_memory is not None
    assert ta.trader_memory is not None


def test_graph_all_analysts_select():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "anthropic"
    config["deep_think_llm"] = "claude-3-haiku-20240307"
    config["quick_think_llm"] = "claude-3-haiku-20240307"

    ta = TradingAgentsGraph(
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config=config,
    )
    assert ta.graph is not None

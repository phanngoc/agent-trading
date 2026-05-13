# TradingAgents Upgrade Plan — Sync with TauricResearch v0.2.5

**Source of truth:** `git rev-parse upstream-v0.2.5` → upstream/main at the time this plan was written.

**Strategy:** Hard-fork has no shared history — this is a **port/cherry-pick** exercise, not a git merge. We selectively adopt upstream features while preserving VN-market customizations (`vnstock_api.py`, `trend_news_api.py`, `risk_manager`, `analyst_runner`).

## Locked decisions

| # | Decision | Choice |
|---|---|---|
| 1 | Extra LLM providers | Ollama + OpenRouter only |
| 2 | Social media for VN tickers | US-only; VN stays on trend_news |
| 3 | Graph topology | Option B — keep local ReAct loops, port what plugs in |
| 4 | Risk vs Portfolio manager naming | Keep `risk_manager` |
| 5 | Memory strategy | Option B — keep BM25, port outcome resolution + checkpointer |

## Phases

0. **Prep** — branch, tag upstream-v0.2.5, plan doc, smoke test
1. **Low-risk infra** — schemas, env overlay, capabilities, model_catalog, rating, structured
2. **LLM providers** — factory dispatch, Ollama, OpenRouter, upgraded openai_client
3. **Sentiment analyst** — sentiment_analyst.py, reddit.py, stocktwits.py, interface wiring
4. **Structured output** — adopt Phase 1 schemas in research_manager, trader, analysts
5. **Graph topology** — message-clear nodes, conditional edges (keep ReAct loops)
6. **Memory + checkpointer** — keep BM25 + port outcome resolution + SQLite checkpointer
7. **Config polish** — i18n, benchmark_map (VN-Index), global_news config
8. **Top-level cleanup** — pyproject version, deps, main.py env-var wiring, docs

Each phase ships in its own branch off `main`: `upgrade/phase-<n>-<slug>`.

## Local invariants to preserve

- `tradingagents/dataflows/vnstock_api.py` — VN stock data provider
- `tradingagents/dataflows/trend_news_api.py` — VN trend-news source
- `tradingagents/agents/managers/risk_manager.py` — local risk manager (do NOT rename to portfolio_manager)
- `tradingagents/agents/utils/analyst_runner.py` — ReAct loop runner abstraction
- `tradingagents/dataflows/interface.py` `is_vn_ticker()` routing — auto-detect VN tickers and route to vnstock/trend_news
- `trend_news/` subdirectory — entirely separate Vietnamese news system, untouched

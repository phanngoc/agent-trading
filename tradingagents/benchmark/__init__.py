"""Benchmark pipeline — paper-portfolio simulation for evaluating TradingAgents
against baselines (Buy & Hold, SMA crossover, random) on Vietnamese equities.

The package is organized into a few small pieces that compose:

* :mod:`models` — frozen dataclasses (``Decision``, ``Position``, ``Trade``,
  ``Portfolio``) with JSON serialization. The data layer everything else
  reads and writes.
* :mod:`config` — parser for ``benchmarks/config.yaml`` exposing typed
  views over the watchlist, fees, sizing policy, and strategies.
* (Phase 2) ``execution``, ``portfolio``, ``metrics``, ``baselines`` —
  the simulator that turns a stream of decisions into a P&L curve and a
  scorecard.

The package has no LLM dependencies — TradingAgents decisions are parsed
from ``eval_results/`` so the benchmark stays cheap to re-run.
"""

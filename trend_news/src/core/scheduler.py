"""
In-process scheduler that runs the crawl pipeline and Claude sentiment
evaluation alongside the FastAPI server.

Both jobs are blocking (network I/O, subprocess-style work), so we run
them inside `asyncio.run_in_executor(None, ...)` to avoid stalling the
event loop. APScheduler's AsyncIOScheduler dispatches the wrapper.

Job state (last_run_at, last_status, last_error, runs, failures) is held
in memory and exposed via `snapshot()` for the /api/v1/scheduler/status
endpoint. There is intentionally no persistence — the server is stateless
on restart; jobs simply pick up the next interval.
"""

from __future__ import annotations

import asyncio
import os
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

CRAWL_INTERVAL_MIN = int(os.environ.get("TRENDRADAR_CRAWL_INTERVAL_MIN", "30"))
LLM_EVAL_INTERVAL_MIN = int(os.environ.get("TRENDRADAR_LLM_EVAL_INTERVAL_MIN", "60"))
LLM_EVAL_LIMIT = int(os.environ.get("TRENDRADAR_LLM_EVAL_LIMIT", "100"))
LLM_EVAL_DAYS_BACK = int(os.environ.get("TRENDRADAR_LLM_EVAL_DAYS_BACK", "7"))


@dataclass
class JobState:
    name: str
    interval_min: int
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None  # "ok" | "failed" | "skipped"
    last_error: Optional[str] = None
    last_duration_s: Optional[float] = None
    runs: int = 0
    failures: int = 0
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


class TrendRadarScheduler:
    """Wraps APScheduler with status tracking and lazy DB-path injection."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._jobs: Dict[str, JobState] = {}
        self._lock = threading.Lock()
        self._running_jobs: set[str] = set()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._register("crawl",    CRAWL_INTERVAL_MIN,    self._run_crawl)
        self._register("llm_eval", LLM_EVAL_INTERVAL_MIN, self._run_llm_eval)
        self._scheduler.start()
        print(f"[scheduler] started — crawl every {CRAWL_INTERVAL_MIN}m, "
              f"llm_eval every {LLM_EVAL_INTERVAL_MIN}m")

    def shutdown(self) -> None:
        if self._scheduler is None:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:
            pass
        self._scheduler = None
        print("[scheduler] stopped")

    def _register(
        self,
        name: str,
        interval_min: int,
        coro_factory: Callable[[], Awaitable[None]],
    ) -> None:
        self._jobs[name] = JobState(name=name, interval_min=interval_min)
        assert self._scheduler is not None
        self._scheduler.add_job(
            coro_factory,
            trigger=IntervalTrigger(minutes=interval_min),
            id=name,
            name=name,
            max_instances=1,            # never overlap with itself
            coalesce=True,              # if missed, fire only once
            misfire_grace_time=300,
            replace_existing=True,
        )

    # ------------------------------------------------------------------
    # job runners
    # ------------------------------------------------------------------
    async def _run_crawl(self) -> None:
        await self._run_blocking("crawl", self._do_crawl)

    async def _run_llm_eval(self) -> None:
        await self._run_blocking("llm_eval", self._do_llm_eval)

    async def _run_blocking(self, name: str, fn: Callable[[], Dict[str, Any]]) -> None:
        if name in self._running_jobs:
            with self._lock:
                self._jobs[name].last_status = "skipped"
                self._jobs[name].last_error = "previous run still active"
            return
        self._running_jobs.add(name)
        started = datetime.utcnow()
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, fn)
            with self._lock:
                state = self._jobs[name]
                state.last_run_at = started.isoformat() + "Z"
                state.last_status = "ok"
                state.last_error = None
                state.last_duration_s = (datetime.utcnow() - started).total_seconds()
                state.runs += 1
                if isinstance(result, dict):
                    state.extra = result
        except Exception as exc:
            err_text = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            with self._lock:
                state = self._jobs[name]
                state.last_run_at = started.isoformat() + "Z"
                state.last_status = "failed"
                state.last_error = err_text
                state.last_duration_s = (datetime.utcnow() - started).total_seconds()
                state.runs += 1
                state.failures += 1
        finally:
            self._running_jobs.discard(name)

    # ------------------------------------------------------------------
    # job bodies (blocking — invoked inside executor)
    # ------------------------------------------------------------------
    def _do_crawl(self) -> Dict[str, Any]:
        from main import run_crawl_pipeline
        ok = run_crawl_pipeline()
        return {"ok": bool(ok)}

    def _do_llm_eval(self) -> Dict[str, Any]:
        from src.core.claude_client import ClaudeAuthError, ClaudeClient
        from src.core.claude_sentiment import ClaudeSentiment
        try:
            client = ClaudeClient()
        except ClaudeAuthError as e:
            return {"skipped": str(e)}
        scorer = ClaudeSentiment(client=client, db_path=self.db_path)
        summary = scorer.evaluate_high_uncertainty_articles(
            days_back=LLM_EVAL_DAYS_BACK,
            min_uncertainty=0.35,
            limit=LLM_EVAL_LIMIT,
        )
        synced = scorer.sync_llm_feedback_to_learning(min_confidence=0.6)
        return {**summary, "synced_to_feedback": synced}

    # ------------------------------------------------------------------
    # introspection + manual trigger
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            jobs = []
            for state in self._jobs.values():
                next_run = None
                if self._scheduler:
                    job = self._scheduler.get_job(state.name)
                    if job and job.next_run_time:
                        next_run = job.next_run_time.isoformat()
                jobs.append({
                    "name": state.name,
                    "interval_min": state.interval_min,
                    "next_run_at": next_run,
                    "last_run_at": state.last_run_at,
                    "last_status": state.last_status,
                    "last_error": state.last_error,
                    "last_duration_s": state.last_duration_s,
                    "runs": state.runs,
                    "failures": state.failures,
                    "currently_running": state.name in self._running_jobs,
                    "last_result": state.extra,
                })
        return {"running": self._scheduler is not None, "jobs": jobs}

    async def trigger(self, name: str) -> Dict[str, Any]:
        if name not in self._jobs:
            raise KeyError(f"unknown job: {name}")
        runner = {
            "crawl":    self._run_crawl,
            "llm_eval": self._run_llm_eval,
        }[name]
        # fire-and-forget; status visible via snapshot()
        asyncio.create_task(runner())
        return {"triggered": name}

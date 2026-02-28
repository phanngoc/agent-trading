"""
Cognee Multi-Mode Search Benchmark — Developer Tool
====================================================
So sánh chất lượng search của CHUNKS, GRAPH_COMPLETION, RAG_COMPLETION
song song trên cùng một query để benchmark input cho trading agent.

Chạy từ thư mục trend_news/:
    python chatbot/chat-muti.py

Yêu cầu:
    - output/cognee_db/ đã có data (chạy indexer trước)
    - OPENAI_API_KEY hoặc GEMINI_API_KEY trong .env

Commands trong REPL:
    /modes [MODE|all|default]   toggle search modes
    /top_k N                    đặt số kết quả (default: 10)
    /stats                      xem thống kê session
    /save                       lưu JSON ra output/
    /clear                      xóa màn hình
    /quit                       thoát
"""

# ---------------------------------------------------------------------------
# Stdlib
# ---------------------------------------------------------------------------
import asyncio
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup — BEFORE any chatbot.* import
# ---------------------------------------------------------------------------
_CHATBOT_DIR = Path(__file__).parent
_TREND_NEWS_DIR = _CHATBOT_DIR.parent
if str(_TREND_NEWS_DIR) not in sys.path:
    sys.path.insert(0, str(_TREND_NEWS_DIR))

# ---------------------------------------------------------------------------
# Project imports (NO `import cognee` here — must happen after setup_cognee_paths)
# ---------------------------------------------------------------------------
from chatbot.config import (
    setup_cognee_paths,
    COGNEE_LLM_CONFIG,
    COGNEE_EMBEDDING_ENV,
    OUTPUT_DIR,
    DB_PATH,
)
from chatbot.utils import parse_cognee_results

# ---------------------------------------------------------------------------
# Rich
# ---------------------------------------------------------------------------
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_MODES: Dict[str, Dict] = {
    "CHUNKS": {
        "description": "Fast semantic chunk retrieval (vector similarity)",
        "timeout": 15.0,
        "color": "cyan",
        "enabled_default": True,
    },
    "GRAPH_COMPLETION": {
        "description": "LLM synthesis over knowledge graph (slow, holistic)",
        "timeout": 35.0,
        "color": "magenta",
        "enabled_default": True,
    },
    "RAG_COMPLETION": {
        "description": "Hybrid RAG: vector retrieval + LLM generation",
        "timeout": 30.0,
        "color": "green",
        "enabled_default": True,
    },
    "SUMMARIES": {
        "description": "Pre-computed document summaries",
        "timeout": 15.0,
        "color": "yellow",
        "enabled_default": False,
    },
    "CHUNKS_LEXICAL": {
        "description": "BM25 lexical keyword search",
        "timeout": 10.0,
        "color": "blue",
        "enabled_default": False,
    },
    "TRIPLET_COMPLETION": {
        "description": "Knowledge graph triplet-based completion",
        "timeout": 30.0,
        "color": "red",
        "enabled_default": False,
    },
}

DEFAULT_TOP_K = 10
CONSOLE = Console()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkResult:
    """Kết quả của một mode search trên một query."""

    mode: str
    query: str
    top_k: int
    timestamp: str

    latency_ms: float = 0.0
    num_results: int = 0
    raw_output: Any = field(default=None, repr=False)
    parsed_articles: List[Dict] = field(default_factory=list)

    success: bool = False
    error: Optional[str] = None
    timed_out: bool = False

    @property
    def top_result_preview(self) -> str:
        if self.parsed_articles:
            title = self.parsed_articles[0].get("title", "")
            return title[:90] + ("…" if len(title) > 90 else "")
        if self.raw_output and isinstance(self.raw_output, list) and self.raw_output:
            first = str(self.raw_output[0])
            clean = first.replace("\n", " ")[:90]
            return clean + ("…" if len(first) > 90 else "")
        return "(no results)"

    @property
    def status_icon(self) -> str:
        if self.timed_out:
            return "[yellow]TIMEOUT[/yellow]"
        if not self.success:
            return "[red]ERROR[/red]"
        if self.num_results == 0:
            return "[dim]EMPTY[/dim]"
        return "[green]OK[/green]"

    def to_dict(self) -> Dict:
        return {
            "mode": self.mode,
            "query": self.query,
            "top_k": self.top_k,
            "timestamp": self.timestamp,
            "latency_ms": round(self.latency_ms, 1),
            "num_results": self.num_results,
            "parsed_articles": self.parsed_articles,
            "success": self.success,
            "error": self.error,
            "timed_out": self.timed_out,
        }


@dataclass
class SessionStats:
    """Thống kê tổng hợp toàn session."""

    session_id: str = field(
        default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    queries: List[Dict] = field(default_factory=list)
    mode_stats: Dict[str, Dict] = field(default_factory=dict)

    def record_run(self, results: List[BenchmarkResult]) -> None:
        entry = {
            "query": results[0].query if results else "",
            "timestamp": datetime.now().isoformat(),
            "modes": [r.to_dict() for r in results],
        }
        self.queries.append(entry)
        for r in results:
            if r.mode not in self.mode_stats:
                self.mode_stats[r.mode] = {
                    "total_runs": 0,
                    "success_runs": 0,
                    "timeout_runs": 0,
                    "total_latency_ms": 0.0,
                    "total_results": 0,
                }
            s = self.mode_stats[r.mode]
            s["total_runs"] += 1
            if r.timed_out:
                s["timeout_runs"] += 1
            if r.success:
                s["success_runs"] += 1
                s["total_latency_ms"] += r.latency_ms
                s["total_results"] += r.num_results

    def avg_latency(self, mode: str) -> Optional[float]:
        s = self.mode_stats.get(mode, {})
        runs = s.get("success_runs", 0)
        return s["total_latency_ms"] / runs if runs else None

    def success_rate(self, mode: str) -> float:
        s = self.mode_stats.get(mode, {})
        total = s.get("total_runs", 0)
        return s.get("success_runs", 0) / total * 100 if total else 0.0

    def avg_results(self, mode: str) -> float:
        s = self.mode_stats.get(mode, {})
        runs = s.get("success_runs", 0)
        return s.get("total_results", 0) / runs if runs else 0.0

    def to_dict(self) -> Dict:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": datetime.now().isoformat(),
            "total_queries": len(self.queries),
            "mode_stats": self.mode_stats,
            "queries": self.queries,
        }


# ---------------------------------------------------------------------------
# Cognee setup
# ---------------------------------------------------------------------------


def _setup_cognee() -> None:
    """
    Khởi tạo Cognee cho read-only search.
    PHẢI gọi trước bất kỳ `import cognee` nào.

    Pattern giống indexer.py:51-66, nhưng không gọi
    set_graph_database_provider (read-only, không cần).
    """
    setup_cognee_paths()

    for key, value in COGNEE_EMBEDDING_ENV.items():
        os.environ.setdefault(key, value)

    import cognee  # noqa: PLC0415 (deferred by design)

    cognee.config.set_llm_config(COGNEE_LLM_CONFIG)

    db_path = os.environ.get("SYSTEM_ROOT_DIRECTORY", "N/A")
    CONSOLE.print(f"[dim]  DB:[/dim] {db_path}")
    CONSOLE.print(
        f"[dim]  LLM:[/dim] {COGNEE_LLM_CONFIG.get('llm_model')}  "
        f"[dim]Embedding:[/dim] {os.environ.get('EMBEDDING_MODEL', 'N/A')}"
    )


# ---------------------------------------------------------------------------
# Core search
# ---------------------------------------------------------------------------


async def run_search_mode(
    query: str,
    mode: str,
    top_k: int = DEFAULT_TOP_K,
) -> BenchmarkResult:
    """
    Chạy một mode search. Bắt mọi exception — không bao giờ raise.
    Mỗi mode fail độc lập, không ảnh hưởng mode khác.
    """
    import cognee  # noqa: PLC0415
    from cognee.api.v1.search import SearchType  # noqa: PLC0415

    result = BenchmarkResult(
        mode=mode,
        query=query,
        top_k=top_k,
        timestamp=datetime.now().isoformat(),
    )
    timeout = ALL_MODES.get(mode, {}).get("timeout", 30.0)
    t0 = time.perf_counter()

    try:
        search_type = SearchType[mode]
        raw = await asyncio.wait_for(
            cognee.search(query_text=query, query_type=search_type, top_k=top_k),
            timeout=timeout,
        )
        result.latency_ms = (time.perf_counter() - t0) * 1000
        result.raw_output = raw
        result.parsed_articles = parse_cognee_results(raw)
        result.num_results = len(result.parsed_articles)
        result.success = True

    except asyncio.TimeoutError:
        result.latency_ms = (time.perf_counter() - t0) * 1000
        result.timed_out = True
        result.error = f"Timeout after {timeout:.0f}s"

    except KeyError:
        result.latency_ms = (time.perf_counter() - t0) * 1000
        result.error = f"Unknown SearchType: {mode}"

    except Exception as exc:
        result.latency_ms = (time.perf_counter() - t0) * 1000
        result.error = str(exc)[:200]

    return result


async def run_all_modes(
    query: str,
    enabled_modes: List[str],
    top_k: int = DEFAULT_TOP_K,
) -> List[BenchmarkResult]:
    """Chạy tất cả modes SONG SONG. Mỗi mode tự handle exception."""
    tasks = [run_search_mode(query, mode, top_k) for mode in enabled_modes]
    results = await asyncio.gather(*tasks)
    return list(results)


def fetch_indexed_articles(
    limit: int = 20,
    keyword: Optional[str] = None,
    all_articles: bool = False,
    db_path: str = DB_PATH,
) -> Tuple[List[Dict], int, int]:
    """
    Đọc từ SQLite news_articles.

    - all_articles=False (default): chỉ bài đã index vào Cognee (id <= watermark)
    - all_articles=True: tất cả bài trong DB, đánh dấu indexed/pending

    Returns: (articles, total_indexed_count, total_in_db)
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Tổng số bài trong DB
        total_in_db = conn.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0]

        # Lấy watermark từ chatbot_sync
        row = conn.execute(
            "SELECT last_indexed_id, total_indexed FROM chatbot_sync WHERE id=1"
        ).fetchone()
        watermark = row["last_indexed_id"] if row else 0
        total_indexed = row["total_indexed"] if row else 0

        # Build WHERE clause
        conditions = []
        params: List[Any] = []

        if not all_articles and watermark > 0:
            conditions.append("id <= ?")
            params.append(watermark)

        if keyword:
            conditions.append("(title LIKE ? OR source_id LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT id, source_id, title, url, crawled_at, crawl_date,
                   sentiment_score, sentiment_label
            FROM news_articles
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        conn.close()

        articles = []
        for r in rows:
            d = dict(r)
            d["_indexed"] = (watermark > 0 and d["id"] <= watermark)
            articles.append(d)

        return articles, total_indexed, total_in_db

    except Exception as exc:
        return [{"_error": str(exc)}], 0, 0


def display_articles_table(
    articles: List[Dict],
    total_indexed: int,
    total_in_db: int,
    keyword: Optional[str] = None,
    show_all: bool = False,
) -> None:
    """
    Rich Table hiển thị bài viết.
    Columns: # | ID | Idx | Source | Date | Sentiment | Title
    """
    if not articles:
        if keyword:
            CONSOLE.print(
                f"[yellow]Không tìm thấy bài với keyword '[bold]{keyword}[/bold]'.[/yellow]"
            )
        else:
            CONSOLE.print(
                "[yellow]Chưa có bài viết nào.[/yellow]\n"
                "[dim]Chạy:[/dim] python chatbot/indexer.py --test --limit 5"
            )
        return

    if "_error" in articles[0]:
        CONSOLE.print(f"[red]DB error: {articles[0]['_error']}[/red]")
        return

    sentiment_colors = {
        "Bullish": "green",
        "Somewhat-Bullish": "green",
        "Bearish": "red",
        "Somewhat-Bearish": "red",
        "Neutral": "white",
    }

    pending = total_in_db - total_indexed
    idx_color = "green" if total_indexed > 0 else "yellow"
    pending_str = (
        f"  [yellow]pending={pending}[/yellow]" if pending > 0 else ""
    )
    title_str = (
        f"[bold]Articles[/bold]  "
        f"[dim]in_db={total_in_db}  [{idx_color}]indexed={total_indexed}[/{idx_color}]{pending_str}"
        f"  showing={len(articles)}"
        + (f"  filter='{keyword}'" if keyword else "")
        + "[/dim]"
    )

    table = Table(
        title=title_str,
        box=box.ROUNDED,
        border_style="bright_blue",
        header_style="bold white on dark_blue",
        expand=True,
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim", min_width=3, no_wrap=True)
    table.add_column("ID", justify="right", style="dim", min_width=5, no_wrap=True)
    if show_all:
        table.add_column("Idx", justify="center", min_width=3, no_wrap=True)
    table.add_column("Source", min_width=8, no_wrap=True)
    table.add_column("Date", justify="center", min_width=10, no_wrap=True)
    table.add_column("Sent", justify="center", min_width=10, no_wrap=True)
    table.add_column("Title")

    for i, art in enumerate(articles, 1):
        sentiment = art.get("sentiment_label") or "Neutral"
        score = art.get("sentiment_score")
        s_color = sentiment_colors.get(sentiment, "white")
        s_abbrev = sentiment[:3].upper() if sentiment else "---"
        s_str = (
            f"[{s_color}]{s_abbrev}({score:+.2f})[/{s_color}]"
            if score is not None
            else f"[{s_color}]{s_abbrev}[/{s_color}]"
        )

        date = (art.get("crawl_date") or art.get("crawled_at") or "")[:10]
        source = escape(art.get("source_id", "")[:12])
        title = escape(art.get("title", ""))
        is_indexed = art.get("_indexed", False)

        row_cells: List[Any] = [str(i), str(art.get("id", ""))]
        if show_all:
            row_cells.append("[green]✓[/green]" if is_indexed else "[dim]·[/dim]")
        row_cells += [source, date, s_str, title]

        style = "" if is_indexed else "dim"
        table.add_row(*row_cells, style=style)

    CONSOLE.print()
    CONSOLE.print(table)
    if pending > 0:
        CONSOLE.print(
            f"[dim]Tip: chạy [/dim][yellow]python chatbot/indexer.py[/yellow]"
            f"[dim] để index thêm {pending} bài chưa được index vào Cognee[/dim]"
        )
    else:
        CONSOLE.print(
            "[dim]Tip: dùng từ trong tiêu đề làm query để test search quality[/dim]"
        )


def _extract_graph_narrative(raw_output: Any) -> Optional[str]:
    """
    GRAPH_COMPLETION trả về List[dict] với key 'search_result': List[str].
    parse_cognee_results() sẽ trả về 0 articles cho narrative text.
    Helper này lấy raw narrative để hiển thị trong detail panel.
    """
    if not raw_output or not isinstance(raw_output, list):
        return None
    first = raw_output[0]
    if isinstance(first, dict):
        parts = first.get("search_result", [])
        if parts and isinstance(parts[0], str) and len(parts[0]) > 20:
            return "\n\n".join(str(p) for p in parts[:5])
    elif isinstance(first, str) and len(first) > 20:
        return first
    return None


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------


def display_comparison_table(results: List[BenchmarkResult]) -> None:
    """
    Rich Table: Mode | Status | Latency | Count | Top Result Preview
    """
    table = Table(
        title="[bold]Search Mode Comparison[/bold]",
        box=box.ROUNDED,
        border_style="bright_blue",
        header_style="bold white on dark_blue",
        expand=True,
    )
    table.add_column("Mode", style="bold", min_width=18, no_wrap=True)
    table.add_column("Status", justify="center", min_width=9)
    table.add_column("Latency", justify="right", min_width=10)
    table.add_column("n", justify="center", min_width=4)
    table.add_column("Top Result Preview")

    for r in results:
        color = ALL_MODES.get(r.mode, {}).get("color", "white")

        # Latency
        if r.timed_out:
            lat = f"[yellow]>{ALL_MODES.get(r.mode, {}).get('timeout', 30):.0f}s[/yellow]"
        elif not r.success:
            lat = "[red dim]—[/red dim]"
        elif r.latency_ms < 5_000:
            lat = f"[green]{r.latency_ms:.0f}ms[/green]"
        elif r.latency_ms < 15_000:
            lat = f"[yellow]{r.latency_ms / 1000:.1f}s[/yellow]"
        else:
            lat = f"[red]{r.latency_ms / 1000:.1f}s[/red]"

        # Preview
        if r.error and not r.timed_out:
            preview = f"[red dim]{escape(r.error[:100])}[/red dim]"
        else:
            preview = escape(r.top_result_preview)

        table.add_row(
            f"[{color}]{r.mode}[/{color}]",
            r.status_icon,
            lat,
            str(r.num_results) if r.success else "—",
            preview,
        )

    CONSOLE.print()
    CONSOLE.print(table)


def display_mode_detail(result: BenchmarkResult) -> None:
    """
    Rich Panel chi tiết một mode.
    - Parsed articles: title, source, date, sentiment, URL
    - Nếu 0 articles (GRAPH_COMPLETION narrative): raw text
    """
    color = ALL_MODES.get(result.mode, {}).get("color", "white")
    content = Text()

    if not result.success:
        content.append("ERROR: ", style="bold red")
        content.append(result.error or "Unknown", style="red")
        if result.timed_out:
            content.append(
                f"\n\nTimed out after {ALL_MODES.get(result.mode, {}).get('timeout', 30):.0f}s",
                style="yellow",
            )
    elif result.num_results == 0:
        narrative = _extract_graph_narrative(result.raw_output)
        if narrative:
            content.append("[Graph Narrative]\n\n", style="dim italic")
            content.append(narrative)
        else:
            content.append("No results.", style="dim italic")
    else:
        sentiment_colors = {
            "Bullish": "green",
            "Somewhat-Bullish": "green",
            "Bearish": "red",
            "Somewhat-Bearish": "red",
            "Neutral": "white",
        }
        for i, art in enumerate(result.parsed_articles, 1):
            title = art.get("title", "(no title)")
            source = art.get("source_id", "")
            url = art.get("url", "")
            sentiment = art.get("sentiment_label", "")
            score = art.get("sentiment_score")
            date = (art.get("crawled_at") or "")[:10]

            content.append(f"\n[{i}] ", style=f"bold {color}")
            content.append(title, style="bold white")
            meta_parts = [p for p in [source, date] if p]
            if meta_parts:
                content.append(f"\n    {' | '.join(meta_parts)}", style="dim")
            if sentiment:
                sc = f" ({score:+.2f})" if score is not None else ""
                content.append(
                    f"  {sentiment}{sc}",
                    style=sentiment_colors.get(sentiment, "white"),
                )
            if url:
                content.append(f"\n    {url[:100]}", style="blue underline")
            content.append("\n")

    title_str = (
        f"[bold {color}]{result.mode}[/bold {color}]  "
        f"[dim]{result.latency_ms:.0f}ms | {result.num_results} results[/dim]"
    )
    CONSOLE.print(Panel(content, title=title_str, border_style=color, padding=(1, 2)))


def display_stats_summary(session: SessionStats) -> None:
    """Aggregate stats: Mode | Runs | Success% | Avg Latency | Timeouts | Avg Results"""
    if not session.queries:
        CONSOLE.print("[dim]No queries in this session yet.[/dim]")
        return

    CONSOLE.print(Rule("[bold]Session Statistics[/bold]", style="bright_blue"))
    CONSOLE.print(
        f"[dim]Session:[/dim] {session.session_id}  "
        f"[dim]Queries:[/dim] {len(session.queries)}"
    )

    table = Table(box=box.SIMPLE_HEAVY, border_style="blue", header_style="bold")
    table.add_column("Mode", style="bold")
    table.add_column("Runs", justify="center")
    table.add_column("Success %", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Timeouts", justify="center")
    table.add_column("Avg Results", justify="right")

    for mode_name, stats in session.mode_stats.items():
        color = ALL_MODES.get(mode_name, {}).get("color", "white")
        runs = stats["total_runs"]
        pct = session.success_rate(mode_name)
        avg_lat = session.avg_latency(mode_name)
        timeouts = stats.get("timeout_runs", 0)
        avg_res = session.avg_results(mode_name)

        lat_str = (
            f"{avg_lat:.0f}ms"
            if avg_lat and avg_lat < 5_000
            else (f"{avg_lat / 1000:.1f}s" if avg_lat else "N/A")
        )
        pct_color = "green" if pct >= 80 else ("yellow" if pct >= 50 else "red")

        table.add_row(
            f"[{color}]{mode_name}[/{color}]",
            str(runs),
            f"[{pct_color}]{pct:.0f}%[/{pct_color}]",
            lat_str,
            f"[yellow]{timeouts}[/yellow]" if timeouts else "0",
            f"{avg_res:.1f}",
        )

    CONSOLE.print(table)


# ---------------------------------------------------------------------------
# REPL helpers
# ---------------------------------------------------------------------------


async def async_input(prompt_str: str = "") -> str:
    """Non-blocking input() — runs blocking call in thread pool."""
    loop = asyncio.get_event_loop()
    if prompt_str:
        CONSOLE.print(prompt_str, end="")
    return await loop.run_in_executor(None, input)


def parse_command(user_input: str) -> Tuple[str, List[str]]:
    stripped = user_input.strip()
    if stripped.startswith("/"):
        parts = stripped.split()
        return parts[0].lower(), parts[1:]
    return "query", [stripped]


def handle_modes_command(enabled_modes: List[str], args: List[str]) -> List[str]:
    if not args:
        table = Table(box=box.SIMPLE, header_style="bold")
        table.add_column("Mode")
        table.add_column("Status", justify="center")
        table.add_column("Timeout", justify="right")
        table.add_column("Description")
        for name, cfg in ALL_MODES.items():
            table.add_row(
                f"[{cfg['color']}]{name}[/{cfg['color']}]",
                "[green]ON[/green]" if name in enabled_modes else "[dim]OFF[/dim]",
                f"{cfg['timeout']:.0f}s",
                cfg["description"],
            )
        CONSOLE.print(table)
        return enabled_modes

    arg = args[0].upper()

    if arg == "ALL":
        new = list(ALL_MODES.keys())
        CONSOLE.print(f"[green]Enabled all: {', '.join(new)}[/green]")
        return new
    if arg == "DEFAULT":
        new = [k for k, v in ALL_MODES.items() if v["enabled_default"]]
        CONSOLE.print(f"[green]Reset to defaults: {', '.join(new)}[/green]")
        return new
    if arg in ALL_MODES:
        if arg in enabled_modes:
            new = [m for m in enabled_modes if m != arg]
            CONSOLE.print(f"[yellow]Disabled: {arg}[/yellow]")
        else:
            new = enabled_modes + [arg]
            CONSOLE.print(f"[green]Enabled: {arg}[/green]")
        return new

    CONSOLE.print(f"[red]Unknown mode: {arg}. Options: {', '.join(ALL_MODES)}[/red]")
    return enabled_modes


def save_session(session: SessionStats) -> Optional[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"benchmark_{session.session_id}.json"
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        CONSOLE.print(f"[green]Saved →[/green] {out}")
        return out
    except Exception as exc:
        CONSOLE.print(f"[red]Save failed: {exc}[/red]")
        return None


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------


async def repl(session: SessionStats) -> None:
    enabled_modes: List[str] = [k for k, v in ALL_MODES.items() if v["enabled_default"]]
    top_k: int = DEFAULT_TOP_K

    CONSOLE.print(
        Panel(
            "[bold]Commands[/bold]\n"
            "  [bright_green]/articles [N] [keyword][/bright_green]   xem bài viết đã index (default 20)\n"
            "  [cyan]/modes [MODE|all|default][/cyan]    toggle search modes\n"
            "  [cyan]/top_k N[/cyan]                     số kết quả (1-50, default 10)\n"
            "  [cyan]/stats[/cyan]                       thống kê session\n"
            "  [cyan]/save[/cyan]                        lưu JSON ra output/\n"
            "  [cyan]/clear[/cyan]                       xóa màn hình\n"
            "  [cyan]/quit[/cyan]                        thoát\n\n"
            f"[dim]Active modes: {', '.join(enabled_modes)}  |  Top-K: {top_k}[/dim]",
            title="[bold bright_blue]Cognee Multi-Mode Benchmark[/bold bright_blue]",
            border_style="bright_blue",
        )
    )

    while True:
        try:
            raw = await async_input("\n[bold cyan]Query>[/bold cyan] ")
        except (EOFError, KeyboardInterrupt):
            CONSOLE.print("\n[yellow]Interrupted — /quit to exit.[/yellow]")
            continue

        raw = raw.strip()
        if not raw:
            continue

        cmd, args = parse_command(raw)

        if cmd in ("/quit", "/q"):
            CONSOLE.print("[yellow]Saving session before exit…[/yellow]")
            save_session(session)
            break

        elif cmd == "/modes":
            enabled_modes = handle_modes_command(enabled_modes, args)

        elif cmd == "/top_k":
            if args and args[0].isdigit():
                top_k = max(1, min(50, int(args[0])))
                CONSOLE.print(f"[green]top_k = {top_k}[/green]")
            else:
                CONSOLE.print(f"[red]Usage: /top_k N (1-50). Current: {top_k}[/red]")

        elif cmd == "/stats":
            display_stats_summary(session)

        elif cmd == "/save":
            save_session(session)

        elif cmd == "/articles":
            # /articles [N] [keyword...]   — chỉ indexed
            # /articles all [N] [keyword] — tất cả bài trong DB
            show_all = False
            limit = 20
            keyword = None
            remaining = args[:]
            if remaining and remaining[0].lower() == "all":
                show_all = True
                remaining = remaining[1:]
            if remaining and remaining[0].isdigit():
                limit = max(1, min(200, int(remaining[0])))
                remaining = remaining[1:]
            if remaining:
                keyword = " ".join(remaining)
            arts, total_idx, total_db = fetch_indexed_articles(
                limit=limit, keyword=keyword, all_articles=show_all
            )
            display_articles_table(
                arts, total_idx, total_db, keyword=keyword, show_all=show_all
            )

        elif cmd == "/clear":
            CONSOLE.clear()

        elif cmd == "query":
            query_text = args[0] if args else ""
            if not query_text:
                continue
            if not enabled_modes:
                CONSOLE.print(
                    "[red]No modes enabled. Use /modes to enable some.[/red]"
                )
                continue

            CONSOLE.print(
                f"\n[dim]Running {len(enabled_modes)} mode(s) in parallel: "
                f"{', '.join(enabled_modes)}[/dim]"
            )

            with CONSOLE.status("[bold green]Searching…[/bold green]", spinner="dots"):
                results = await run_all_modes(query_text, enabled_modes, top_k)

            session.record_run(results)
            display_comparison_table(results)

            # Detail view prompt
            successful = [r for r in results if r.success or r.timed_out]
            if successful:
                # Build shortcut map: first letter → mode (prefer longer modes first)
                shortcuts: Dict[str, str] = {}
                for r in results:
                    key = r.mode[0]
                    if key not in shortcuts:
                        shortcuts[key] = r.mode

                hint_parts = [
                    f"[{ALL_MODES.get(r.mode, {}).get('color', 'white')}]"
                    f"[{r.mode[0]}]{escape(r.mode[1:])}[/]"
                    for r in results
                ]
                hint = "  ".join(hint_parts) + "  [dim][N]one[/dim]"
                CONSOLE.print(f"Detail view? {hint}")

                try:
                    detail_raw = await async_input("[dim]> [/dim]")
                except (EOFError, KeyboardInterrupt):
                    continue

                detail_raw = detail_raw.strip().upper()
                if detail_raw in ("N", ""):
                    pass
                else:
                    # Try shortcut letter first, then full mode name
                    chosen = shortcuts.get(detail_raw) or next(
                        (r.mode for r in results if r.mode.upper() == detail_raw),
                        None,
                    )
                    if chosen:
                        target = next(
                            (r for r in results if r.mode == chosen), None
                        )
                        if target:
                            display_mode_detail(target)
                    else:
                        CONSOLE.print(f"[dim]No match for '{detail_raw}'.[/dim]")

        else:
            CONSOLE.print(f"[red]Unknown command: {cmd}. Type /quit to exit.[/red]")


async def main() -> None:
    CONSOLE.print(Rule("[bold]Cognee Benchmark Tool — Startup[/bold]"))

    CONSOLE.print("[dim]Initializing Cognee…[/dim]")
    try:
        _setup_cognee()
        CONSOLE.print("[green]Cognee ready.[/green]")
    except Exception as exc:
        CONSOLE.print(f"[red bold]Cognee init failed:[/red bold] {exc}")
        CONSOLE.print(
            "[yellow]Check output/cognee_db/ exists and .env has a valid API key.[/yellow]"
        )
        return

    session = SessionStats()
    CONSOLE.print(f"[dim]Session: {session.session_id}[/dim]")

    try:
        await repl(session)
    except KeyboardInterrupt:
        CONSOLE.print("\n[yellow]Keyboard interrupt.[/yellow]")
    finally:
        if session.queries:
            CONSOLE.print("[dim]Auto-saving…[/dim]")
            save_session(session)
        CONSOLE.print("[green]Goodbye.[/green]")


if __name__ == "__main__":
    asyncio.run(main())

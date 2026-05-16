"""F319.com per-ticker thread fetcher.

F319 is Vietnam's largest retail trader forum — the closest VN
equivalent to Reddit's r/wallstreetbets / r/stocks in role: high-volume
ticker chatter from retail F0 investors, with thread titles, reply
counts, and view counts that serve as a buzz proxy.

F319 runs on XenForo 1.x (markup is ``<li class="discussionListItem">``
rather than the XF2 ``.structItem``). We scrape the main stock
discussion subforum (``thi-truong-chung-khoan.3``) and filter thread
titles for the requested ticker as a standalone token.

Matches the contract used by :mod:`tradingagents.dataflows.stocktwits`
and :mod:`tradingagents.dataflows.reddit` — returns a single formatted
string, never raises, and emits a clear ``<unavailable>`` placeholder
when the source is unreachable so the LLM prompt always sees something
predictable.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Main stock-discussion subforum (XenForo 1 ID 3). XF1 sorts by
# last-post-date by default. Each page lists ~30 threads, so the
# default 3-page scan covers ~90 most-active threads — enough that
# popular tickers (VN30, HNX30) almost always have at least one match.
_FORUM_URL_TEMPLATE = "https://f319.com/forums/thi-truong-chung-khoan.3/page-{page}"
_DEFAULT_PAGES = 3
# A normal-browser UA — F319's CDN tier blocks bare library UAs.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Match each thread row. We anchor on the ``<li id="thread-NNN"`` shape
# rather than the class list because XF1 appends sticky/visible/state
# modifiers to the class. ``[^>]*?`` keeps the regex non-greedy until
# we hit the closing ``</li>`` of the same row.
_ROW_RE = re.compile(
    r'<li id="thread-(?P<tid>\d+)"[^>]*class="discussionListItem[^"]*"[^>]*>'
    r'(?P<body>.*?)</li>',
    re.DOTALL,
)
_TITLE_RE = re.compile(
    r'<h3 class="title">.*?<a href="(?P<href>[^"]+)"[^>]*>'
    r'(?P<title>.*?)</a>',
    re.DOTALL,
)
# Last-post date is in an ``<abbr class="DateTime" data-datestring="DD/MM/YYYY"``.
_DATE_RE = re.compile(r'data-datestring="(?P<dt>[^"]+)"')
# XF1 stats: dl.major dd = replies, dl.minor dd = views.
_MAJOR_RE = re.compile(r'<dl class="major"><dd>(?P<v>.*?)</dd></dl>', re.DOTALL)
_MINOR_RE = re.compile(r'<dl class="minor"><dd>(?P<v>.*?)</dd></dl>', re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _strip_tags(html: str) -> str:
    """Reduce a fragment of HTML to plain text, collapsing whitespace."""
    return re.sub(r"\s+", " ", _TAG_STRIP_RE.sub("", html)).strip()


def _to_int(raw: str) -> int:
    """Parse a XF1 count like ``"1.484.947"`` or ``"952"`` to int."""
    cleaned = re.sub(r"[^\d]", "", raw or "")
    return int(cleaned) if cleaned else 0


def _ticker_in_title(ticker: str, title: str) -> bool:
    """True if ``ticker`` appears in ``title`` as a standalone token.

    Avoids false positives like ``ACB`` matching inside ``ACBS``.
    """
    pattern = rf"(?<![A-Za-z0-9]){re.escape(ticker.upper())}(?![A-Za-z0-9])"
    return re.search(pattern, title.upper()) is not None


def _normalize_ticker(ticker: str) -> str:
    """Drop the ``.VN`` exchange suffix — F319 uses the bare symbol."""
    return ticker.split(".")[0].upper()


def _fetch_subforum_page(page: int, timeout: float) -> Optional[str]:
    url = _FORUM_URL_TEMPLATE.format(page=page)
    req = Request(url, headers={"User-Agent": _UA, "Accept": "text/html"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("F319 fetch page %s failed: %s", page, exc)
        return None
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — keep the fetcher robust
        logger.warning("F319 decode page %s failed: %s", page, exc)
        return None


def fetch_f319_posts(
    ticker: str,
    limit: int = 20,
    pages: int = _DEFAULT_PAGES,
    timeout: float = 12.0,
) -> str:
    """Fetch recent F319 threads mentioning ``ticker`` as a plaintext block.

    Scans the first ``pages`` pages of the stock subforum (~30 threads
    per page), filters by ticker mention in the title, and renders up
    to ``limit`` rows with reply / view counts so the LLM can weight
    by engagement.
    """
    symbol = _normalize_ticker(ticker)
    rows: List[str] = []
    seen_threads: set = set()
    total_replies = 0
    total_views = 0
    scanned_threads = 0
    any_page_loaded = False

    for page in range(1, pages + 1):
        html = _fetch_subforum_page(page, timeout)
        if not html:
            continue
        any_page_loaded = True
        for match in _ROW_RE.finditer(html):
            scanned_threads += 1
            thread_id = match.group("tid")
            if thread_id in seen_threads:
                continue
            seen_threads.add(thread_id)

            row_html = match.group("body")
            title_match = _TITLE_RE.search(row_html)
            if not title_match:
                continue
            title = _strip_tags(title_match.group("title"))
            if not _ticker_in_title(symbol, title):
                continue

            href = title_match.group("href")
            url = href if href.startswith("http") else f"https://f319.com/{href.lstrip('/')}"

            date_match = _DATE_RE.search(row_html)
            when = date_match.group("dt") if date_match else "?"

            replies_match = _MAJOR_RE.search(row_html)
            views_match = _MINOR_RE.search(row_html)
            replies = _to_int(_strip_tags(replies_match.group("v"))) if replies_match else 0
            views = _to_int(_strip_tags(views_match.group("v"))) if views_match else 0

            total_replies += replies
            total_views += views
            rows.append(
                f"  [{when} · {replies:>4} replies · {views:>7,} views] "
                f"{title}  ({url})"
            )
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break

    if not any_page_loaded:
        return f"<F319 unavailable for ${symbol}>"

    if not rows:
        return (
            f"<no F319 threads found mentioning ${symbol} across "
            f"{scanned_threads} most-active stock-subforum threads>"
        )

    header = (
        f"F319.com — {len(rows)} recent threads mentioning ${symbol} "
        f"(scanned {scanned_threads} active threads; matches total "
        f"{total_replies:,} replies, {total_views:,} views):"
    )
    return header + "\n" + "\n".join(rows)

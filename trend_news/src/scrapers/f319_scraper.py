"""
F319.com forum scraper.

Scrapes the latest hot threads from f319.com — Vietnam's largest retail
trader forum. Unlike the other ``trend_news`` scrapers, the source here
is a *discussion forum* rather than a publisher: each "article" is a
thread title with reply / view counts that serve as a buzz proxy.

F319 runs on XenForo 1.x, where thread rows are
``<li class="discussionListItem">`` (not the XF2 ``.structItem``
markup found in newer forums). The main stock discussion subforum is
``thi-truong-chung-khoan.3`` — id 3, not the lower-traffic 10 used by
the older site map. Each row exposes the thread title, last-post
date, reply count, and view count.

The thread title is treated as the "article title" and the full thread
URL as the "article url" so downstream processors (sentiment scoring,
ticker mapping) can treat it uniformly with news articles.
"""

import re
from typing import Dict, List

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


_THREAD_URL_RE = re.compile(r"/?threads/[^/]+\.\d+/?$")


class F319Scraper(BaseScraper):
    """Scraper for f319.com latest threads in the stock-market subforum."""

    BASE_URL = "https://f319.com"
    # XF1 sorts the listing by last-post-date by default, so we don't
    # need a query string. Subforum id 3 = "Thị trường chứng khoán",
    # which carries the bulk of ticker-specific discussion.
    FORUM_PATH = "/forums/thi-truong-chung-khoan.3/"

    def __init__(self):
        super().__init__(
            source_id="f319",
            source_name="F319 — Diễn đàn chứng khoán",
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}{self.FORUM_PATH}"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse thread rows from a XenForo 1.x subforum listing page."""
        articles: List[Dict] = []
        seen_urls = set()

        # Each thread row: <li id="thread-NNN" class="discussionListItem ...">
        rows = soup.select("li.discussionListItem")
        for row in rows:
            title_el = row.select_one("h3.title a")
            if not title_el:
                continue

            title = self._clean_title(title_el.get_text())
            href = str(title_el.get("href", "") or "")
            if not title or len(title) < 8:
                continue
            if not _THREAD_URL_RE.search(href.split("?")[0]):
                continue

            url = self._normalize_url(href, self.BASE_URL)
            # Strip pagination suffix so duplicate threads collapse.
            url = re.sub(r"/page-\d+/?$", "/", url)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": "",
            })

        return articles

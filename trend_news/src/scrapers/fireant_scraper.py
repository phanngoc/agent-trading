"""
Fireant.vn social-feed scraper.

Fireant is a Vietnamese stock-trading social network where retail and
semi-pro investors post short notes ("status updates") indexed by
ticker — functionally the closest VN equivalent to StockTwits. The
public web app is a React SPA, so HTML scraping of the rendered page
returns an empty shell. We therefore hit the underlying JSON API
directly.

Endpoint shape (reverse-engineered from the public web client):

    GET https://restv2.fireant.vn/posts?type=0&offset=0&limit=20

That returns the global "wall" feed. Per-symbol queries
(``&symbol=VNM``) work the same way and are used by the per-ticker
fetcher in ``tradingagents/dataflows/fireant.py``; this scraper only
needs the global feed to feed the ``trend_news`` aggregator.

This class overrides :py:meth:`BaseScraper.fetch` because the base
implementation assumes an HTML response — we cannot parse JSON via
BeautifulSoup. ``parse_articles`` is kept as a no-op stub to satisfy
the abstract interface.
"""

import json
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


# Conservative caps — Fireant's posts can be very long, and very-old
# posts add little signal once we already have the recent 30.
_POST_LIMIT = 30
_BODY_TRUNCATE = 280

# Public web client uses these endpoints. We try them in order and stop
# at the first 2xx JSON response that contains a posts array.
_ENDPOINT_CANDIDATES = (
    "https://restv2.fireant.vn/posts?type=0&offset=0&limit={limit}",
    "https://restv2.fireant.vn/posts?offset=0&limit={limit}",
)


class FireantScraper(BaseScraper):
    """Scraper for the Fireant.vn public posts wall.

    Each Fireant post is mapped to one ``article`` dict whose ``title``
    is a truncated first line of the post body and whose ``url`` is the
    post's permalink. Downstream processors (sentiment scorer, ticker
    mapper) then treat it like any other article.
    """

    def __init__(self):
        super().__init__(
            source_id="fireant",
            source_name="Fireant — Mạng xã hội đầu tư",
        )
        # Override the default Accept so the API does not return HTML.
        self.headers = {
            **self.headers,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://fireant.vn",
            "Referer": "https://fireant.vn/",
        }

    def get_url(self) -> str:
        # The first candidate is the canonical endpoint; the base class
        # never uses this directly since we override ``fetch``.
        return _ENDPOINT_CANDIDATES[0].format(limit=_POST_LIMIT)

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:  # noqa: D401
        """Unused — see :py:meth:`fetch`. Required by the abstract base."""
        return []

    def fetch(self, timeout: int = 15) -> Optional[Dict]:
        """Fetch the Fireant global wall and return article-shaped rows.

        Tries each candidate endpoint; the first one returning a JSON
        array of posts wins. Returns ``None`` if every candidate fails
        or no posts could be parsed — matching the base class contract.
        """
        last_error: Optional[str] = None
        for url_template in _ENDPOINT_CANDIDATES:
            url = url_template.format(limit=_POST_LIMIT)
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=timeout,
                    allow_redirects=True,
                )
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                    continue

                payload = response.json()
            except requests.exceptions.Timeout:
                last_error = f"timeout after {timeout}s"
                continue
            except requests.exceptions.ConnectionError as exc:
                last_error = f"connection error: {exc}"
                continue
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = f"invalid JSON: {exc}"
                continue
            except Exception as exc:  # noqa: BLE001 — keep scraper robust
                last_error = f"unexpected: {exc}"
                continue

            articles = self._parse_posts(payload)
            if articles:
                return {
                    "status": "success",
                    "id": self.source_id,
                    "items": articles,
                }

        print(f"  ✗ {self.source_name}: {last_error or 'no posts returned'}")
        return None

    # ------------------------------------------------------------------
    # JSON parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_posts(payload) -> List[Dict]:
        """Normalize the Fireant JSON shape into article dicts.

        Fireant has tweaked the response envelope several times. We
        accept the two known shapes:

        * Top-level list of post objects.
        * ``{"posts": [...]}`` envelope.
        """
        if isinstance(payload, dict):
            posts = payload.get("posts") or payload.get("data") or []
        elif isinstance(payload, list):
            posts = payload
        else:
            return []

        articles: List[Dict] = []
        seen_urls = set()
        for post in posts:
            if not isinstance(post, dict):
                continue

            post_id = post.get("postID") or post.get("id") or post.get("postId")
            body = (post.get("content") or post.get("body") or "").strip()
            if not body:
                continue

            # First non-empty line, truncated, becomes the "title".
            first_line = next(
                (ln.strip() for ln in body.splitlines() if ln.strip()),
                body[:_BODY_TRUNCATE],
            )
            title = first_line[:_BODY_TRUNCATE]

            url = post.get("link") or post.get("url")
            if not url and post_id:
                url = f"https://fireant.vn/posts/{post_id}"
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": "",
            })

        return articles

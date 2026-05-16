"""Fireant.vn per-ticker posts fetcher.

Fireant is a Vietnamese stock-trading social network indexed by cashtag —
the closest VN equivalent to StockTwits. The public web client at
``fireant.vn`` is a React SPA backed by a JSON API; we hit the API
directly because HTML scraping returns an empty shell.

Endpoint (reverse-engineered from the public web client):

    GET https://restv2.fireant.vn/posts?symbol={SYMBOL}&offset=0&limit={N}

The endpoint is sometimes guarded by a bearer token but the public
``demo_token`` distributed with the web client works for read-only
requests. If both attempts fail, the fetcher degrades gracefully and
returns a placeholder so the caller never has to special-case missing
data — same contract as :mod:`stocktwits` / :mod:`reddit`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# All Fireant REST endpoints are gated by a Bearer JWT (verified against
# live API 2026-05-15). There is no anonymous read tier. Users who want
# the analyst to consume Fireant data must set ``FIREANT_BEARER`` in the
# environment — typically copied from their browser's network panel
# after signing in to fireant.vn. Without it the fetcher returns a
# self-describing placeholder so the LLM clearly sees the source is
# disabled rather than empty.
_API = "https://restv2.fireant.vn/posts?{qs}"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"
_BEARER_ENV = "FIREANT_BEARER"

_BODY_TRUNCATE = 280
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP_RE.sub("", text or "")).strip()


def _normalize_ticker(ticker: str) -> str:
    """Drop the ``.VN`` suffix — Fireant uses the bare symbol."""
    return ticker.split(".")[0].upper()


def _do_request(url: str, timeout: float, bearer: Optional[str]) -> Optional[Any]:
    headers = {
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://fireant.vn",
        "Referer": "https://fireant.vn/",
    }
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except HTTPError as exc:
        logger.warning("Fireant HTTP %s for %s", exc.code, url)
        return exc.code  # caller can branch on 401 to retry with token
    except (URLError, TimeoutError) as exc:
        logger.warning("Fireant fetch failed: %s", exc)
        return None
    try:
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("Fireant invalid JSON: %s", exc)
        return None


def _extract_posts(payload: Any) -> List[Dict]:
    """Accept either a top-level list or ``{posts/data: [...]}`` envelope."""
    if isinstance(payload, dict):
        posts = payload.get("posts") or payload.get("data") or []
    elif isinstance(payload, list):
        posts = payload
    else:
        return []
    return [p for p in posts if isinstance(p, dict)]


def _format_sentiment(post: Dict) -> str:
    """Map Fireant's sentiment int / label to a StockTwits-style tag.

    Fireant posts carry a ``sentiment`` field — encoding has shifted
    over the years (was int -1/0/+1, then string "Bullish"/"Bearish").
    We accept both.
    """
    raw = post.get("sentiment")
    if raw is None:
        return "no-label"
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s in ("bullish", "long", "buy"):
            return "Bullish"
        if s in ("bearish", "short", "sell"):
            return "Bearish"
        return "no-label"
    if isinstance(raw, (int, float)):
        if raw > 0:
            return "Bullish"
        if raw < 0:
            return "Bearish"
    return "no-label"


def fetch_fireant_posts(
    ticker: str,
    limit: int = 30,
    timeout: float = 10.0,
) -> str:
    """Fetch recent Fireant posts for ``ticker`` as a formatted block.

    Requires ``FIREANT_BEARER`` in the environment — Fireant's API has
    no anonymous tier. When the token is missing or rejected the
    fetcher returns a self-describing ``<unavailable>`` placeholder so
    the caller never has to special-case None or exceptions, matching
    the contract used by :func:`stocktwits.fetch_stocktwits_messages`.
    """
    symbol = _normalize_ticker(ticker)
    bearer = os.environ.get(_BEARER_ENV, "").strip() or None
    if not bearer:
        return (
            f"<Fireant unavailable for ${symbol}: set {_BEARER_ENV} env "
            f"to a Bearer token (copy from fireant.vn after sign-in)>"
        )

    qs = urlencode({"symbol": symbol, "offset": 0, "limit": limit})
    url = _API.format(qs=qs)

    payload = _do_request(url, timeout, bearer=bearer)
    if payload is None or isinstance(payload, int):
        code = payload if isinstance(payload, int) else "network"
        return f"<Fireant unavailable for ${symbol}: HTTP {code}>"

    posts = _extract_posts(payload)
    if not posts:
        return f"<no Fireant posts found for ${symbol}>"

    lines: List[str] = []
    bullish = bearish = unlabeled = 0
    total_likes = total_comments = 0
    for post in posts[:limit]:
        created = (post.get("date") or post.get("createdDate") or post.get("postedDate") or "")[:10]
        user = (post.get("user") or post.get("creator") or {})
        user_name = user.get("name") or user.get("userName") or user.get("username") or "?"

        body = _strip_tags(post.get("content") or post.get("body") or "")
        if not body:
            continue
        if len(body) > _BODY_TRUNCATE:
            body = body[:_BODY_TRUNCATE] + "…"

        tag = _format_sentiment(post)
        if tag == "Bullish":
            bullish += 1
        elif tag == "Bearish":
            bearish += 1
        else:
            unlabeled += 1

        likes = int(post.get("totalLikes") or post.get("likes") or 0)
        comments = int(post.get("totalReplies") or post.get("comments") or 0)
        total_likes += likes
        total_comments += comments

        lines.append(
            f"[{created or '?'} · @{user_name} · {tag} · "
            f"{likes:>3}♥ · {comments:>2}💬] {body}"
        )

    if not lines:
        return f"<no Fireant posts found for ${symbol} after filtering>"

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"Fireant.vn — ${symbol}: "
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} posts · "
        f"{total_likes} likes, {total_comments} comments across matches"
    )
    return summary + "\n\n" + "\n".join(lines)

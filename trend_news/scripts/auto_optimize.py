"""
Auto-optimize content fetching loop.

Each iteration:
1. Fetch content batch (priority: VN financial sources)
2. Measure success rate per source
3. Tune selectors for failing sources
4. Update DB stats
5. Repeat

Usage: python scripts/auto_optimize.py --iterations 10 --batch 200
"""
import argparse
import asyncio
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from src.utils.content_fetcher import ContentFetcher, SELECTORS, _extract_text, MAX_CONTENT_LEN

DB_PATH = "output/trend_news.db"

# VN financial sources — priority for content fetching
VN_FIN_SOURCES = [
    "cafef-chungkhoan", "cafef",
    "vnexpress-kinhdoanh", "vnexpress-chungkhoan",
    "vietnambiz-chungkhoan", "vietnambiz-doanhnghiep", "vietnambiz-nganhang",
    "tinnhanhchungkhoan", "tinnhanhchungkhoan-doanhnghiep", "tinnhanhchungkhoan-nhandinh",
    "24hmoney",
    "baodautu-taichinh", "baodautu-chungkhoan", "baodautu-kinhdoanh",
    "vneconomy-chungkhoan", "vneconomy-taichinh", "vneconomy-doanhnghiep",
    "vietnamfinance", "vietnamfinance-taichinh", "vietnamfinance-nganhang",
    "dantri-kinhdoanh",
]

# CN/EN sources
CN_EN_SOURCES = [
    "wallstreetcn-quick", "wallstreetcn-news", "wallstreetcn-hot",
    "cls-depth", "cls-telegraph", "cls-hot",
    "jin10", "gelonghui", "zaobao",
    "mktnews-flash",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,zh-CN;q=0.8,en;q=0.7",
}


def probe_source_selectors(url: str, source_id: str, timeout: int = 8) -> Dict:
    """Probe a URL to find the best CSS selector for article content."""
    result = {"url": url, "source_id": source_id, "status": 0, "best_selector": None, "content_len": 0, "sample": ""}
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        result["status"] = r.status_code
        if r.status_code != 200:
            return result
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"]):
            tag.decompose()

        # Try many common selectors
        candidates = []
        for el in soup.find_all(["div", "article", "section", "main"], class_=True):
            cls = " ".join(el.get("class", []))
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 200:
                candidates.append((len(text), f".{cls.split()[0]}", text))

        # Also try by id
        for el in soup.find_all(id=True):
            text = el.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 200:
                candidates.append((len(text), f"#{el.get('id')}", text))

        # Sort by length, cap, pick best non-nav content
        candidates.sort(key=lambda x: -x[0])
        for length, selector, text in candidates[:5]:
            # Skip navigation/menu heavy content
            words = text.split()
            if length > 300:
                result["best_selector"] = selector
                result["content_len"] = min(length, MAX_CONTENT_LEN)
                result["sample"] = text[:150]
                break

    except Exception as e:
        result["error"] = str(e)
    return result


def get_articles_needing_content(db: sqlite3.Connection, sources: List[str], limit: int) -> List[Tuple]:
    c = db.cursor()
    if sources:
        ph = ",".join("?" * len(sources))
        rows = c.execute(
            f"""SELECT id, url, source_id FROM news_articles
                WHERE source_id IN ({ph})
                AND url IS NOT NULL AND url != '' AND LENGTH(url) > 10
                AND (content IS NULL OR content = '')
                ORDER BY crawled_at DESC LIMIT ?""",
            sources + [limit],
        ).fetchall()
    else:
        rows = c.execute(
            """SELECT id, url, source_id FROM news_articles
               WHERE url IS NOT NULL AND url != '' AND LENGTH(url) > 10
               AND (content IS NULL OR content = '')
               ORDER BY crawled_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return rows


def save_content_batch(db: sqlite3.Connection, results: Dict[int, str]) -> int:
    c = db.cursor()
    updates = [(content, aid) for aid, content in results.items() if content and len(content) > 50]
    if updates:
        c.executemany("UPDATE news_articles SET content=? WHERE id=?", updates)
        db.commit()
    return len(updates)


def print_stats(db: sqlite3.Connection, iteration: int, elapsed: float, fetched: int, saved: int, source_stats: Dict):
    c = db.cursor()
    total = c.execute("SELECT COUNT(*) FROM news_articles WHERE url IS NOT NULL AND url != ''").fetchone()[0]
    has_content = c.execute("SELECT COUNT(*) FROM news_articles WHERE content IS NOT NULL AND LENGTH(content) > 50").fetchone()[0]
    pct = has_content / total * 100 if total else 0

    print(f"\n{'='*60}")
    print(f"  Iteration {iteration:2d} complete — {elapsed:.1f}s")
    print(f"  Fetched: {fetched} | Saved: {saved} | Rate: {fetched/elapsed:.0f}/s")
    print(f"  DB Coverage: {has_content:,}/{total:,} articles = {pct:.1f}%")
    if source_stats:
        print(f"  Per-source success:")
        for src, (ok, fail) in sorted(source_stats.items(), key=lambda x: -x[1][0])[:8]:
            total_src = ok + fail
            rate = ok / total_src * 100 if total_src else 0
            icon = "✅" if rate > 70 else ("⚠️" if rate > 20 else "❌")
            print(f"    {icon} {src:30s} {ok:3d}/{total_src:3d} ({rate:.0f}%)")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Auto-optimize content fetching")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--batch", type=int, default=200, help="Articles per iteration")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--probe", action="store_true", help="Probe new selectors for failing sources")
    args = parser.parse_args()

    db = sqlite3.connect(DB_PATH)
    fetcher = ContentFetcher()

    print(f"🚀 Auto-optimize: {args.iterations} iterations × {args.batch} articles (concurrency={args.concurrency})")

    total_saved = 0
    source_success: Dict[str, List[int]] = defaultdict(lambda: [0, 0])  # [ok, fail]

    for i in range(1, args.iterations + 1):
        t0 = time.time()

        # Priority: VN financial first, then CN/EN
        articles = get_articles_needing_content(db, VN_FIN_SOURCES, args.batch // 2)
        remaining = args.batch - len(articles)
        if remaining > 0:
            articles += get_articles_needing_content(db, CN_EN_SOURCES, remaining // 2)
        if len(articles) < args.batch // 2:
            # Fill with any remaining source
            articles += get_articles_needing_content(db, [], args.batch - len(articles))

        # Deduplicate
        seen = set()
        articles = [a for a in articles if a[0] not in seen and not seen.add(a[0])]

        if not articles:
            print(f"\n✅ Iteration {i}: No more articles to fetch — done!")
            break

        print(f"\n[{i}/{args.iterations}] Fetching {len(articles)} articles...", end=" ", flush=True)

        results = asyncio.run(fetcher.fetch_batch(articles, concurrency=args.concurrency))
        saved = save_content_batch(db, results)
        elapsed = time.time() - t0
        total_saved += saved

        # Track per-source stats
        iter_source_stats: Dict[str, Tuple[int, int]] = defaultdict(lambda: [0, 0])
        for aid, url, src in articles:
            if aid in results and results[aid]:
                iter_source_stats[src][0] += 1
                source_success[src][0] += 1
            else:
                iter_source_stats[src][1] += 1
                source_success[src][1] += 1

        print(f"saved {saved}/{len(articles)} in {elapsed:.1f}s")
        print_stats(db, i, elapsed, len(articles), saved, iter_source_stats)

        # Auto-probe: if a source has 0% success, probe one URL to find selector
        if args.probe and i % 3 == 0:
            failing = [src for src, (ok, fail) in source_success.items() if ok == 0 and fail >= 3]
            if failing:
                print(f"\n🔍 Probing selectors for failing sources: {failing[:3]}")
                c = db.cursor()
                for src in failing[:3]:
                    row = c.execute(
                        "SELECT url FROM news_articles WHERE source_id=? AND url IS NOT NULL AND url != '' LIMIT 1",
                        (src,),
                    ).fetchone()
                    if row:
                        probe = probe_source_selectors(row[0], src)
                        if probe.get("best_selector") and probe["content_len"] > 200:
                            print(f"  💡 {src}: try selector '{probe['best_selector']}' ({probe['content_len']} chars)")
                            print(f"     Sample: {probe['sample'][:80]}")
                            # Update SELECTORS dynamically (in-memory only)
                            prefix = src.split("-")[0]
                            if src not in SELECTORS and prefix not in SELECTORS:
                                SELECTORS[src] = [probe["best_selector"]]
                                print(f"  ✅ Added selector {probe['best_selector']} for {src}")
                        else:
                            print(f"  ❌ {src}: no good selector found (status={probe.get('status')} len={probe['content_len']})")

        # Small pause between iterations
        if i < args.iterations:
            time.sleep(1)

    # Final summary
    c = db.cursor()
    total_articles = c.execute("SELECT COUNT(*) FROM news_articles WHERE url IS NOT NULL AND url != ''").fetchone()[0]
    has_content = c.execute("SELECT COUNT(*) FROM news_articles WHERE content IS NOT NULL AND LENGTH(content) > 50").fetchone()[0]
    pct = has_content / total_articles * 100 if total_articles else 0

    print(f"\n{'='*60}")
    print(f"🏁 FINAL RESULTS after {args.iterations} iterations")
    print(f"   Total saved this run: {total_saved:,} articles")
    print(f"   DB coverage: {has_content:,}/{total_articles:,} = {pct:.1f}%")
    print(f"\n   Top sources (success rate):")
    for src, (ok, fail) in sorted(source_success.items(), key=lambda x: -x[1][0])[:15]:
        total_src = ok + fail
        rate = ok / total_src * 100 if total_src else 0
        icon = "✅" if rate > 70 else ("⚠️" if rate > 20 else "❌")
        print(f"   {icon} {src:30s} {ok:4d}/{total_src:4d} ({rate:4.0f}%)")
    print(f"{'='*60}")
    db.close()


if __name__ == "__main__":
    main()

"""
Integration test: WorldMonitor enrichment pipeline.

Tests all 3 phases:
  Phase 1: WorldMonitorFetcher — RSS fetch + classify
  Phase 2: ArticleEnricher    — cross-reference
  Phase 3: GroqSummarizer     — LLM enrichment

Run:
    cd trend_news
    python -m pytest tests/test_worldmonitor_pipeline.py -v
    # Or standalone:
    python tests/test_worldmonitor_pipeline.py
"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scrapers.worldmonitor_fetcher import (
    WorldMonitorFetcher,
    classify_threat,
    WORLDMONITOR_FEEDS,
)
from src.core.article_enricher import ArticleEnricher
from src.core.groq_summarizer import GroqSummarizer


# ── Sample VN articles (simulate existing scraper output) ─────────────────────

SAMPLE_VN_ARTICLES = [
    {
        "title": "VnIndex tăng 15 điểm nhờ cổ phiếu ngân hàng bứt phá",
        "url": "https://cafef.vn/sample-1",
        "source": "CafeF",
    },
    {
        "title": "Xuất khẩu Việt Nam sang Mỹ giảm mạnh do thuế quan mới",
        "url": "https://vneconomy.vn/sample-2",
        "source": "VnEconomy",
    },
    {
        "title": "Tỷ giá USD/VND tăng cao nhất 6 tháng qua áp lực từ Fed",
        "url": "https://cafef.vn/sample-3",
        "source": "CafeF",
    },
    {
        "title": "Samsung mở rộng nhà máy tại Việt Nam thêm 2 tỷ USD",
        "url": "https://vnexpress.net/sample-4",
        "source": "VnExpress",
    },
    {
        "title": "Giá dầu thế giới tăng 3% ảnh hưởng chi phí sản xuất trong nước",
        "url": "https://vneconomy.vn/sample-5",
        "source": "VnEconomy",
    },
]


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_phase1_classifier():
    separator("Phase 1a: Threat Classifier")

    test_cases = [
        ("US launches airstrike on Iran nuclear facility", "critical"),
        ("Federal Reserve raises interest rates by 50bps", "high"),
        ("Vietnam-China trade talks scheduled for next month", "medium"),
        ("Samsung announces new investment deal in Vietnam", "low"),
        ("Weather forecast for Southeast Asia", "info"),
    ]
    passed = 0
    for title, expected in test_cases:
        result = classify_threat(title)
        match = "✓" if result["level"] == expected else "✗"
        print(f"  {match} [{result['level']:8s}] {title[:55]}")
        if result["level"] == expected:
            passed += 1
    print(f"\n  Result: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_phase1_fetcher(categories=None):
    separator("Phase 1b: WorldMonitorFetcher (live RSS)")

    fetcher = WorldMonitorFetcher(timeout=10, max_items_per_feed=5)
    cats = categories or ["vietnam", "asia"]  # small subset for quick test

    print(f"  Fetching categories: {cats}")
    t0 = time.time()
    results = fetcher.fetch_all(categories=cats)
    elapsed = time.time() - t0

    total = sum(len(v) for v in results.values())
    print(f"\n  ✓ Fetched {total} articles in {elapsed:.1f}s")
    for cat, items in results.items():
        print(f"    [{cat}] {len(items)} articles")
        for item in items[:2]:
            lvl = item.get("threat_level", "?")
            print(f"      [{lvl:8s}] {item['title'][:65]}")

    assert total > 0, "No articles fetched — check network/RSS"
    return results


def test_phase2_enricher():
    separator("Phase 2: ArticleEnricher")

    # Fetch fresh WM articles
    from src.scrapers.worldmonitor_fetcher import WorldMonitorFetcher
    fetcher = WorldMonitorFetcher(timeout=10, max_items_per_feed=3, use_cache=True)
    wm_results = fetcher.fetch_all(categories=["vietnam", "finance"])
    wm_articles = [a for items in wm_results.values() for a in items]

    enricher = ArticleEnricher(wm_articles, max_context_items=3, min_overlap_score=0.1)
    enriched = enricher.enrich_batch(SAMPLE_VN_ARTICLES)

    print(f"  Enriched {len(enriched)} VN articles\n")
    for art in enriched:
        print(f"  📰 {art['title'][:55]}")
        print(f"     threat={art['threat_level']}  geo={art['geo_relevance']}  "
              f"signal={art['market_signal']}")
        if art["global_context"]:
            print(f"     Context: {art['global_context'][0]['title'][:55]}")
        else:
            print(f"     Context: (no match)")
        print()

    assert all("threat_level" in a for a in enriched)
    assert all("global_context" in a for a in enriched)
    return enriched


def test_phase3_groq():
    from src.scrapers.worldmonitor_fetcher import WorldMonitorFetcher
    from src.core.article_enricher import ArticleEnricher
    fetcher = WorldMonitorFetcher(timeout=10, max_items_per_feed=3, use_cache=True)
    wm_articles = fetcher.fetch_flat(["vietnam"])
    enriched_articles = ArticleEnricher(wm_articles).enrich_batch(SAMPLE_VN_ARTICLES[:2])
    separator("Phase 3: GroqSummarizer")

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        print("  ⚠ GROQ_API_KEY not set — skipping LLM test")
        print("  Set: export GROQ_API_KEY=gsk_...")
        return enriched_articles

    summarizer = GroqSummarizer(api_key=api_key)

    # Test summarize_with_context
    vn_headlines = [a["title"] for a in enriched_articles[:3]]
    global_ctx = []
    for a in enriched_articles[:3]:
        global_ctx.extend([c["title"] for c in a.get("global_context", [])[:2]])

    print("  Testing summarize_with_context...")
    t0 = time.time()
    summary = summarizer.summarize_with_context(vn_headlines, global_ctx, lang="vi")
    elapsed = time.time() - t0
    if summary:
        print(f"  ✓ Summary ({elapsed:.1f}s):\n    {summary}\n")
    else:
        print("  ✗ Summary failed\n")

    # Test enrich_batch (first 3 only to save quota)
    print("  Testing enrich_batch (3 articles)...")
    final = summarizer.enrich_batch(enriched_articles[:3], delay_between=0.2)

    for art in final:
        sig = art.get("groq_market_signal", "?")
        summ = art.get("groq_summary", "")
        print(f"  📊 [{sig:8s}] {art['title'][:50]}")
        if summ:
            print(f"          → {summ[:100]}")

    return final


def run_all(fetch_categories=None):
    """Run the full pipeline test."""
    print("\n🚀 WorldMonitor × TrendNews Pipeline Test")
    print(f"{'='*60}\n")

    # Phase 1a — classifier unit test
    test_phase1_classifier()

    # Phase 1b — live RSS fetch
    wm_results = test_phase1_fetcher(fetch_categories)
    wm_flat = []
    for items in wm_results.values():
        wm_flat.extend(items)

    print(f"\n  Total WM articles: {len(wm_flat)}")

    # Phase 2 — enrichment
    enriched = test_phase2_enricher(wm_flat)

    # Phase 3 — Groq
    final = test_phase3_groq(enriched)

    separator("Summary")
    print(f"  ✓ Phase 1: {len(wm_flat)} global articles fetched")
    print(f"  ✓ Phase 2: {len(enriched)} VN articles enriched")
    print(f"  ✓ Phase 3: Groq summaries {'added' if os.environ.get('GROQ_API_KEY') else 'skipped (no key)'}")

    # Output sample
    print("\n  Sample enriched article (JSON):")
    sample = {k: v for k, v in enriched[0].items() if k != "global_context"}
    sample["global_context_count"] = len(enriched[0].get("global_context", []))
    print(json.dumps(sample, ensure_ascii=False, indent=4))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", nargs="+",
                        default=["vietnam", "asia"],
                        help="WM categories to fetch (default: vietnam asia)")
    args = parser.parse_args()
    run_all(fetch_categories=args.categories)

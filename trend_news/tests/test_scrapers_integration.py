"""
Integration tests for Vietnamese financial news scrapers.

These tests make REAL HTTP requests to verify scrapers can actually
crawl articles from each source. Run with network access.

Usage:
    # Run all integration tests
    cd trend_news && pytest tests/test_scrapers_integration.py -v

    # Run only a specific source group
    cd trend_news && pytest tests/test_scrapers_integration.py -v -k "vneconomy"

    # Run with timeout control (default 30s per test)
    cd trend_news && pytest tests/test_scrapers_integration.py -v --timeout=60

    # Show stdout (see article counts per scraper)
    cd trend_news && pytest tests/test_scrapers_integration.py -v -s
"""

import sys
import os
import re

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.scrapers import (
    # VnEconomy
    VnEconomyChungKhoanScraper,
    VnEconomyTaiChinhScraper,
    VnEconomyDoanhNghiepScraper,
    # Tin Nhanh Chứng Khoán
    TinNhanhChungKhoanScraper,
    TinNhanhChungKhoanNhanDinhScraper,
    TinNhanhChungKhoanDoanhNghiepScraper,
    # VietnamBiz
    VietnamBizChungKhoanScraper,
    VietnamBizDoanhNghiepScraper,
    VietnamBizNganHangScraper,
    # Báo Đầu Tư
    BaoDauTuTaiChinhScraper,
    BaoDauTuChungKhoanScraper,
    BaoDauTuKinhDoanhScraper,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_scraper_result(result, scraper_name: str, min_articles: int = 3):
    """Common assertions for a successful scrape result."""
    assert result is not None, (
        f"{scraper_name}: fetch() returned None — site may be down or HTML structure changed"
    )
    assert result["status"] == "success", (
        f"{scraper_name}: status is '{result.get('status')}', expected 'success'"
    )
    assert "id" in result, f"{scraper_name}: missing 'id' key in result"
    assert "items" in result, f"{scraper_name}: missing 'items' key in result"

    items = result["items"]
    assert isinstance(items, list), f"{scraper_name}: 'items' should be a list"
    assert len(items) >= min_articles, (
        f"{scraper_name}: expected at least {min_articles} articles, got {len(items)}"
    )

    print(f"\n  [{scraper_name}] crawled {len(items)} articles")

    for i, article in enumerate(items):
        _assert_article_shape(article, scraper_name, index=i)


def _assert_article_shape(article: dict, scraper_name: str, index: int = 0):
    """Verify each article dict has the expected shape and valid content."""
    ctx = f"{scraper_name}[{index}]"

    assert "title" in article, f"{ctx}: missing 'title'"
    assert "url" in article, f"{ctx}: missing 'url'"
    assert "mobileUrl" in article, f"{ctx}: missing 'mobileUrl'"

    title = article["title"]
    url = article["url"]

    assert isinstance(title, str) and len(title) >= 10, (
        f"{ctx}: title too short or wrong type: {title!r}"
    )
    assert isinstance(url, str) and url.startswith("http"), (
        f"{ctx}: URL must be absolute http/https, got: {url!r}"
    )
    # URL should not be a bare domain (must have a path)
    assert len(url.split("/")) > 3, (
        f"{ctx}: URL looks like a bare domain with no path: {url!r}"
    )
    # Title should not be a navigation/menu item (at least 2 words)
    assert title.count(" ") >= 1 or title.count("-") >= 1, (
        f"{ctx}: title looks like a single navigation word: {title!r}"
    )


def _skip_if_unreachable(url: str, timeout: int = 10):
    """Skip test if the site is not reachable (network/DNS issue)."""
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code >= 500:
            pytest.skip(f"Site returned {r.status_code}: {url}")
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.SSLError) as e:
        pytest.skip(f"Site unreachable: {url} — {e}")


# ---------------------------------------------------------------------------
# VnEconomy (vneconomy.vn)
# ---------------------------------------------------------------------------

class TestVnEconomyScrapers:
    """
    VnEconomy.vn — Thời báo Kinh tế Việt Nam.
    Authoritative economic newspaper, strong VN30 coverage.
    Article URL pattern: /slug-title.htm (no -e<digits> suffix)
    """

    def test_chungkhoan_returns_articles(self):
        scraper = VnEconomyChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "VnEconomy-ChungKhoan")

    def test_chungkhoan_urls_are_articles_not_categories(self):
        """Verify that returned URLs are article pages, not category aggregators."""
        scraper = VnEconomyChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        category_pattern = re.compile(r"-e\d+\.htm$")
        for article in result["items"]:
            url = article["url"]
            assert not category_pattern.search(url), (
                f"VnEconomy: URL looks like a category page: {url}"
            )
            # Article slugs should be descriptive (multiple hyphens)
            path = url.replace("https://vneconomy.vn", "").lstrip("/")
            slug = path.replace(".htm", "")
            assert slug.count("-") >= 2, (
                f"VnEconomy: slug looks too short for an article: {slug!r}"
            )

    def test_taichinh_returns_articles(self):
        scraper = VnEconomyTaiChinhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "VnEconomy-TaiChinh")

    def test_doanhnghiep_returns_articles(self):
        scraper = VnEconomyDoanhNghiepScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "VnEconomy-DoanhNghiepNiemYet")

    def test_source_ids_are_correct(self):
        assert VnEconomyChungKhoanScraper().source_id == "vneconomy-chungkhoan"
        assert VnEconomyTaiChinhScraper().source_id == "vneconomy-taichinh"
        assert VnEconomyDoanhNghiepScraper().source_id == "vneconomy-doanhnghiep"

    def test_no_duplicate_urls_in_chungkhoan(self):
        scraper = VnEconomyChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        urls = [a["url"] for a in result["items"]]
        assert len(urls) == len(set(urls)), "VnEconomy: duplicate URLs found in results"


# ---------------------------------------------------------------------------
# Tin Nhanh Chứng Khoán (tinnhanhchungkhoan.vn)
# ---------------------------------------------------------------------------

class TestTinNhanhChungKhoanScrapers:
    """
    tinnhanhchungkhoan.vn — Dedicated Vietnamese stock market newspaper.
    Best source for VN30 real-time news.
    Article URL pattern: https://www.tinnhanhchungkhoan.vn/slug-postXXXXXX.html
    """

    def test_chungkhoan_returns_articles(self):
        scraper = TinNhanhChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "TinNhanhChungKhoan")

    def test_chungkhoan_urls_have_post_pattern(self):
        """All returned URLs should match the -postXXXXXX.html article pattern."""
        scraper = TinNhanhChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        post_pattern = re.compile(r"-post\d+\.html$")
        for article in result["items"]:
            url = article["url"]
            assert post_pattern.search(url), (
                f"TinNhanhChungKhoan: URL does not match -postXXXXXX.html pattern: {url}"
            )

    def test_nhandinh_returns_articles(self):
        scraper = TinNhanhChungKhoanNhanDinhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "TinNhanhChungKhoan-NhanDinh")

    def test_doanhnghiep_returns_articles(self):
        scraper = TinNhanhChungKhoanDoanhNghiepScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "TinNhanhChungKhoan-DoanhNghiep")

    def test_source_ids_are_correct(self):
        assert TinNhanhChungKhoanScraper().source_id == "tinnhanhchungkhoan"
        assert TinNhanhChungKhoanNhanDinhScraper().source_id == "tinnhanhchungkhoan-nhandinh"
        assert TinNhanhChungKhoanDoanhNghiepScraper().source_id == "tinnhanhchungkhoan-doanhnghiep"

    def test_no_category_links_included(self):
        """Category pages like /nhan-dinh/, /ck-quoc-te/ must not appear in results."""
        scraper = TinNhanhChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        post_pattern = re.compile(r"-post\d+\.html$")
        for article in result["items"]:
            url = article["url"]
            assert post_pattern.search(url), (
                f"Category/nav link leaked into results: {url}"
            )

    def test_no_duplicate_urls(self):
        scraper = TinNhanhChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        urls = [a["url"] for a in result["items"]]
        assert len(urls) == len(set(urls)), "TinNhanhChungKhoan: duplicate URLs found"


# ---------------------------------------------------------------------------
# VietnamBiz (vietnambiz.vn)
# ---------------------------------------------------------------------------

class TestVietnamBizScrapers:
    """
    vietnambiz.vn — Business & finance portal with strong VN30 coverage.
    Article URL pattern: /slug-YYYYMMDDHHMMSSXXX.htm (timestamp suffix)
    """

    def test_chungkhoan_returns_articles(self):
        scraper = VietnamBizChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "VietnamBiz-ChungKhoan")

    def test_chungkhoan_urls_have_timestamp_pattern(self):
        """Article URLs must end with a long numeric timestamp."""
        scraper = VietnamBizChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        timestamp_pattern = re.compile(r"-\d{10,}\.htm$")
        for article in result["items"]:
            url = article["url"]
            assert timestamp_pattern.search(url), (
                f"VietnamBiz: URL does not match timestamp pattern: {url}"
            )

    def test_doanhnghiep_returns_articles(self):
        scraper = VietnamBizDoanhNghiepScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "VietnamBiz-DoanhNghiep")

    def test_nganhang_returns_articles(self):
        scraper = VietnamBizNganHangScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "VietnamBiz-NganHang")

    def test_source_ids_are_correct(self):
        assert VietnamBizChungKhoanScraper().source_id == "vietnambiz-chungkhoan"
        assert VietnamBizDoanhNghiepScraper().source_id == "vietnambiz-doanhnghiep"
        assert VietnamBizNganHangScraper().source_id == "vietnambiz-nganhang"

    def test_no_subcategory_links_in_chungkhoan(self):
        """Sub-category URLs like /chung-khoan/thi-truong.htm must be excluded."""
        scraper = VietnamBizChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        timestamp_pattern = re.compile(r"-\d{10,}\.htm$")
        for article in result["items"]:
            url = article["url"]
            assert timestamp_pattern.search(url), (
                f"VietnamBiz: sub-category or nav link leaked into results: {url}"
            )

    def test_no_duplicate_urls(self):
        scraper = VietnamBizChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        urls = [a["url"] for a in result["items"]]
        assert len(urls) == len(set(urls)), "VietnamBiz: duplicate URLs found"


# ---------------------------------------------------------------------------
# Báo Đầu Tư (baodautu.vn)
# ---------------------------------------------------------------------------

class TestBaoDauTuScrapers:
    """
    baodautu.vn — Official investment newspaper under Vietnam Ministry of Finance.
    Article URL pattern: https://baodautu.vn/slug-dXXXXXX.html
    """

    def test_taichinh_returns_articles(self):
        scraper = BaoDauTuTaiChinhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "BaoDauTu-TaiChinh")

    def test_taichinh_urls_have_d_pattern(self):
        """Article URLs must end with -dXXXXXX.html (5+ digit ID)."""
        scraper = BaoDauTuTaiChinhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        article_pattern = re.compile(r"-d\d{5,}\.html$")
        for article in result["items"]:
            url = article["url"]
            assert article_pattern.search(url), (
                f"BaoDauTu: URL does not match -dXXXXXX.html pattern: {url}"
            )

    def test_chungkhoan_returns_articles(self):
        scraper = BaoDauTuChungKhoanScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "BaoDauTu-ChungKhoan")

    def test_kinhdoanh_returns_articles(self):
        scraper = BaoDauTuKinhDoanhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        _assert_scraper_result(result, "BaoDauTu-KinhDoanh")

    def test_source_ids_are_correct(self):
        assert BaoDauTuTaiChinhScraper().source_id == "baodautu-taichinh"
        assert BaoDauTuChungKhoanScraper().source_id == "baodautu-chungkhoan"
        assert BaoDauTuKinhDoanhScraper().source_id == "baodautu-kinhdoanh"

    def test_no_emagazine_or_multimedia_links(self):
        """Special content types like emagazine must not appear in results."""
        scraper = BaoDauTuTaiChinhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        for article in result["items"]:
            url = article["url"]
            assert "emagazine" not in url, f"BaoDauTu: emagazine URL leaked: {url}"
            assert "multimedia" not in url, f"BaoDauTu: multimedia URL leaked: {url}"

    def test_no_duplicate_urls(self):
        scraper = BaoDauTuTaiChinhScraper()
        _skip_if_unreachable(scraper.get_url())

        result = scraper.fetch()
        if result is None:
            pytest.skip("Site unavailable")

        urls = [a["url"] for a in result["items"]]
        assert len(urls) == len(set(urls)), "BaoDauTu: duplicate URLs found"


# ---------------------------------------------------------------------------
# Cross-scraper smoke test
# ---------------------------------------------------------------------------

class TestAllNewScrapersSmoke:
    """
    Quick smoke test: run all 12 new scrapers and report which ones work.
    A scraper is considered working if it returns >= 1 article.
    This test never hard-fails — it just reports the status of each source.
    """

    ALL_SCRAPERS = [
        VnEconomyChungKhoanScraper,
        VnEconomyTaiChinhScraper,
        VnEconomyDoanhNghiepScraper,
        TinNhanhChungKhoanScraper,
        TinNhanhChungKhoanNhanDinhScraper,
        TinNhanhChungKhoanDoanhNghiepScraper,
        VietnamBizChungKhoanScraper,
        VietnamBizDoanhNghiepScraper,
        VietnamBizNganHangScraper,
        BaoDauTuTaiChinhScraper,
        BaoDauTuChungKhoanScraper,
        BaoDauTuKinhDoanhScraper,
    ]

    def test_smoke_all_scrapers(self):
        results = {}
        errors = {}

        for ScraperClass in self.ALL_SCRAPERS:
            scraper = ScraperClass()
            sid = scraper.source_id
            try:
                result = scraper.fetch(timeout=20)
                if result and result.get("items"):
                    results[sid] = len(result["items"])
                else:
                    errors[sid] = "returned None or empty items"
            except Exception as e:
                errors[sid] = str(e)

        # Print summary
        print("\n\n=== Scraper Smoke Test Results ===")
        print(f"{'Source ID':<45} {'Status':<10} {'Articles':>8}")
        print("-" * 65)
        for sid, count in sorted(results.items()):
            print(f"  ✓  {sid:<42} {'OK':<10} {count:>8}")
        for sid, err in sorted(errors.items()):
            print(f"  ✗  {sid:<42} {'FAILED':<10}  {err[:30]}")
        print("-" * 65)
        print(f"  Passed: {len(results)}/{len(self.ALL_SCRAPERS)}")

        # Require at least 50% of scrapers to work
        pass_rate = len(results) / len(self.ALL_SCRAPERS)
        assert pass_rate >= 0.5, (
            f"Too many scrapers failed: only {len(results)}/{len(self.ALL_SCRAPERS)} working. "
            f"Failed: {list(errors.keys())}"
        )

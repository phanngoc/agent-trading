"""
TinNhanhChungKhoan.vn news scraper.

Scrapes stock market news from tinnhanhchungkhoan.vn (Tin Nhanh Chứng Khoán) -
Vietnam's dedicated stock market newspaper with real-time trading news,
analysis, and company announcements covering VN30/VNINDEX stocks.
"""

import re
from typing import Dict, List

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


class TinNhanhChungKhoanScraper(BaseScraper):
    """Scraper for TinNhanhChungKhoan.vn stock market news."""

    BASE_URL = "https://www.tinnhanhchungkhoan.vn"

    def __init__(self):
        super().__init__(
            source_id="tinnhanhchungkhoan",
            source_name="Tin Nhanh Chứng Khoán"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/chung-khoan/"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from TinNhanhChungKhoan stock market section.

        Article URL pattern: https://www.tinnhanhchungkhoan.vn/slug-postXXXXXX.html
        Category URL pattern: https://www.tinnhanhchungkhoan.vn/category/ (no -post suffix)
        """
        articles = []
        seen_urls = set()

        # Article URLs contain '-postXXXXXX' pattern
        _article_pattern = re.compile(r"-post\d+\.html$")

        selectors = [
            "h2 a",
            "h3 a",
            "h4 a",
            ".post-title a",
            ".news-title a",
            ".article-title a",
            ".list-article h3 a",
            ".list-article h4 a",
        ]

        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = str(elem.get("href", "") or "")

                    if not title or len(title) < 10:
                        continue

                    # Normalize to absolute URL
                    if url and not url.startswith("http"):
                        url = self._normalize_url(url, self.BASE_URL)

                    if not url or url in seen_urls:
                        continue

                    # Must match article URL pattern (ends with -postXXXXXX.html)
                    if not _article_pattern.search(url):
                        continue

                    # Skip non-article content
                    if any(skip in url for skip in [
                        "/video/", "/photo/", "/infographics/",
                        "/emagazine/", "javascript:",
                    ]):
                        continue

                    seen_urls.add(url)
                    articles.append({
                        "title": title,
                        "url": url,
                        "mobileUrl": ""
                    })
            except Exception:
                continue

        return articles[:50]


class TinNhanhChungKhoanNhanDinhScraper(BaseScraper):
    """Scraper for TinNhanhChungKhoan market analysis/commentary section."""

    BASE_URL = "https://www.tinnhanhchungkhoan.vn"

    def __init__(self):
        super().__init__(
            source_id="tinnhanhchungkhoan-nhandinh",
            source_name="Tin Nhanh Chứng Khoán - Nhận Định"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/nhan-dinh/"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from TinNhanhChungKhoan analysis section."""
        articles = []
        seen_urls = set()

        _article_pattern = re.compile(r"-post\d+\.html$")

        for elem in soup.select("h2 a, h3 a, h4 a"):
            title = self._clean_title(elem.get_text())
            url = str(elem.get("href", "") or "")

            if not title or len(title) < 10:
                continue

            if url and not url.startswith("http"):
                url = self._normalize_url(url, self.BASE_URL)

            if not url or url in seen_urls:
                continue

            if not _article_pattern.search(url):
                continue

            seen_urls.add(url)
            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": ""
            })

        return articles[:50]


class TinNhanhChungKhoanDoanhNghiepScraper(BaseScraper):
    """Scraper for TinNhanhChungKhoan enterprise/company news section."""

    BASE_URL = "https://www.tinnhanhchungkhoan.vn"

    def __init__(self):
        super().__init__(
            source_id="tinnhanhchungkhoan-doanhnghiep",
            source_name="Tin Nhanh Chứng Khoán - Doanh Nghiệp"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/doanh-nghiep/"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from TinNhanhChungKhoan enterprise section."""
        articles = []
        seen_urls = set()

        _article_pattern = re.compile(r"-post\d+\.html$")

        for elem in soup.select("h2 a, h3 a, h4 a"):
            title = self._clean_title(elem.get_text())
            url = str(elem.get("href", "") or "")

            if not title or len(title) < 10:
                continue

            if url and not url.startswith("http"):
                url = self._normalize_url(url, self.BASE_URL)

            if not url or url in seen_urls:
                continue

            if not _article_pattern.search(url):
                continue

            seen_urls.add(url)
            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": ""
            })

        return articles[:50]

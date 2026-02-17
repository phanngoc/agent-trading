"""
BaoDauTu.vn news scraper.

Scrapes investment and financial news from baodautu.vn (Báo Đầu Tư) -
the official Investment Review newspaper under Vietnam's Ministry of Finance,
covering stocks, banking, bonds, insurance, and corporate finance
with authoritative analysis of VN30/VNINDEX listed companies.
"""

import re
from typing import Dict, List

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


class BaoDauTuTaiChinhScraper(BaseScraper):
    """Scraper for BaoDauTu finance/investment section."""

    BASE_URL = "https://baodautu.vn"

    def __init__(self):
        super().__init__(
            source_id="baodautu-taichinh",
            source_name="Báo Đầu Tư - Tài Chính"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/dau-tu-tai-chinh-d6/"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from BaoDauTu finance/investment section.

        Article URL pattern: https://baodautu.vn/slug-dXXXXXX.html
        Category URL pattern: https://baodautu.vn/category-dXX/ (short digits, trailing slash)
        """
        articles = []
        seen_urls = set()

        # Article URLs end with -d<5+ digits>.html
        _article_pattern = re.compile(r"-d\d{5,}\.html$")

        selectors = [
            "article a",
            "h2 a",
            "h3 a",
            ".list-news a",
            ".news-item a",
        ]

        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = str(elem.get("href", "") or "")

                    if not title or len(title) < 10:
                        continue

                    if url and not url.startswith("http"):
                        url = self._normalize_url(url, self.BASE_URL)

                    if not url or url in seen_urls:
                        continue

                    # Must match article URL pattern
                    if not _article_pattern.search(url):
                        continue

                    # Skip special content types
                    if any(skip in url for skip in [
                        "/emagazine", "/multimedia", "/photo/",
                        "/video/", "javascript:", "#",
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


class BaoDauTuChungKhoanScraper(BaseScraper):
    """Scraper for BaoDauTu stock market subsection."""

    BASE_URL = "https://baodautu.vn"

    def __init__(self):
        super().__init__(
            source_id="baodautu-chungkhoan",
            source_name="Báo Đầu Tư - Chứng Khoán"
        )

    def get_url(self) -> str:
        # Chứng khoán is a subsection under Đầu tư tài chính
        return f"{self.BASE_URL}/chung-khoan-d25/"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from BaoDauTu stock section."""
        articles = []
        seen_urls = set()

        _article_pattern = re.compile(r"-d\d{5,}\.html$")

        for elem in soup.select("article a, h2 a, h3 a"):
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

            if any(skip in url for skip in ["/emagazine", "/multimedia"]):
                continue

            seen_urls.add(url)
            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": ""
            })

        return articles[:50]


class BaoDauTuKinhDoanhScraper(BaseScraper):
    """Scraper for BaoDauTu business/enterprise news section."""

    BASE_URL = "https://baodautu.vn"

    def __init__(self):
        super().__init__(
            source_id="baodautu-kinhdoanh",
            source_name="Báo Đầu Tư - Kinh Doanh"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/kinh-doanh-d3/"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from BaoDauTu business section."""
        articles = []
        seen_urls = set()

        _article_pattern = re.compile(r"-d\d{5,}\.html$")

        for elem in soup.select("article a, h2 a, h3 a"):
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

            if any(skip in url for skip in ["/emagazine", "/multimedia"]):
                continue

            seen_urls.add(url)
            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": ""
            })

        return articles[:50]

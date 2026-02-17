"""
VietnamBiz.vn news scraper.

Scrapes financial and business news from vietnambiz.vn - a leading Vietnamese
business news portal with comprehensive coverage of stock market, listed companies,
banking, real estate and macroeconomics.
"""

import re
from typing import Dict, List

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


class VietnamBizChungKhoanScraper(BaseScraper):
    """Scraper for VietnamBiz stock market section."""

    BASE_URL = "https://vietnambiz.vn"

    def __init__(self):
        super().__init__(
            source_id="vietnambiz-chungkhoan",
            source_name="VietnamBiz Chứng Khoán"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/chung-khoan.htm"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamBiz stock market section.

        Article URL pattern: /slug-YYYYMMDDHHMMSSXXX.htm  (ends with long timestamp number)
        Category URL pattern: /chung-khoan/sub-category.htm  (contains subdirectory)
        """
        articles = []
        seen_urls = set()

        # Article URLs end with a long numeric timestamp (10+ digits)
        _article_pattern = re.compile(r"-\d{10,}\.htm$")

        selectors = [
            "h2 a",
            "h3 a",
            "h4 a",
            ".story-title a",
            ".article-title a",
            ".news-title a",
            ".box-category-item a",
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

                    # Only include .htm URLs with timestamp-style suffix
                    if not _article_pattern.search(url):
                        continue

                    # Skip non-article content types
                    if any(skip in url for skip in [
                        "/photo/", "/video/", "/infographics/",
                        "/emagazine/", "javascript:", "#",
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


class VietnamBizDoanhNghiepScraper(BaseScraper):
    """Scraper for VietnamBiz enterprise/company news section."""

    BASE_URL = "https://vietnambiz.vn"

    def __init__(self):
        super().__init__(
            source_id="vietnambiz-doanhnghiep",
            source_name="VietnamBiz Doanh Nghiệp"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/doanh-nghiep.htm"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamBiz enterprise section."""
        articles = []
        seen_urls = set()

        _article_pattern = re.compile(r"-\d{10,}\.htm$")

        for elem in soup.select("h2 a, h3 a"):
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


class VietnamBizNganHangScraper(BaseScraper):
    """Scraper for VietnamBiz banking section."""

    BASE_URL = "https://vietnambiz.vn"

    def __init__(self):
        super().__init__(
            source_id="vietnambiz-nganhang",
            source_name="VietnamBiz Ngân Hàng"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/tai-chinh/ngan-hang.htm"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamBiz banking section."""
        articles = []
        seen_urls = set()

        _article_pattern = re.compile(r"-\d{10,}\.htm$")

        for elem in soup.select("h2 a, h3 a"):
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

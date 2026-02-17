"""
VnEconomy.vn news scraper.

Scrapes financial and stock market news from vneconomy.vn - Thời báo Kinh tế Việt Nam,
one of Vietnam's most authoritative economic newspapers with deep coverage of
VN30/VNINDEX stocks, banking, investment, and macroeconomics.
"""

import re
from typing import Dict, List

from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


class VnEconomyChungKhoanScraper(BaseScraper):
    """Scraper for VnEconomy stock market section."""

    BASE_URL = "https://vneconomy.vn"

    def __init__(self):
        super().__init__(
            source_id="vneconomy-chungkhoan",
            source_name="VnEconomy Chứng Khoán"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/chung-khoan.htm"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VnEconomy stock market section.

        Article URLs pattern: /slug-title.htm (no -e<digits> suffix)
        Category URLs pattern: /category-e<digits>.htm (skip these)
        """
        articles = []
        seen_urls = set()

        # VnEconomy articles appear in h3 and h2 tags
        selectors = [
            "h3 a",
            "h2 a",
            ".story__title a",
            ".list-news__item a",
        ]

        # Category link pattern to skip: ends with -e<digits>.htm
        _category_pattern = re.compile(r"-e\d+\.htm$")

        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = elem.get("href", "")

                    if not title or len(title) < 10:
                        continue

                    url = self._normalize_url(url, self.BASE_URL)

                    if not url or url in seen_urls:
                        continue

                    # Only include .htm article URLs
                    if not url.endswith(".htm"):
                        continue

                    # Skip category/topic aggregation pages
                    if _category_pattern.search(url):
                        continue

                    # Skip non-article paths
                    path = url.replace(self.BASE_URL, "")
                    if any(skip in path for skip in [
                        "/video/", "/photo/", "/infographics/",
                        "/interactive", "/multimedia",
                    ]):
                        continue

                    # Article slugs should have multiple words (at least 2 hyphens)
                    slug = path.lstrip("/").replace(".htm", "")
                    if slug.count("-") < 2:
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


class VnEconomyTaiChinhScraper(BaseScraper):
    """Scraper for VnEconomy finance/banking section."""

    BASE_URL = "https://vneconomy.vn"

    def __init__(self):
        super().__init__(
            source_id="vneconomy-taichinh",
            source_name="VnEconomy Tài Chính"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/tai-chinh.htm"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VnEconomy finance section."""
        articles = []
        seen_urls = set()

        _category_pattern = re.compile(r"-e\d+\.htm$")

        for elem in soup.select("h3 a, h2 a"):
            title = self._clean_title(elem.get_text())
            url = elem.get("href", "")

            if not title or len(title) < 10:
                continue

            url = self._normalize_url(url, self.BASE_URL)

            if not url or url in seen_urls:
                continue

            if not url.endswith(".htm"):
                continue

            if _category_pattern.search(url):
                continue

            path = url.replace(self.BASE_URL, "")
            slug = path.lstrip("/").replace(".htm", "")
            if slug.count("-") < 2:
                continue

            seen_urls.add(url)
            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": ""
            })

        return articles[:50]


class VnEconomyDoanhNghiepScraper(BaseScraper):
    """Scraper for VnEconomy listed companies/enterprise section."""

    BASE_URL = "https://vneconomy.vn"

    def __init__(self):
        super().__init__(
            source_id="vneconomy-doanhnghiep",
            source_name="VnEconomy Doanh Nghiệp Niêm Yết"
        )

    def get_url(self) -> str:
        return f"{self.BASE_URL}/doanh-nghiep-niem-yet.htm"

    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VnEconomy listed companies section."""
        articles = []
        seen_urls = set()

        _category_pattern = re.compile(r"-e\d+\.htm$")

        for elem in soup.select("h3 a, h2 a"):
            title = self._clean_title(elem.get_text())
            url = elem.get("href", "")

            if not title or len(title) < 10:
                continue

            url = self._normalize_url(url, self.BASE_URL)

            if not url or url in seen_urls:
                continue

            if not url.endswith(".htm"):
                continue

            if _category_pattern.search(url):
                continue

            path = url.replace(self.BASE_URL, "")
            slug = path.lstrip("/").replace(".htm", "")
            if slug.count("-") < 2:
                continue

            seen_urls.add(url)
            articles.append({
                "title": title,
                "url": url,
                "mobileUrl": ""
            })

        return articles[:50]

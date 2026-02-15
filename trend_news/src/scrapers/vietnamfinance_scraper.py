"""
VietnamFinance.vn news scraper.

Scrapes financial news from vietnamfinance.vn - a leading Vietnamese
financial news and analysis website focused on finance, banking, 
stock market, real estate, and business news.
"""

from typing import Dict, List
from bs4 import BeautifulSoup

from .base_scraper import BaseScraper


class VietnamFinanceScraper(BaseScraper):
    """Scraper for VietnamFinance.vn homepage financial news."""
    
    BASE_URL = "https://vietnamfinance.vn"
    
    def __init__(self):
        super().__init__(
            source_id="vietnamfinance",
            source_name="VietnamFinance"
        )
    
    def get_url(self) -> str:
        return self.BASE_URL
    
    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamFinance homepage."""
        articles = []
        seen_urls = set()
        
        # VietnamFinance uses various tags for article titles
        # Main article titles are usually in h2, h3 tags within anchor tags
        selectors = [
            # Main headlines
            "h2 a",
            "h3 a",
            # Article list items
            ".article-list h2 a",
            ".article-list h3 a",
            # News items
            ".news-item a",
            ".news-list a",
            # Title classes
            ".title a",
            ".article-title a",
            # Featured articles
            ".featured h2 a",
            ".featured h3 a",
        ]
        
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = str(elem.get('href', '') or '')
                    
                    if not title or len(title) < 10:
                        continue
                    
                    # Normalize URL - VietnamFinance URLs are usually absolute
                    if url and not url.startswith('http'):
                        url = self._normalize_url(url, self.BASE_URL)
                    
                    if not url or url in seen_urls:
                        continue
                    
                    # Only include article links (usually end with .html and contain -dXXX pattern)
                    # Skip navigation, category, and other non-article links
                    if not any(skip in url for skip in [
                        '/photo/', '/video/', '/infographics/',
                        '/emagazine/', 'javascript:', '#'
                    ]):
                        # VietnamFinance article URLs typically match pattern: /slug-dXXXXX.html
                        # or category pages like /tai-chinh.htm, /ngan-hang/
                        if '.html' in url or url.endswith('/'):
                            seen_urls.add(url)
                            articles.append({
                                "title": title,
                                "url": url,
                                "mobileUrl": ""
                            })
            except Exception as e:
                # Continue even if one selector fails
                print(f"  Warning parsing {selector}: {e}")
                continue
        
        # Limit to top 50 articles
        return articles[:50]


class VietnamFinanceTaiChinhScraper(BaseScraper):
    """Scraper for VietnamFinance finance/stock market section."""
    
    BASE_URL = "https://vietnamfinance.vn"
    
    def __init__(self):
        super().__init__(
            source_id="vietnamfinance-taichinh",
            source_name="VietnamFinance Tài Chính"
        )
    
    def get_url(self) -> str:
        return f"{self.BASE_URL}/tai-chinh.htm"
    
    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamFinance finance section."""
        articles = []
        seen_urls = set()
        
        selectors = [
            "h2 a",
            "h3 a",
            ".article-list a",
            ".news-item a",
        ]
        
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = str(elem.get('href', '') or '')
                    
                    if not title or len(title) < 10:
                        continue
                    
                    if url and not url.startswith('http'):
                        url = self._normalize_url(url, self.BASE_URL)
                    
                    if not url or url in seen_urls:
                        continue
                    
                    # Filter for article links
                    if '.html' in url and not any(skip in url for skip in [
                        '/photo/', '/video/', '/infographics/'
                    ]):
                        seen_urls.add(url)
                        articles.append({
                            "title": title,
                            "url": url,
                            "mobileUrl": ""
                        })
            except Exception:
                continue
        
        return articles[:50]


class VietnamFinanceNganHangScraper(BaseScraper):
    """Scraper for VietnamFinance banking section."""
    
    BASE_URL = "https://vietnamfinance.vn"
    
    def __init__(self):
        super().__init__(
            source_id="vietnamfinance-nganhang",
            source_name="VietnamFinance Ngân Hàng"
        )
    
    def get_url(self) -> str:
        return f"{self.BASE_URL}/ngan-hang/"
    
    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamFinance banking section."""
        articles = []
        seen_urls = set()
        
        selectors = [
            "h2 a",
            "h3 a",
            ".news-item a",
        ]
        
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = str(elem.get('href', '') or '')
                    
                    if not title or len(title) < 10:
                        continue
                    
                    if url and not url.startswith('http'):
                        url = self._normalize_url(url, self.BASE_URL)
                    
                    if not url or url in seen_urls:
                        continue
                    
                    if '.html' in url:
                        seen_urls.add(url)
                        articles.append({
                            "title": title,
                            "url": url,
                            "mobileUrl": ""
                        })
            except Exception:
                continue
        
        return articles[:50]


class VietnamFinanceBatDongSanScraper(BaseScraper):
    """Scraper for VietnamFinance real estate section."""
    
    BASE_URL = "https://vietnamfinance.vn"
    
    def __init__(self):
        super().__init__(
            source_id="vietnamfinance-batdongsan",
            source_name="VietnamFinance Bất Động Sản"
        )
    
    def get_url(self) -> str:
        return f"{self.BASE_URL}/bat-dong-san/"
    
    def parse_articles(self, soup: BeautifulSoup) -> List[Dict]:
        """Parse articles from VietnamFinance real estate section."""
        articles = []
        seen_urls = set()
        
        selectors = [
            "h2 a",
            "h3 a",
            ".article-list a",
        ]
        
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    title = self._clean_title(elem.get_text())
                    url = str(elem.get('href', '') or '')
                    
                    if not title or len(title) < 10:
                        continue
                    
                    if url and not url.startswith('http'):
                        url = self._normalize_url(url, self.BASE_URL)
                    
                    if not url or url in seen_urls:
                        continue
                    
                    if '.html' in url:
                        seen_urls.add(url)
                        articles.append({
                            "title": title,
                            "url": url,
                            "mobileUrl": ""
                        })
            except Exception:
                continue
        
        return articles[:50]

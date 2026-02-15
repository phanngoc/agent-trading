"""
Vietnamese news scrapers package.

This package contains scrapers for Vietnamese financial news sources.
"""

from .base_scraper import BaseScraper
from .cafef_scraper import CafeFScraper, CafeFChungKhoanScraper
from .vnexpress_scraper import VnExpressKinhDoanhScraper, VnExpressChungKhoanScraper
from .dantri_scraper import DanTriKinhDoanhScraper
from .money24h_scraper import Money24HScraper
from .vietnamfinance_scraper import (
    VietnamFinanceScraper,
    VietnamFinanceTaiChinhScraper,
    VietnamFinanceNganHangScraper,
    VietnamFinanceBatDongSanScraper,
)

# Registry of all available Vietnam scrapers
VIETNAM_SCRAPERS = {
    "cafef": CafeFScraper,
    "cafef-chungkhoan": CafeFChungKhoanScraper,
    "vnexpress-kinhdoanh": VnExpressKinhDoanhScraper,
    "vnexpress-chungkhoan": VnExpressChungKhoanScraper,
    "dantri-kinhdoanh": DanTriKinhDoanhScraper,
    "24hmoney": Money24HScraper,
    "vietnamfinance": VietnamFinanceScraper,
    "vietnamfinance-taichinh": VietnamFinanceTaiChinhScraper,
    "vietnamfinance-nganhang": VietnamFinanceNganHangScraper,
    "vietnamfinance-batdongsan": VietnamFinanceBatDongSanScraper,
}

__all__ = [
    "BaseScraper",
    "CafeFScraper",
    "CafeFChungKhoanScraper",
    "VnExpressKinhDoanhScraper",
    "VnExpressChungKhoanScraper",
    "DanTriKinhDoanhScraper",
    "Money24HScraper",
    "VietnamFinanceScraper",
    "VietnamFinanceTaiChinhScraper",
    "VietnamFinanceNganHangScraper",
    "VietnamFinanceBatDongSanScraper",
    "VIETNAM_SCRAPERS",
]

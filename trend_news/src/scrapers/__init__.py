"""
Vietnamese news scrapers package.

This package contains scrapers for Vietnamese financial news sources.
"""

from .base_scraper import BaseScraper
from .cafef_scraper import CafeFScraper, CafeFChungKhoanScraper, CafeFDoanhNghiepScraper
from .vnexpress_scraper import VnExpressKinhDoanhScraper, VnExpressChungKhoanScraper
from .dantri_scraper import DanTriKinhDoanhScraper
from .money24h_scraper import Money24HScraper
from .vietnamfinance_scraper import (
    VietnamFinanceScraper,
    VietnamFinanceTaiChinhScraper,
    VietnamFinanceNganHangScraper,
    VietnamFinanceBatDongSanScraper,
)
from .vneconomy_scraper import (
    VnEconomyChungKhoanScraper,
    VnEconomyTaiChinhScraper,
    VnEconomyDoanhNghiepScraper,
)
from .tinnhanhchungkhoan_scraper import (
    TinNhanhChungKhoanScraper,
    TinNhanhChungKhoanNhanDinhScraper,
    TinNhanhChungKhoanDoanhNghiepScraper,
)
from .vietnambiz_scraper import (
    VietnamBizChungKhoanScraper,
    VietnamBizDoanhNghiepScraper,
    VietnamBizNganHangScraper,
)
from .baodautu_scraper import (
    BaoDauTuTaiChinhScraper,
    BaoDauTuChungKhoanScraper,
    BaoDauTuKinhDoanhScraper,
)

# Registry of all available Vietnam scrapers
VIETNAM_SCRAPERS = {
    # CafeF - Tài chính cá nhân & Chứng khoán
    "cafef": CafeFScraper,
    "cafef-chungkhoan": CafeFChungKhoanScraper,
    "cafef-doanhnghiep": CafeFDoanhNghiepScraper,

    # VnExpress - Kinh doanh tổng hợp
    "vnexpress-kinhdoanh": VnExpressKinhDoanhScraper,
    "vnexpress-chungkhoan": VnExpressChungKhoanScraper,

    # DanTri - Kinh doanh tổng hợp
    "dantri-kinhdoanh": DanTriKinhDoanhScraper,

    # 24hMoney - Tài chính & Chứng khoán
    "24hmoney": Money24HScraper,

    # VietnamFinance - Tài chính & Ngân hàng
    "vietnamfinance": VietnamFinanceScraper,
    "vietnamfinance-taichinh": VietnamFinanceTaiChinhScraper,
    "vietnamfinance-nganhang": VietnamFinanceNganHangScraper,
    "vietnamfinance-batdongsan": VietnamFinanceBatDongSanScraper,

    # VnEconomy - Thời báo Kinh tế Việt Nam (uy tín cao)
    "vneconomy-chungkhoan": VnEconomyChungKhoanScraper,
    "vneconomy-taichinh": VnEconomyTaiChinhScraper,
    "vneconomy-doanhnghiep": VnEconomyDoanhNghiepScraper,

    # Tin Nhanh Chứng Khoán - Chuyên chứng khoán
    "tinnhanhchungkhoan": TinNhanhChungKhoanScraper,
    "tinnhanhchungkhoan-nhandinh": TinNhanhChungKhoanNhanDinhScraper,
    "tinnhanhchungkhoan-doanhnghiep": TinNhanhChungKhoanDoanhNghiepScraper,

    # VietnamBiz - Kinh doanh & Chứng khoán
    "vietnambiz-chungkhoan": VietnamBizChungKhoanScraper,
    "vietnambiz-doanhnghiep": VietnamBizDoanhNghiepScraper,
    "vietnambiz-nganhang": VietnamBizNganHangScraper,

    # Báo Đầu Tư - Tờ báo đầu tư chính thức (Bộ Tài chính)
    "baodautu-taichinh": BaoDauTuTaiChinhScraper,
    "baodautu-chungkhoan": BaoDauTuChungKhoanScraper,
    "baodautu-kinhdoanh": BaoDauTuKinhDoanhScraper,
}

__all__ = [
    "BaseScraper",
    # CafeF
    "CafeFScraper",
    "CafeFChungKhoanScraper",
    "CafeFDoanhNghiepScraper",
    # VnExpress
    "VnExpressKinhDoanhScraper",
    "VnExpressChungKhoanScraper",
    # DanTri
    "DanTriKinhDoanhScraper",
    # 24hMoney
    "Money24HScraper",
    # VietnamFinance
    "VietnamFinanceScraper",
    "VietnamFinanceTaiChinhScraper",
    "VietnamFinanceNganHangScraper",
    "VietnamFinanceBatDongSanScraper",
    # VnEconomy
    "VnEconomyChungKhoanScraper",
    "VnEconomyTaiChinhScraper",
    "VnEconomyDoanhNghiepScraper",
    # Tin Nhanh Chứng Khoán
    "TinNhanhChungKhoanScraper",
    "TinNhanhChungKhoanNhanDinhScraper",
    "TinNhanhChungKhoanDoanhNghiepScraper",
    # VietnamBiz
    "VietnamBizChungKhoanScraper",
    "VietnamBizDoanhNghiepScraper",
    "VietnamBizNganHangScraper",
    # Báo Đầu Tư
    "BaoDauTuTaiChinhScraper",
    "BaoDauTuChungKhoanScraper",
    "BaoDauTuKinhDoanhScraper",
    # Registry
    "VIETNAM_SCRAPERS",
]

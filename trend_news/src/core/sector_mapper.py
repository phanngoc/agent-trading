"""
VN Stock Sector Mapper

Maps tickers to sectors for sector-level sentiment aggregation.
Used by /api/v2/sectors/{sector} and batch signal endpoints.
"""
from typing import Dict, List, Optional

SECTOR_TICKERS: Dict[str, List[str]] = {
    "banking": [
        "VCB", "BID", "CTG", "TCB", "MBB", "VPB", "ACB", "HDB",
        "STB", "TPB", "VIB", "OCB", "MSB", "LPB", "SSB", "BAB",
    ],
    "real_estate": [
        "VIC", "VHM", "VRE", "NVL", "PDR", "KDH", "DXG", "NLG",
        "DIG", "KBC", "BCM", "AGG", "CEO", "HQC", "ITA",
    ],
    "energy": [
        "GAS", "PLX", "PVD", "PVS", "BSR", "OIL", "PVC", "PGS",
        "PGD", "PVB", "PTC",
    ],
    "steel": [
        "HPG", "HSG", "NKG", "TLH", "POM", "VGS", "TVN",
    ],
    "tech": [
        "FPT", "CMG", "ELC", "VGI", "ITD", "SAM",
    ],
    "retail": [
        "MWG", "PNJ", "DGW", "FRT", "AST",
    ],
    "food_beverage": [
        "VNM", "SAB", "MSN", "QNS", "KDC", "MCH",
    ],
    "aviation": [
        "HVN", "VJC", "ACV",
    ],
    "securities": [
        "SSI", "VND", "MBS", "HCM", "CTS", "SHS", "VCI", "BSI",
    ],
    "industrial": [
        "GVR", "PHR", "DPM", "DCM", "CSV", "BFC",
    ],
    "utilities": [
        "REE", "NT2", "POW", "PC1", "SHP", "GEG", "TBC",
    ],
    "logistics": [
        "GMD", "STG", "HAX", "VTP", "ITL",
    ],
}

# Reverse map: ticker → sector
TICKER_SECTOR: Dict[str, str] = {}
for sector, tickers in SECTOR_TICKERS.items():
    for t in tickers:
        TICKER_SECTOR[t] = sector

SECTOR_DISPLAY: Dict[str, str] = {
    "banking":       "Ngân hàng",
    "real_estate":   "Bất động sản",
    "energy":        "Dầu khí & Năng lượng",
    "steel":         "Thép",
    "tech":          "Công nghệ",
    "retail":        "Bán lẻ",
    "food_beverage": "Thực phẩm & Đồ uống",
    "aviation":      "Hàng không",
    "securities":    "Chứng khoán",
    "industrial":    "Công nghiệp",
    "utilities":     "Điện & Tiện ích",
    "logistics":     "Vận tải & Logistics",
}

def get_sector(ticker: str) -> Optional[str]:
    return TICKER_SECTOR.get(ticker.upper())

def get_sector_tickers(sector: str) -> List[str]:
    return SECTOR_TICKERS.get(sector.lower(), [])

def all_sectors() -> List[str]:
    return list(SECTOR_TICKERS.keys())

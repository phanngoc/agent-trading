"""
Vietnamese Stock Ticker Alias Mapper

Maps stock ticker symbols to related Vietnamese keywords for news search.
VIC → ['Vingroup', 'VIC', 'VIN', 'bất động sản', ...]
"""

from typing import Dict, List

# ---------------------------------------------------------------------------
# Ticker alias dictionary
# Keys: uppercase ticker symbol
# Values: list of Vietnamese/English aliases to search in news titles
# ---------------------------------------------------------------------------
TICKER_ALIASES: Dict[str, List[str]] = {
    # === Real Estate & Vingroup ecosystem ===
    "VIC": ["Vingroup", "VinGroup", "VIC", "tập đoàn Vin", "dòng tiền VIN", "nhóm VIN"],
    "VHM": ["VinHomes", "Vinhomes", "VHM", "Vingroup", "bất động sản Vin"],
    "VRE": ["Vincom Retail", "VRE", "trung tâm thương mại Vincom"],
    "NVL": ["Novaland", "Nova Land", "NVL", "bất động sản Nova"],
    "PDR": ["Phát Đạt", "PDR"],
    "KDH": ["Khang Điền", "KDH"],
    "DXG": ["Đất Xanh", "DXG"],
    "CII": ["CII", "Đầu tư Hạ tầng"],
    "SCR": ["SCR", "Đất Quảng"],
    "KBC": ["KBC", "Kinh Bắc"],
    "DPG": ["Đạt Phương", "DPG"],

    # === Banking ===
    "VCB": ["Vietcombank", "VCB", "Ngoại thương"],
    "BID": ["BIDV", "BID", "Đầu tư Phát triển"],
    "CTG": ["VietinBank", "CTG", "Công thương"],
    "TCB": ["Techcombank", "TCB"],
    "MBB": ["MB Bank", "MBB", "Quân đội"],
    "VPB": ["VPBank", "VPB"],
    "ACB": ["ACB", "Á Châu"],
    "STB": ["Sacombank", "STB"],
    "HDB": ["HDBank", "HDB"],
    "LPB": ["LienVietPostBank", "LPB", "Bưu Điện Liên Việt"],
    "TPB": ["TPBank", "TPB"],
    "MSB": ["Maritime Bank", "MSB"],
    "OCB": ["OCB", "Phương Đông"],
    "VIB": ["VIB", "Quốc Tế"],
    "EIB": ["Eximbank", "EIB", "Xuất nhập khẩu"],
    "SHB": ["SHB", "Sài Gòn Hà Nội"],
    "BAB": ["BAB", "Bắc Á"],
    "NAB": ["NAB", "Nam Á"],

    # === Oil & Gas ===
    "PLX": ["Petrolimex", "PLX", "xăng dầu"],
    "GAS": ["PetroVietnam Gas", "GAS", "PV Gas", "khí đốt"],
    "PVD": ["PV Drilling", "PVD", "khoan dầu"],
    "BSR": ["Bình Sơn", "BSR", "lọc dầu"],
    "OIL": ["PVOil", "OIL", "xăng dầu"],

    # === Steel & Materials ===
    "HPG": ["Hòa Phát", "HPG", "thép"],
    "HSG": ["Hoa Sen", "HSG", "tôn thép"],
    "NKG": ["Nam Kim", "NKG", "thép"],
    "SMC": ["SMC", "thép"],

    # === Aviation & Transport ===
    "HVN": ["Vietnam Airlines", "HVN", "hàng không"],
    "VJC": ["Vietjet", "VJC", "hàng không giá rẻ"],
    "ACV": ["Cảng hàng không", "ACV"],
    "GMD": ["Gemadept", "GMD", "cảng biển"],
    "HAH": ["HAH", "Hải An"],
    "DVP": ["DVP", "cảng Đình Vũ"],

    # === Technology & Telecom ===
    "FPT": ["FPT", "tập đoàn FPT", "công nghệ FPT"],
    "VGI": ["Viettel Global", "VGI"],
    "CMG": ["CMC", "CMG", "tập đoàn CMC"],
    "ELC": ["ELC", "Điện tử"],
    "SAM": ["SAM Holdings", "SAM"],

    # === Consumer & Retail ===
    "MWG": ["Mobile World", "Thế Giới Di Động", "MWG", "TGDĐ"],
    "FRT": ["FPT Retail", "FRT"],
    "MSN": ["Masan", "MSN", "tập đoàn Masan"],
    "VNM": ["Vinamilk", "VNM"],
    "SAB": ["Sabeco", "SAB", "bia Sài Gòn"],
    "QNS": ["Đường Quảng Ngãi", "QNS"],
    "KDC": ["Kinh Đô", "KDC"],

    # === Securities ===
    "SSI": ["SSI", "chứng khoán SSI"],
    "VCI": ["Viet Capital Securities", "VCI"],
    "HCM": ["chứng khoán HCM", "HSC"],
    "VND": ["VNDIRECT", "VND"],
    "MBS": ["MB Securities", "MBS"],
    "VIX": ["VIX Securities", "VIX", "chứng khoán VIX"],

    # === Utilities & Energy ===
    "REE": ["REE", "cơ điện lạnh"],
    "PC1": ["PC1", "điện"],
    "POW": ["PetroVietnam Power", "POW", "điện lực"],
    "GEX": ["Gelex", "GEX"],
    "EVF": ["EVF", "tài chính điện lực"],

    # === Agriculture ===
    "HAG": ["HAGL", "HAG", "Hoàng Anh Gia Lai"],
    "HNG": ["HAGL Agrico", "HNG"],
    "BAF": ["BAF", "chăn nuôi"],
    "DBC": ["Dabaco", "DBC"],
    "LSS": ["Mía đường Lam Sơn", "LSS"],

    # === Generic categories for broad search ===
    "BATDONGSAN": ["bất động sản", "nhà đất", "dự án", "chung cư", "đất nền"],
    "CHUNGKHOAN": ["chứng khoán", "cổ phiếu", "VN-Index", "thị trường"],
    "NGANHANG": ["ngân hàng", "tín dụng", "lãi suất", "cho vay"],
    "XANGDAU": ["xăng dầu", "dầu khí", "năng lượng"],
}

# Synonyms for generic sector queries
SECTOR_MAP: Dict[str, str] = {
    "realestate": "BATDONGSAN",
    "banking": "NGANHANG",
    "securities": "CHUNGKHOAN",
    "oilandgas": "XANGDAU",
    "bất động sản": "BATDONGSAN",
    "ngân hàng": "NGANHANG",
    "chứng khoán": "CHUNGKHOAN",
    "xăng dầu": "XANGDAU",
}


def get_aliases(ticker: str) -> List[str]:
    """
    Return list of search aliases for a ticker symbol.

    Falls back to [ticker] if not found in dictionary.

    Args:
        ticker: Stock ticker symbol (e.g., 'VIC', 'HPG')

    Returns:
        List of alias strings to search in news titles
    """
    ticker_upper = ticker.upper().strip()

    # Check sector synonyms first
    if ticker_upper.lower() in SECTOR_MAP:
        ticker_upper = SECTOR_MAP[ticker_upper.lower()]

    aliases = TICKER_ALIASES.get(ticker_upper)
    if aliases:
        return aliases

    # Fallback: return the ticker itself so at minimum it searches for exact match
    return [ticker]


def build_fts_match_query(tickers_str: str) -> str:
    """
    Build an FTS5 MATCH query string from comma-separated tickers.

    Each alias is quoted as a phrase so multi-word terms match exactly.
    Multiple aliases/tickers are joined with OR.

    Example:
        'VIC' → '"Vingroup" OR "VinGroup" OR "VIC" OR "tập đoàn Vin" ...'
        'VIC,HPG' → '"Vingroup" OR ... OR "Hòa Phát" OR "HPG" OR "thép"'

    Args:
        tickers_str: Comma-separated ticker symbols

    Returns:
        FTS5 MATCH expression string (empty string if no valid tickers)
    """
    parts: List[str] = []
    for ticker in tickers_str.split(","):
        ticker = ticker.strip()
        if not ticker:
            continue
        for alias in get_aliases(ticker):
            # Quote each alias as a phrase to handle multi-word terms and
            # special FTS5 characters. Escape internal double-quotes.
            safe = alias.replace('"', '""')
            parts.append(f'"{safe}"')

    return " OR ".join(parts)


def build_title_conditions(tickers_str: str) -> tuple[List[str], List[str]]:
    """
    Parse comma-separated tickers and build SQL LIKE conditions + params.

    Args:
        tickers_str: Comma-separated tickers, e.g. "VIC,HPG"

    Returns:
        (conditions, params) to inject into SQL WHERE clause
        conditions: list of SQL fragments like "title LIKE ?"
        params: list of values like ["%Vingroup%", ...]
    """
    conditions = []
    params = []

    for ticker in tickers_str.split(","):
        ticker = ticker.strip()
        if not ticker:
            continue

        aliases = get_aliases(ticker)
        for alias in aliases:
            conditions.append("title LIKE ?")
            params.append(f"%{alias}%")

    return conditions, params

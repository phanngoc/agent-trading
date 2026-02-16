"""
Vietnamese Stock Ticker Alias Mapper

Maps stock ticker symbols to related Vietnamese keywords for FTS5 news search.
Covers HSX (HOSE), HNX, and UPCOM listed companies.

VIC → ['Vingroup', 'VIC', 'tập đoàn Vin', 'dòng tiền VIN', 'nhóm VIN']
"""

from typing import Dict, List

# ---------------------------------------------------------------------------
# Ticker alias dictionary
# Keys: uppercase ticker symbol (no exchange suffix)
# Values: ordered list of Vietnamese/English search terms.
#         First entry = primary company name used in news headlines.
# ---------------------------------------------------------------------------
TICKER_ALIASES: Dict[str, List[str]] = {

    # =========================================================================
    # Real Estate & Construction
    # =========================================================================
    "VIC": ["Vingroup", "VIC", "tập đoàn Vin", "dòng tiền VIN", "nhóm VIN"],
    "VHM": ["Vinhomes", "VHM", "Vingroup", "bất động sản Vin"],
    "VRE": ["Vincom Retail", "VRE", "Vincom"],
    "NVL": ["Novaland", "Nova Land", "NVL", "bất động sản Nova"],
    "PDR": ["Phát Đạt", "PDR"],
    "KDH": ["Khang Điền", "KDH"],
    "DXG": ["Đất Xanh", "DXG", "Datxanh"],
    "DXS": ["Đất Xanh Services", "DXS"],
    "CII": ["CII", "Đầu tư Hạ tầng Kỹ thuật"],
    "SCR": ["Đất Quảng", "SCR"],
    "KBC": ["Kinh Bắc", "KBC"],
    "DPG": ["Đạt Phương", "DPG"],
    "NLG": ["Nam Long", "NLG"],
    "HDC": ["Phát triển Nhà Bà Rịa", "HDC"],
    "HBC": ["Xây dựng Hoà Bình", "HBC"],
    "CTD": ["Coteccons", "CTD", "Cotec"],
    "LDG": ["LDG", "Đầu tư LDG"],
    "AGG": ["An Gia", "AGG"],
    "DIG": ["DIC Corp", "DIG"],
    "IDC": ["Viglacera", "IDC"],
    "BCM": ["Bình Dương", "BCM", "Becamex"],
    "CEO": ["CEO Group", "CEO", "C.E.O"],
    "HQC": ["Hoàng Quân", "HQC"],
    "ITA": ["Tân Tạo", "ITA"],
    "SGR": ["Đầu tư Saigon", "SGR"],
    "SZC": ["KCN Sonadezi", "SZC"],
    "TDC": ["Kinh doanh Nhà Bình Dương", "TDC"],

    # =========================================================================
    # Banking
    # =========================================================================
    "VCB": ["Vietcombank", "VCB", "Ngân hàng Ngoại thương"],
    "BID": ["BIDV", "BID", "Ngân hàng Đầu tư Phát triển"],
    "CTG": ["VietinBank", "CTG", "Ngân hàng Công thương"],
    "TCB": ["Techcombank", "TCB"],
    "MBB": ["MB Bank", "MBB", "Ngân hàng Quân đội"],
    "VPB": ["VPBank", "VPB"],
    "ACB": ["ACB", "Ngân hàng Á Châu"],
    "STB": ["Sacombank", "STB"],
    "HDB": ["HDBank", "HDB"],
    "LPB": ["LienVietPostBank", "LPB", "Ngân hàng Bưu Điện Liên Việt"],
    "TPB": ["TPBank", "TPB"],
    "MSB": ["Maritime Bank", "MSB", "Hàng hải"],
    "OCB": ["OCB", "Phương Đông"],
    "VIB": ["VIB", "Ngân hàng Quốc Tế"],
    "EIB": ["Eximbank", "EIB", "Ngân hàng Xuất nhập khẩu"],
    "SHB": ["SHB", "Ngân hàng Sài Gòn Hà Nội"],
    "BAB": ["BAB", "Ngân hàng Bắc Á"],
    "NAB": ["NAB", "Ngân hàng Nam Á"],
    "PGB": ["PGBank", "PGB"],
    "VAB": ["VietABank", "VAB"],
    "BVB": ["BVBank", "BVB"],
    "KLB": ["Kienlongbank", "KLB"],
    "SSB": ["SeABank", "SSB"],
    "ABB": ["ABBank", "ABB"],
    "NVB": ["NCB", "NVB", "Ngân hàng Quốc dân"],
    "VBB": ["VietBank", "VBB"],
    "BFC": ["Phân bón Bình Điền", "BFC"],   # same code, different sector
    "SGN": ["Sài Gòn", "SGN"],
    "VDB": ["VDB", "Phát triển Việt Nam"],

    # =========================================================================
    # Oil, Gas & Energy
    # =========================================================================
    "PLX": ["Petrolimex", "PLX", "xăng dầu Petrolimex"],
    "GAS": ["PV Gas", "GAS", "PetroVietnam Gas", "khí đốt"],
    "PVD": ["PV Drilling", "PVD", "khoan dầu khí"],
    "BSR": ["Bình Sơn", "BSR", "lọc dầu Bình Sơn"],
    "OIL": ["PVOil", "OIL", "dầu nhớt"],
    "PVS": ["PetroVietnam Services", "PVS", "dịch vụ dầu khí"],
    "PVB": ["PV Power", "PVB"],
    "PVT": ["PVTrans", "PVT", "vận tải dầu khí"],
    "POW": ["PetroVietnam Power", "POW", "điện lực dầu khí"],
    "PGD": ["Gas Petrolimex", "PGD"],
    "PVC": ["Vinaconex Petro", "PVC"],
    "PGC": ["Gas Petrolimex", "PGC"],
    "COM": ["Miennam Petro", "COM"],

    # =========================================================================
    # Steel, Mining & Materials
    # =========================================================================
    "HPG": ["Hòa Phát", "Hoa Phat", "HPG", "thép Hòa Phát"],
    "HSG": ["Hoa Sen", "HSG", "tôn thép Hoa Sen"],
    "NKG": ["Nam Kim", "NKG", "thép Nam Kim"],
    "SMC": ["SMC", "thép SMC"],
    "TLH": ["Thép Tiến Lên", "TLH"],
    "TVN": ["Thép Việt Nam", "TVN", "VNSTEEL"],
    "VGS": ["Thép Việt Ý", "VGS"],
    "POM": ["Thép Pomina", "POM"],
    "DTL": ["Thép Đình Vũ", "DTL"],
    "KMT": ["Kim khí miền Trung", "KMT"],
    "TIS": ["Thép Tisco", "TIS"],
    "VIS": ["Thép Việt Ý", "VIS"],

    # =========================================================================
    # Aviation & Transport
    # =========================================================================
    "HVN": ["Vietnam Airlines", "HVN", "hàng không quốc gia"],
    "VJC": ["Vietjet", "VJC", "Vietjet Air", "hàng không Vietjet"],
    "ACV": ["Cảng hàng không", "ACV", "Airports Corporation"],
    "GMD": ["Gemadept", "GMD", "cảng biển Gemadept"],
    "HAH": ["Hải An", "HAH", "vận tải Hải An"],
    "DVP": ["Cảng Đình Vũ", "DVP"],
    "SGP": ["Cảng Sài Gòn", "SGP"],
    "PHP": ["Cảng Hải Phòng", "PHP"],
    "VTO": ["Vinalines", "VTO", "vận tải biển Vinalines"],
    "VNA": ["Vinalines", "VNA"],
    "TCL": ["Transimex", "TCL"],
    "STG": ["Sotrans", "STG"],
    "CTO": ["Vận tải ô tô số 3", "CTO"],
    "VCG": ["Vinaconex", "VCG"],
    "PTB": ["Phú Tài", "PTB"],

    # =========================================================================
    # Technology & Telecommunications
    # =========================================================================
    "FPT": ["FPT", "tập đoàn FPT", "công nghệ FPT"],
    "VGI": ["Viettel Global", "VGI"],
    "CMG": ["CMC", "CMG", "tập đoàn CMC"],
    "ELC": ["Điện tử Bình Hòa", "ELC"],
    "SAM": ["SAM Holdings", "SAM"],
    "ITD": ["Tín Nghĩa", "ITD"],
    "SIS": ["Sản xuất Kinh doanh Xuất nhập khẩu", "SIS"],
    "VTC": ["VTC", "Viễn thông"],
    "ICT": ["Công nghệ thông tin", "ICT"],
    "SGT": ["Saigon Technology", "SGT"],

    # =========================================================================
    # Consumer, Retail & FMCG
    # =========================================================================
    "MWG": ["Mobile World", "Thế Giới Di Động", "MWG", "TGDĐ"],
    "FRT": ["FPT Retail", "FRT", "Long Châu"],
    "MSN": ["Masan", "MSN", "tập đoàn Masan"],
    "VNM": ["Vinamilk", "VNM", "sữa Vinamilk"],
    "SAB": ["Sabeco", "SAB", "bia Sài Gòn", "Sabecco"],
    "QNS": ["Đường Quảng Ngãi", "QNS"],
    "KDC": ["Kinh Đô", "KDC", "Kido"],
    "MCH": ["Masan Consumer", "MCH"],
    "VHC": ["Vĩnh Hoàn", "VHC", "cá tra Vĩnh Hoàn"],
    "ANV": ["Nam Việt", "ANV", "cá tra Nam Việt"],
    "IDI": ["IDI", "Tập đoàn Sao Mai"],
    "MML": ["MML", "Masan MEATLife"],
    "HAG": ["HAGL", "HAG", "Hoàng Anh Gia Lai"],
    "HNG": ["HAGL Agrico", "HNG", "nông nghiệp HAGL"],
    "DBC": ["Dabaco", "DBC", "chăn nuôi Dabaco"],
    "BAF": ["BAF", "Nông nghiệp BAF"],
    "LSS": ["Mía đường Lam Sơn", "LSS"],
    "SBT": ["TTC Sugar", "SBT", "đường TTC"],
    "VCF": ["Vinacafé", "VCF"],
    "ABT": ["Xuất nhập khẩu Thuỷ sản Bến Tre", "ABT"],
    "CMX": ["Cà Mau Seafood", "CMX"],
    "ACL": ["Thủy sản Cửu Long", "ACL"],

    # =========================================================================
    # Securities & Finance
    # =========================================================================
    "SSI": ["SSI", "chứng khoán SSI"],
    "VCI": ["Viet Capital Securities", "VCI", "chứng khoán Bản Việt"],
    "HCM": ["HSC", "chứng khoán HCM"],
    "VND": ["VNDIRECT", "VND", "chứng khoán VNDirect"],
    "MBS": ["MB Securities", "MBS", "chứng khoán MB"],
    "VIX": ["VIX Securities", "VIX", "chứng khoán VIX"],
    "CTS": ["Ngân hàng Công thương Securities", "CTS"],
    "AGR": ["Agribank Securities", "AGR"],
    "BVS": ["Bảo Việt Securities", "BVS"],
    "ART": ["Artex", "ART"],
    "FTS": ["Fili", "FTS"],
    "ORS": ["Orientsec", "ORS"],
    "BSI": ["BSI", "chứng khoán BSI"],
    "TVB": ["Thiên Việt Securities", "TVB"],
    "VFS": ["Chứng khoán VIFS", "VFS"],
    "SHS": ["Sài Gòn Hà Nội Securities", "SHS"],
    "VDS": ["Rồng Việt Securities", "VDS"],

    # =========================================================================
    # Utilities & Power
    # =========================================================================
    "REE": ["REE", "cơ điện lạnh REE"],
    "PC1": ["PC1", "điện lực miền Bắc"],
    "GEX": ["Gelex", "GEX", "tập đoàn Gelex"],
    "EVF": ["EVF", "Tài chính Điện lực"],
    "NT2": ["Nhiệt điện Phú Mỹ", "NT2"],
    "PPC": ["Nhiệt điện Phả Lại", "PPC"],
    "VSH": ["Thủy điện Vĩnh Sơn", "VSH"],
    "TBC": ["Thủy điện Thác Bà", "TBC"],
    "SBA": ["Thủy điện Sông Ba", "SBA"],
    "HND": ["Nhiệt điện Hà Nam", "HND"],
    "GEG": ["Điện Gia Lai", "GEG"],
    "TLT": ["Thủy điện Miền Trung", "TLT"],
    "CHP": ["Thủy điện Miền Trung", "CHP"],
    "SRC": ["Thủy điện", "SRC"],
    "VEA": ["Tổng Công ty Máy Động lực", "VEA"],

    # =========================================================================
    # Pharmaceuticals & Healthcare
    # =========================================================================
    "DHG": ["Dược Hậu Giang", "DHG"],
    "IMP": ["Imexpharm", "IMP"],
    "DMC": ["Dược phẩm Trung ương", "DMC"],
    "TRA": ["Traphaco", "TRA"],
    "DBD": ["Dược Bình Định", "DBD"],
    "AMV": ["Sản xuất Kinh doanh Dược phẩm", "AMV"],
    "DVN": ["Dược Việt Nam", "DVN", "Vimedimex"],

    # =========================================================================
    # Insurance
    # =========================================================================
    "BVH": ["Bảo Việt", "BVH", "Tập đoàn Bảo Việt"],
    "PTI": ["Bảo hiểm Bưu điện", "PTI"],
    "BMI": ["Bảo Minh", "BMI"],
    "BIC": ["Bảo hiểm BIDV", "BIC"],

    # =========================================================================
    # Textiles & Garments
    # =========================================================================
    "TCM": ["Dệt may Thành Công", "TCM"],
    "TNG": ["Đầu tư Thương mại TNG", "TNG"],
    "GIL": ["Dệt Gia Định", "GIL"],
    "STK": ["Sợi Thế Kỷ", "STK"],
    "MSH": ["May Sông Hồng", "MSH"],
    "VGT": ["Vinatex", "VGT", "Dệt may Việt Nam"],
    "EVE": ["Everpia", "EVE"],

    # =========================================================================
    # Rubber & Tyre
    # =========================================================================
    "DRC": ["Cao su Đà Nẵng", "DRC"],
    "CSM": ["Casumina", "CSM", "cao su miền Nam"],
    "SRC2": ["Cao su Sao vàng", "SRC2"],
    "PHR": ["Cao su Phước Hòa", "PHR"],
    "TRC": ["Cao su Tây Ninh", "TRC"],
    "DPR": ["Cao su Đồng Phú", "DPR"],
    "GVR": ["Tập đoàn Cao su Việt Nam", "GVR"],

    # =========================================================================
    # Fertiliser & Chemicals
    # =========================================================================
    "DCM": ["Phân bón Cà Mau", "DCM", "đạm Cà Mau"],
    "DPM": ["Đạm Phú Mỹ", "DPM", "PetroVietnam Fertilizer"],
    "LAS": ["Phân bón miền Nam", "LAS"],
    "BFC": ["Phân bón Bình Điền", "BFC"],
    "DDV": ["DAP Vinachem", "DDV"],
    "CSV": ["Hóa chất Việt Nam", "CSV"],

    # =========================================================================
    # Logistics & Warehousing
    # =========================================================================
    "TMS": ["Transimex", "TMS", "kho vận Hàng hải"],
    "SFI": ["Đại lý Hàng hải Việt Nam", "SFI"],
    "VTP": ["Viettel Post", "VTP"],
    "EMS": ["EMS", "Vietnam Post Express"],

    # =========================================================================
    # Sector / Theme Keywords
    # =========================================================================
    "BATDONGSAN": ["bất động sản", "nhà đất", "dự án", "chung cư", "đất nền", "thị trường nhà đất"],
    "CHUNGKHOAN": ["chứng khoán", "cổ phiếu", "VN-Index", "thị trường chứng khoán", "HNX-Index"],
    "NGANHANG": ["ngân hàng", "tín dụng", "lãi suất", "cho vay", "NHNN", "Ngân hàng Nhà nước"],
    "XANGDAU": ["xăng dầu", "dầu khí", "năng lượng", "dầu mỏ"],
    "THEP": ["thép", "sắt thép", "thị trường thép"],
    "NONGSAN": ["nông nghiệp", "nông sản", "lúa gạo", "thuỷ sản", "chăn nuôi"],
    "DETMAY": ["dệt may", "may mặc", "xuất khẩu dệt may"],
    "CONGNGHE": ["công nghệ", "phần mềm", "số hóa", "AI", "chuyển đổi số"],
    "HANGKHONG": ["hàng không", "hàng không giá rẻ", "sân bay"],
    "DUOC": ["dược phẩm", "y tế", "bệnh viện", "thuốc"],
    "DIEN": ["điện", "năng lượng tái tạo", "điện mặt trời", "điện gió", "thủy điện"],
    "BAOHINH": ["bảo hiểm", "tái bảo hiểm"],
    "XAYDUNG": ["xây dựng", "vật liệu xây dựng", "xi măng"],
}

# ---------------------------------------------------------------------------
# Sector synonym map (English → sector key)
# ---------------------------------------------------------------------------
SECTOR_MAP: Dict[str, str] = {
    # English sector names
    "realestate": "BATDONGSAN",
    "banking": "NGANHANG",
    "securities": "CHUNGKHOAN",
    "oilandgas": "XANGDAU",
    "steel": "THEP",
    "agriculture": "NONGSAN",
    "textile": "DETMAY",
    "technology": "CONGNGHE",
    "aviation": "HANGKHONG",
    "pharma": "DUOC",
    "power": "DIEN",
    "insurance": "BAOHINH",
    "construction": "XAYDUNG",
    # Vietnamese sector names
    "bất động sản": "BATDONGSAN",
    "ngân hàng": "NGANHANG",
    "chứng khoán": "CHUNGKHOAN",
    "xăng dầu": "XANGDAU",
    "thép": "THEP",
    "nông sản": "NONGSAN",
    "dệt may": "DETMAY",
    "công nghệ": "CONGNGHE",
    "hàng không": "HANGKHONG",
    "dược phẩm": "DUOC",
    "điện": "DIEN",
    "bảo hiểm": "BAOHINH",
    "xây dựng": "XAYDUNG",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_aliases(ticker: str) -> List[str]:
    """
    Return search aliases for a ticker or sector keyword.

    Strips exchange suffixes (.VN, .HNX) before lookup.
    Falls back to [ticker] if not found.

    Args:
        ticker: Stock ticker (e.g. 'VIC', 'VIC.VN', 'HPG') or sector keyword

    Returns:
        List of alias strings for FTS5 / LIKE search
    """
    # Strip exchange suffix (.VN, .HNX, .UPCOM, etc.)
    clean = ticker.upper().split(".")[0].strip()

    # Check sector synonym map first (handles English sector names)
    sector_key = SECTOR_MAP.get(clean.lower())
    if sector_key:
        clean = sector_key
    else:
        # Also try the original lower-case Vietnamese key
        sector_key = SECTOR_MAP.get(ticker.lower().strip())
        if sector_key:
            clean = sector_key

    aliases = TICKER_ALIASES.get(clean)
    if aliases:
        return aliases

    # Fallback: return ticker itself
    return [ticker.split(".")[0].upper()]


def build_fts_match_query(tickers_str: str) -> str:
    """
    Build an FTS5 MATCH query string from comma-separated tickers.

    Each alias is quoted as a phrase so multi-word terms match exactly.
    Multiple aliases/tickers are combined with OR.

    Example:
        'VIC'     → '"Vingroup" OR "VIC" OR "tập đoàn Vin" ...'
        'VIC,HPG' → '"Vingroup" OR ... OR "Hòa Phát" OR "HPG" OR "thép Hòa Phát"'

    Args:
        tickers_str: Comma-separated ticker symbols

    Returns:
        FTS5 MATCH expression string, empty string if no valid tickers
    """
    parts: List[str] = []
    for ticker in tickers_str.split(","):
        ticker = ticker.strip()
        if not ticker:
            continue
        for alias in get_aliases(ticker):
            safe = alias.replace('"', '""')
            parts.append(f'"{safe}"')

    return " OR ".join(parts)


def build_title_conditions(tickers_str: str) -> tuple[List[str], List[str]]:
    """
    Build SQL LIKE conditions and params from comma-separated tickers.

    Fallback for environments where FTS5 is unavailable.

    Args:
        tickers_str: Comma-separated tickers, e.g. 'VIC,HPG'

    Returns:
        (conditions, params) to inject into SQL WHERE clause
    """
    conditions: List[str] = []
    params: List[str] = []

    for ticker in tickers_str.split(","):
        ticker = ticker.strip()
        if not ticker:
            continue
        for alias in get_aliases(ticker):
            conditions.append("title LIKE ?")
            params.append(f"%{alias}%")

    return conditions, params


def list_supported_tickers() -> List[str]:
    """Return sorted list of all supported ticker symbols."""
    return sorted(k for k in TICKER_ALIASES if not k.isupper() or len(k) <= 6)

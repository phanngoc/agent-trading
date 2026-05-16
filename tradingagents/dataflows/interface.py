from typing import Annotated
import re

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .trend_news_api import get_news as get_trend_news, get_global_news as get_trend_global_news
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# vnstock provider for Vietnamese stocks
from .vnstock_api import (
    get_stock_data as get_vnstock_stock_data,
    get_indicators as get_vnstock_indicators,
    get_fundamentals as get_vnstock_fundamentals,
    get_balance_sheet as get_vnstock_balance_sheet,
    get_cashflow as get_vnstock_cashflow,
    get_income_statement as get_vnstock_income_statement,
    get_insider_transactions as get_vnstock_insider_transactions,
    get_news as get_vnstock_news,
    is_vn_ticker,
)

# Configuration and routing logic
from .config import get_config

# VN ticker pattern: 2-4 uppercase letters, optionally ending in .VN
_VN_TICKER_RE = re.compile(r'^[A-Z]{2,3}(\.VN)?$')

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "trend_news",
    "vnstock",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "vnstock": get_vnstock_stock_data,
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
    },
    # technical_indicators
    "get_indicators": {
        "vnstock": get_vnstock_indicators,
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
    },
    # fundamental_data
    "get_fundamentals": {
        "vnstock": get_vnstock_fundamentals,
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
    },
    "get_balance_sheet": {
        "vnstock": get_vnstock_balance_sheet,
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
    },
    "get_cashflow": {
        "vnstock": get_vnstock_cashflow,
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
    },
    "get_income_statement": {
        "vnstock": get_vnstock_income_statement,
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
    },
    # news_data
    "get_news": {
        "vnstock": get_vnstock_news,
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "trend_news": get_trend_news,
    },
    "get_global_news": {
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "trend_news": get_trend_global_news,
    },
    "get_insider_transactions": {
        "vnstock": get_vnstock_insider_transactions,
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
    },
}

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

# Soft-failure patterns: many vendor wrappers return an error-prefixed
# *string* instead of raising (legacy convention, hard to refactor). The
# router treats these as fallback triggers so a stopped trend_news server
# or a broken vnstock source doesn't poison the whole call — we keep trying
# the next vendor, and only surface the last result if every vendor failed.
import re as _re
_SOFT_FAIL_PATTERN = _re.compile(
    r"^\s*("
    r"vnstock\s+error|"
    r"trend_news\s+API|"
    r"(api|connection)\s+error|"
    r"connection\s+refused|"
    r"(server|service)\s+(is\s+)?(not\s+)?(currently\s+)?(running|available)|"
    r"no\s+vendor|"
    r"error\s+fetching"
    r")",
    _re.IGNORECASE,
)


def _looks_like_failure(result) -> bool:
    """Heuristic: treat known vendor error-strings as soft failures."""
    if result is None:
        return True
    if isinstance(result, str):
        if not result.strip():
            return True
        return bool(_SOFT_FAIL_PATTERN.search(result))
    return False


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support.

    Fallback triggers:
      - AlphaVantageRateLimitError (explicit rate-limit)
      - any other exception from the vendor impl
      - **string return values matching the soft-failure pattern**
        (vnstock returns "vnstock error fetching news for VIC: ..." on
        upstream API breaks; trend_news_api returns "...not currently
        running..." when the server is down)

    Auto-detection: if the first positional arg looks like a VN stock
    (2-4 uppercase letters, optionally ending in .VN), vnstock is injected
    at the front of the vendor chain regardless of config.
    """
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    if args and isinstance(args[0], str) and is_vn_ticker(args[0]):
        if "vnstock" in VENDOR_METHODS[method] and "vnstock" not in primary_vendors:
            primary_vendors = ["vnstock"] + primary_vendors

    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    # Collect every attempt so we can surface a meaningful diagnostic if
    # every vendor failed (rather than masking the chain with a generic
    # "no vendor available" error). Last successful-looking result wins.
    attempts: list[tuple[str, str]] = []
    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue
        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            result = impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError as e:
            attempts.append((vendor, f"rate-limit: {e}"))
            continue
        except Exception as e:  # noqa: BLE001 — every exception triggers fallback
            attempts.append((vendor, f"{type(e).__name__}: {e}"))
            continue

        if _looks_like_failure(result):
            attempts.append((vendor, f"soft-fail: {str(result)[:120]}"))
            continue
        return result

    # No vendor produced data — return a combined diagnostic. We return a
    # string (not raise) so calling tools see degraded-but-usable output;
    # the agent prompt instructs them to flag missing data caveats.
    summary = "; ".join(f"{v}: {msg}" for v, msg in attempts) or "no vendors configured"
    return f"[{method}] all vendors failed for args={args}: {summary}"
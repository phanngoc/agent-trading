"""
vnstock_api.py — VNStock data provider for Vietnamese stocks (HOSE/HNX/UPCOM).

Drop-in replacement for yfinance methods for VN tickers.
Exposes the same function signatures used in interface.py VENDOR_METHODS.
"""

import os
import re
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Annotated

from .stockstats_utils import _clean_dataframe
from .config import get_config

# ── Helpers ────────────────────────────────────────────────────────────────────

_VN_TICKER_RE = re.compile(r'^[A-Z]{2,3}(\.VN)?$')

def is_vn_ticker(symbol: str) -> bool:
    """Return True if symbol looks like a Vietnamese stock ticker."""
    clean = symbol.upper().strip()
    return bool(_VN_TICKER_RE.match(clean))

def clean_symbol(symbol: str) -> str:
    """Strip .VN suffix — vnstock uses bare 3-letter codes."""
    return symbol.upper().replace('.VN', '').strip()

# Source fallback order for company-level data (news, overview, insider_deals).
# VCI's company endpoint started returning a payload without the 'data' key
# in late-2026 (KeyError: 'data' on Company.__init__); KBS still serves the
# same fields.
_COMPANY_SOURCES: tuple[str, ...] = ("KBS", "VCI")

# Source fallback chain used by the price/indicator routes only. VCI
# stays the default because its ``Finance`` API is the only one whose
# method signatures match what the fundamentals routes call (KBS's
# ``Finance`` rejects ``lang='en'`` and 404s on ratio/balance_sheet —
# so reusing this list for fundamentals would regress every working
# ticker). KBS is the fallback for tickers like TCB where VCI's
# ``Company`` payload is malformed and eagerly fails Stock construction.
_PRICE_SOURCES: tuple[str, ...] = ("VCI", "KBS")


def _get_stock_obj(symbol: str, source: str = 'VCI'):
    """Create and return a vnstock Stock object on a specific source."""
    from vnstock import Vnstock
    return Vnstock().stock(symbol=clean_symbol(symbol), source=source)


def _get_stock_obj_with_fallback(
    symbol: str,
    sources: tuple[str, ...] = _PRICE_SOURCES,
):
    """Construct a Stock object, trying each source in order.

    Used by the price / indicator routes where any source's
    ``quote.history`` works once construction succeeds. Re-raises the
    last error if every source fails so callers fall through to their
    existing exception-to-soft-fail path.
    """
    from vnstock import Vnstock
    sym = clean_symbol(symbol)
    last_err: Exception | None = None
    for src in sources:
        try:
            return Vnstock().stock(symbol=sym, source=src)
        except Exception as e:  # noqa: BLE001 — try every source
            last_err = e
            continue
    assert last_err is not None  # loop is non-empty so this is unreachable
    raise last_err


def _get_company_with_fallback(symbol: str):
    """Yield (source, stock_obj) tuples until Company construction succeeds.

    Constructing ``Vnstock().stock(...)`` eagerly builds the per-source
    Company helper, so a broken upstream API surfaces here as a KeyError
    rather than later. The caller iterates and picks the first source that
    actually returns data.
    """
    from vnstock import Vnstock
    sym = clean_symbol(symbol)
    last_err: Exception | None = None
    for src in _COMPANY_SOURCES:
        try:
            obj = Vnstock().stock(symbol=sym, source=src)
            # Touch a cheap attribute to force lazy validation paths.
            _ = obj.company.SUPPORTED_SOURCES if hasattr(obj.company, "SUPPORTED_SOURCES") else None
            yield src, obj
        except Exception as e:  # noqa: BLE001 — we want to try every source
            last_err = e
            continue
    if last_err is not None:
        raise last_err


# ── Price data ─────────────────────────────────────────────────────────────────

def get_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Fetch OHLCV price history from vnstock (VCI source).
    Returns CSV string compatible with yfinance output format.
    """
    sym = clean_symbol(symbol)
    try:
        s = _get_stock_obj_with_fallback(sym)
        df = s.quote.history(start=start_date, end=end_date, interval='1D')
    except Exception as e:
        return f"vnstock error fetching price data for {sym}: {e}"

    if df is None or df.empty:
        return f"No data found for {sym} between {start_date} and {end_date}"

    # Normalize column names to match yfinance convention
    col_map = {
        'time': 'Date',
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'volume': 'Volume',
    }
    df = df.rename(columns=col_map)
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date')

    # Cap to last 90 trading days
    MAX_ROWS = 90
    if len(df) > MAX_ROWS:
        df = df.tail(MAX_ROWS)

    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
    df = df.set_index('Date')

    header = f"# VNStock data for {sym} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(df)}\n"
    header += f"# Source: VCI\n\n"
    return header + df.to_csv()


# ── Technical indicators (via stockstats on vnstock data) ──────────────────────

def get_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 90,
) -> str:
    """
    Calculate technical indicators using stockstats on vnstock price data.
    Mirrors the yfinance get_stock_stats_indicators_window signature.
    """
    from stockstats import wrap
    from .y_finance import get_stock_stats_indicators_window as _yf_indicators

    sym = clean_symbol(symbol)
    config = get_config()
    os.makedirs(config["data_cache_dir"], exist_ok=True)

    curr_date_dt = pd.to_datetime(curr_date)
    start_date_dt = curr_date_dt - pd.DateOffset(days=look_back_days + 300)  # extra buffer for SMA200
    start_str = start_date_dt.strftime('%Y-%m-%d')
    end_str = curr_date_dt.strftime('%Y-%m-%d')

    cache_file = os.path.join(
        config["data_cache_dir"],
        f"{sym}-vnstock-{start_str}-{end_str}.csv"
    )

    if os.path.exists(cache_file):
        data = pd.read_csv(cache_file)
    else:
        try:
            s = _get_stock_obj_with_fallback(sym)
            df_raw = s.quote.history(start=start_str, end=end_str, interval='1D')
        except Exception as e:
            return f"vnstock error fetching data for indicators: {e}"

        if df_raw is None or df_raw.empty:
            return f"No price data available for {sym}"

        col_map = {'time': 'Date', 'open': 'Open', 'high': 'High',
                   'low': 'Low', 'close': 'Close', 'volume': 'Volume'}
        df_raw = df_raw.rename(columns=col_map)
        df_raw['Date'] = pd.to_datetime(df_raw['Date']).dt.strftime('%Y-%m-%d')
        df_raw.to_csv(cache_file, index=False)
        data = df_raw

    data = _clean_dataframe(data)
    df = wrap(data)
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')

    # Indicator descriptions (same as yfinance version)
    INDICATOR_DESCRIPTIONS = {
        "close_50_sma": "50 SMA: Medium-term trend indicator.",
        "close_200_sma": "200 SMA: Long-term trend benchmark.",
        "close_10_ema": "10 EMA: Responsive short-term average.",
        "macd": "MACD: Momentum via EMA differences.",
        "macds": "MACD Signal: EMA smoothing of MACD line.",
        "macdh": "MACD Histogram: Gap between MACD and signal.",
        "rsi": "RSI: Overbought/oversold momentum indicator.",
        "boll": "Bollinger Middle: 20 SMA basis.",
        "boll_ub": "Bollinger Upper Band: Overbought/breakout zone.",
        "boll_lb": "Bollinger Lower Band: Oversold zone.",
        "atr": "ATR: Volatility measure for stop-loss sizing.",
        "vwma": "VWMA: Volume-weighted moving average.",
    }

    try:
        df[indicator]  # trigger stockstats calculation
    except Exception as e:
        return f"Error computing indicator '{indicator}': {e}"

    # Build lookback window output
    results = []
    curr_date_str = curr_date_dt.strftime('%Y-%m-%d')
    start_window = (curr_date_dt - pd.DateOffset(days=look_back_days)).strftime('%Y-%m-%d')

    window_df = df[(df['Date'] >= start_window) & (df['Date'] <= curr_date_str)]
    for _, row in window_df.iterrows():
        results.append(f"{row['Date']}: {row.get(indicator, 'N/A')}")

    if not results:
        return f"No data in the specified window for {sym} {indicator}"

    desc = INDICATOR_DESCRIPTIONS.get(indicator, indicator)
    output = '\n'.join(results)
    output += f"\n\n{desc}"
    return output


# ── Fundamentals ───────────────────────────────────────────────────────────────

def get_fundamentals(ticker: str, curr_date: str) -> str:
    """Company overview + key financial ratios."""
    sym = clean_symbol(ticker)
    try:
        s = _get_stock_obj_with_fallback(sym)
        overview = s.company.overview()
        # vnstock 3.5.0's KBS Finance returns 404 across the board and
        # VCI's Stock construction is broken for many symbols, so the
        # ratio call may fail; collect any error and surface it next to
        # the overview block rather than abandoning the whole report.
        ratio = None
        ratio_error: str | None = None
        try:
            ratio = s.finance.ratio(period='quarter')
        except Exception as e:  # noqa: BLE001 — partial data is better than none
            ratio_error = f"{type(e).__name__}: {e}"

        parts = [f"=== Company Overview: {sym} ==="]
        if overview is not None and not overview.empty:
            parts.append(overview.to_string())

        parts.append(f"\n=== Financial Ratios (last 4 quarters) ===")
        if ratio is not None and not ratio.empty:
            parts.append(ratio.tail(4).T.to_string())
        elif ratio_error:
            parts.append(f"<vnstock ratio unavailable: {ratio_error}>")

        return '\n'.join(parts)
    except Exception as e:
        return f"vnstock error fetching fundamentals for {sym}: {e}"


def get_balance_sheet(ticker: str, freq: str = 'quarterly', curr_date: str = None) -> str:
    """Balance sheet data."""
    sym = clean_symbol(ticker)
    period = 'quarter' if 'quarter' in freq.lower() else 'year'
    try:
        s = _get_stock_obj_with_fallback(sym)
        df = s.finance.balance_sheet(period=period)
        if df is None or df.empty:
            return f"No balance sheet data for {sym}"
        # Show last 4 periods
        result = df.tail(4).T.to_string()
        return f"=== Balance Sheet ({period}) for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching balance sheet for {sym}: {e}"


def get_cashflow(ticker: str, freq: str = 'quarterly', curr_date: str = None) -> str:
    """Cash flow statement data."""
    sym = clean_symbol(ticker)
    period = 'quarter' if 'quarter' in freq.lower() else 'year'
    try:
        s = _get_stock_obj_with_fallback(sym)
        df = s.finance.cash_flow(period=period)
        if df is None or df.empty:
            return f"No cash flow data for {sym}"
        result = df.tail(4).T.to_string()
        return f"=== Cash Flow ({period}) for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching cash flow for {sym}: {e}"


def get_income_statement(ticker: str, freq: str = 'quarterly', curr_date: str = None) -> str:
    """Income statement data."""
    sym = clean_symbol(ticker)
    period = 'quarter' if 'quarter' in freq.lower() else 'year'
    try:
        s = _get_stock_obj_with_fallback(sym)
        df = s.finance.income_statement(period=period)
        if df is None or df.empty:
            return f"No income statement data for {sym}"
        result = df.tail(4).T.to_string()
        return f"=== Income Statement ({period}) for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching income statement for {sym}: {e}"


def get_insider_transactions(ticker: str, curr_date: str = None) -> str:
    """Insider deals / transactions."""
    sym = clean_symbol(ticker)
    try:
        s = _get_stock_obj_with_fallback(sym)
        df = s.company.insider_deals()
        if df is None or df.empty:
            return f"No insider transaction data for {sym}"
        result = df.tail(20).to_string()
        return f"=== Insider Transactions for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching insider transactions for {sym}: {e}"


def get_news(ticker: str, curr_date: str = None, look_back_days: int = 7) -> str:
    """Company news from vnstock with source-fallback (KBS → VCI)."""
    sym = clean_symbol(ticker)
    errors: list[str] = []
    for src, s in _get_company_with_fallback(sym):
        try:
            df = s.company.news()
            if df is None or df.empty:
                errors.append(f"{src}: empty")
                continue
            result = df.head(20).to_string()
            return f"=== News for {sym} (source: {src}) ===\n{result}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src}: {type(e).__name__}: {e}")
            continue
    return f"vnstock: no news source returned data for {sym} ({'; '.join(errors)})"


def get_insider_transactions_fallback(ticker: str, curr_date: str = None) -> str:
    """Helper reused by interface — same fallback as get_news."""
    sym = clean_symbol(ticker)
    errors: list[str] = []
    for src, s in _get_company_with_fallback(sym):
        try:
            df = s.company.insider_deals()
            if df is None or df.empty:
                errors.append(f"{src}: empty")
                continue
            return f"=== Insider Transactions for {sym} (source: {src}) ===\n{df.tail(20).to_string()}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src}: {type(e).__name__}: {e}")
            continue
    return f"vnstock: no insider source returned data for {sym} ({'; '.join(errors)})"

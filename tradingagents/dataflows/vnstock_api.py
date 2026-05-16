"""
vnstock_api.py — VNStock data provider for Vietnamese stocks (HOSE/HNX/UPCOM).

Drop-in replacement for yfinance methods for VN tickers.
Exposes the same function signatures used in interface.py VENDOR_METHODS.

Migrated from the legacy ``Vnstock().stock(symbol, source).quote/finance/company``
helper (deprecated 31/08/2025) to the unified ``vnstock.api.*`` classes:
``Quote``, ``Company``, ``Finance``. Two practical wins from the move:

* No more multi-line "DEPRECATION NOTICE" banner printed to stdout on every
  call (the new API stays quiet on this front).
* Source construction is per-route, so a broken VCI ``Company`` payload
  no longer cascades into the price route the way the eager
  ``Vnstock().stock(...)`` helper used to.

vnai's "INSIDERS PROGRAM" promo banner still occasionally lands on stdout
(separate library, separate concern); callers that pipe output through a
JSON parser must still redirect stdout to stderr — see the consumers in
``dashboard/scripts/fetch_quotes.py`` and the dashboard API routes.
"""

import os
import re
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Annotated, Callable, TypeVar

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


# Source fallback order. We try VCI first for routes whose VCI endpoint is
# the more complete one (Finance has a richer schema there), and KBS first
# for company-metadata routes that have historically broken on VCI
# (Company endpoint returning a payload without the ``data`` key for some
# symbols — TCB confirmed 2026-05-16). The price route accepts either.
_PRICE_SOURCES: tuple[str, ...] = ("VCI", "KBS")
_FINANCE_SOURCES: tuple[str, ...] = ("VCI", "KBS")
_COMPANY_SOURCES: tuple[str, ...] = ("KBS", "VCI")


T = TypeVar("T")


def _try_sources(builder: Callable[[str], T], sources: tuple[str, ...]) -> tuple[T, str]:
    """Return ``(object, source_id)`` for the first source the builder accepts.

    Re-raises the last exception only if every source fails so callers can
    surface a meaningful error rather than ``no vendor`` ambiguity.
    """
    last_err: Exception | None = None
    for src in sources:
        try:
            return builder(src), src
        except Exception as e:  # noqa: BLE001 — try every source
            last_err = e
            continue
    assert last_err is not None  # loop is non-empty so this is unreachable
    raise last_err


def _build_quote(symbol: str, sources: tuple[str, ...] = _PRICE_SOURCES):
    """Construct a ``Quote`` on the first source whose constructor succeeds."""
    from vnstock.api.quote import Quote
    sym = clean_symbol(symbol)
    return _try_sources(lambda src: Quote(source=src, symbol=sym), sources)


def _build_company(symbol: str, sources: tuple[str, ...] = _COMPANY_SOURCES):
    """Construct a ``Company`` on the first source whose constructor succeeds."""
    from vnstock.api.company import Company
    sym = clean_symbol(symbol)
    return _try_sources(lambda src: Company(source=src, symbol=sym), sources)


def _build_finance(symbol: str, period: str = "quarter",
                   sources: tuple[str, ...] = _FINANCE_SOURCES):
    """Construct a ``Finance`` on the first source whose constructor succeeds."""
    from vnstock.api.financial import Finance
    sym = clean_symbol(symbol)
    return _try_sources(lambda src: Finance(source=src, symbol=sym, period=period), sources)


# ── Price data ─────────────────────────────────────────────────────────────────

def get_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Fetch OHLCV price history from vnstock.

    Returns CSV string compatible with yfinance output format.
    """
    sym = clean_symbol(symbol)
    try:
        quote, source = _build_quote(sym)
        df = quote.history(start=start_date, end=end_date, interval='1D')
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
    header += f"# Source: {source}\n\n"
    return header + df.to_csv()


# ── Technical indicators (via stockstats on vnstock data) ──────────────────────

def get_indicators(
    symbol: str,
    indicator: str,
    curr_date: str,
    look_back_days: int = 90,
) -> str:
    """Calculate technical indicators using stockstats on vnstock price data."""
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
            quote, _source = _build_quote(sym)
            df_raw = quote.history(start=start_str, end=end_str, interval='1D')
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
    """Company overview + key financial ratios.

    Splits the data fetch across two API objects since the new
    ``vnstock.api`` classes are intentionally narrow: ``Company`` for the
    overview, ``Finance`` for the ratios. Each picks its own source via
    the fallback helper so a single-vendor outage degrades to partial
    data instead of an empty report.
    """
    sym = clean_symbol(ticker)
    parts = [f"=== Company Overview: {sym} ==="]

    # ── Overview (Company) ────────────────────────────────────────────
    try:
        company, _src = _build_company(sym)
        overview = company.overview()
        if overview is not None and not overview.empty:
            parts.append(overview.to_string())
    except Exception as e:  # noqa: BLE001 — surface as inline annotation
        parts.append(f"<overview unavailable: {type(e).__name__}: {e}>")

    # ── Ratios (Finance) ──────────────────────────────────────────────
    parts.append("\n=== Financial Ratios (last 4 quarters) ===")
    try:
        finance, _src = _build_finance(sym, period="quarter")
        ratio = finance.ratio()
        if ratio is not None and not ratio.empty:
            parts.append(ratio.tail(4).T.to_string())
        else:
            parts.append("<ratio returned empty>")
    except Exception as e:  # noqa: BLE001
        parts.append(f"<ratio unavailable: {type(e).__name__}: {e}>")

    return '\n'.join(parts)


def get_balance_sheet(ticker: str, freq: str = 'quarterly', curr_date: str = None) -> str:
    """Balance sheet data."""
    sym = clean_symbol(ticker)
    period = 'quarter' if 'quarter' in freq.lower() else 'year'
    try:
        finance, _src = _build_finance(sym, period=period)
        df = finance.balance_sheet()
        if df is None or df.empty:
            return f"No balance sheet data for {sym}"
        result = df.tail(4).T.to_string()
        return f"=== Balance Sheet ({period}) for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching balance sheet for {sym}: {e}"


def get_cashflow(ticker: str, freq: str = 'quarterly', curr_date: str = None) -> str:
    """Cash flow statement data."""
    sym = clean_symbol(ticker)
    period = 'quarter' if 'quarter' in freq.lower() else 'year'
    try:
        finance, _src = _build_finance(sym, period=period)
        df = finance.cash_flow()
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
        finance, _src = _build_finance(sym, period=period)
        df = finance.income_statement()
        if df is None or df.empty:
            return f"No income statement data for {sym}"
        result = df.tail(4).T.to_string()
        return f"=== Income Statement ({period}) for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching income statement for {sym}: {e}"


def get_insider_transactions(ticker: str, curr_date: str = None) -> str:
    """Insider deals / transactions."""
    sym = clean_symbol(ticker)
    # In the new API the method is called ``insider_trading`` (not
    # ``insider_deals`` as in the legacy ``stock.company.*`` namespace).
    try:
        company, _src = _build_company(sym)
        df = company.insider_trading()
        if df is None or df.empty:
            return f"No insider transaction data for {sym}"
        result = df.tail(20).to_string()
        return f"=== Insider Transactions for {sym} ===\n{result}"
    except Exception as e:
        return f"vnstock error fetching insider transactions for {sym}: {e}"


def get_news(ticker: str, curr_date: str = None, look_back_days: int = 7) -> str:
    """Company news from vnstock with source-fallback."""
    sym = clean_symbol(ticker)
    errors: list[str] = []
    # Try each source explicitly so the diagnostic includes which one(s) failed.
    from vnstock.api.company import Company
    for src in _COMPANY_SOURCES:
        try:
            company = Company(source=src, symbol=sym)
            df = company.news()
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
    """Helper reused by interface — same fallback semantics as get_news."""
    sym = clean_symbol(ticker)
    errors: list[str] = []
    from vnstock.api.company import Company
    for src in _COMPANY_SOURCES:
        try:
            company = Company(source=src, symbol=sym)
            df = company.insider_trading()
            if df is None or df.empty:
                errors.append(f"{src}: empty")
                continue
            return f"=== Insider Transactions for {sym} (source: {src}) ===\n{df.tail(20).to_string()}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"{src}: {type(e).__name__}: {e}")
            continue
    return f"vnstock: no insider source returned data for {sym} ({'; '.join(errors)})"

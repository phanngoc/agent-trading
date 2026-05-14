/** The dashboard's tracking universe, grouped for the Markets page.
 *  Symbols use Yahoo Finance convention because /api/markets/quotes
 *  proxies Yahoo. Crypto uses Yahoo's "-USD" pairs (BTC-USD, ETH-USD).
 */

import type { Quote } from "@/lib/api-client"

export type SymbolMeta = {
  symbol: string
  name: string
  category: Quote["category"]
  currency: string
}

export const SYMBOLS: SymbolMeta[] = [
  // Vietnam first — that's the home market.
  { symbol: "^VNINDEX",     name: "VN-Index",        category: "vn",        currency: "VND" },
  { symbol: "^HNX",         name: "HNX-Index",       category: "vn",        currency: "VND" },
  { symbol: "^UPCOM",       name: "UPCoM-Index",     category: "vn",        currency: "VND" },

  // Global indices
  { symbol: "^GSPC",        name: "S&P 500",         category: "index",     currency: "USD" },
  { symbol: "^IXIC",        name: "NASDAQ Composite",category: "index",     currency: "USD" },
  { symbol: "^DJI",         name: "Dow Jones",       category: "index",     currency: "USD" },
  { symbol: "^FTSE",        name: "FTSE 100",        category: "index",     currency: "GBP" },
  { symbol: "^N225",        name: "Nikkei 225",      category: "index",     currency: "JPY" },
  { symbol: "^HSI",         name: "Hang Seng",       category: "index",     currency: "HKD" },
  { symbol: "000001.SS",    name: "Shanghai Comp.",  category: "index",     currency: "CNY" },

  // Commodities / gold / oil
  { symbol: "GC=F",         name: "Gold (XAU)",      category: "commodity", currency: "USD" },
  { symbol: "SI=F",         name: "Silver",          category: "commodity", currency: "USD" },
  { symbol: "CL=F",         name: "WTI Crude Oil",   category: "commodity", currency: "USD" },
  { symbol: "BZ=F",         name: "Brent Crude",     category: "commodity", currency: "USD" },
  { symbol: "DX-Y.NYB",     name: "US Dollar Index", category: "commodity", currency: "USD" },

  // Crypto
  { symbol: "BTC-USD",      name: "Bitcoin",         category: "crypto",    currency: "USD" },
  { symbol: "ETH-USD",      name: "Ethereum",        category: "crypto",    currency: "USD" },
  { symbol: "SOL-USD",      name: "Solana",          category: "crypto",    currency: "USD" },
  { symbol: "BNB-USD",      name: "BNB",             category: "crypto",    currency: "USD" },
]

export const symbolMeta = (symbol: string): SymbolMeta | undefined =>
  SYMBOLS.find((s) => s.symbol === symbol)

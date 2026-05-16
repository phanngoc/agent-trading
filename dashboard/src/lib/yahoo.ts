/** Thin wrapper around Yahoo Finance's public quote + chart endpoints.
 *
 *  These are the same endpoints query1.finance.yahoo.com serves to the
 *  Yahoo Finance website. They require no API key, but they're rate-
 *  limited per IP and Yahoo can revoke them at any time. For production
 *  scale, swap to a paid feed; for a personal dashboard polled every
 *  60s, they're fine.
 *
 *  Used only from server-side route handlers — never call from the
 *  browser (CORS will block, and we want server-side caching anyway).
 */

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

export type YahooQuote = {
  symbol: string
  shortName?: string
  longName?: string
  regularMarketPrice?: number
  regularMarketChange?: number
  regularMarketChangePercent?: number
  currency?: string
}

export type YahooChartPoint = { t: string; c: number }

export async function fetchQuotes(symbols: string[]): Promise<YahooQuote[]> {
  if (symbols.length === 0) return []
  const url = new URL("https://query1.finance.yahoo.com/v7/finance/quote")
  url.searchParams.set("symbols", symbols.join(","))
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    // Server-side: tiny cache so we don't hammer Yahoo on every page render.
    next: { revalidate: 30 },
  })
  if (!res.ok) throw new Error(`yahoo quote ${res.status}`)
  const j: { quoteResponse?: { result?: YahooQuote[] } } = await res.json()
  return j.quoteResponse?.result ?? []
}

export async function fetchChart(
  symbol: string,
  range: "1d" | "5d" | "1mo" | "3mo" | "1y" = "1mo",
  interval: "5m" | "15m" | "1h" | "1d" = "1d",
): Promise<YahooChartPoint[]> {
  const url = new URL(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}`)
  url.searchParams.set("range", range)
  url.searchParams.set("interval", interval)
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    next: { revalidate: 60 },
  })
  if (!res.ok) throw new Error(`yahoo chart ${res.status}`)
  const j = (await res.json()) as {
    chart?: {
      result?: Array<{
        timestamp?: number[]
        indicators?: { quote?: Array<{ close?: (number | null)[] }> }
      }>
    }
  }
  const r = j.chart?.result?.[0]
  if (!r?.timestamp || !r.indicators?.quote?.[0]?.close) return []
  const closes = r.indicators.quote[0].close
  return r.timestamp
    .map((ts, i) => ({ t: new Date(ts * 1000).toISOString(), c: closes[i] as number | null }))
    .filter((p): p is YahooChartPoint => p.c != null)
}

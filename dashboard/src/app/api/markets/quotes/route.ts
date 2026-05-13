import { NextResponse } from "next/server"
import { SYMBOLS } from "@/lib/symbols"
import { fetchYFinanceQuotes } from "@/lib/yfinance"
import type { Quote } from "@/lib/api-client"

export const runtime = "nodejs"
export const revalidate = 60

// In-process cache so we don't spawn a fresh Python subprocess for every
// page render — the script takes ~3s for 20 symbols and the prices only
// move every ~minute anyway. ISR via `revalidate` covers static caching
// at the build level; this guards request-time concurrency.
let cache: { ts: number; quotes: Quote[] } | null = null
const CACHE_MS = 60_000

export async function GET() {
  if (cache && Date.now() - cache.ts < CACHE_MS) {
    return NextResponse.json({ quotes: cache.quotes })
  }

  const symbols = SYMBOLS.map((s) => s.symbol)
  try {
    const raw = await fetchYFinanceQuotes(symbols)
    const byId = new Map(raw.map((q) => [q.symbol, q]))

    const quotes: Quote[] = SYMBOLS.map((meta) => {
      const y = byId.get(meta.symbol)
      return {
        symbol: meta.symbol,
        name: meta.name,
        price: y?.price ?? NaN,
        change: y?.change ?? 0,
        changePercent: y?.changePercent ?? 0,
        currency: y?.currency ?? meta.currency,
        category: meta.category,
        history: y?.history ?? [],
      }
    })

    cache = { ts: Date.now(), quotes }
    return NextResponse.json({ quotes })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e), quotes: cache?.quotes ?? [] },
      { status: cache ? 200 : 502 },
    )
  }
}

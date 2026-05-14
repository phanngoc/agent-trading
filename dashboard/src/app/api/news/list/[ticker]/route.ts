import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export type NewsItem = {
  title: string
  url: string
  source: string
  publishedAt: string | null
  sentimentScore: number | null
  sentimentLabel: string | null
  relevance: number | null
}

const TREND_NEWS_URL = process.env.TREND_NEWS_URL ?? "http://localhost:8000"
// trend_news ships with "dev-key" as its default API key (configured via
// TRENDRADAR_API_KEYS env var in trend_news/.env). The dashboard runs
// alongside trend_news on localhost, so embedding the dev key here is no
// different than letting the dashboard read it from the same .env.
const TREND_NEWS_API_KEY = process.env.TREND_NEWS_API_KEY ?? "dev-key"

/** Fetch news for a ticker from trend_news (Vietnamese sources) with
 *  graceful empty-fallback when the server is down.
 *
 *  We deliberately stick to trend_news here rather than fanning out to
 *  vnstock — vnstock's company.news returns DataFrames that we'd have
 *  to JSON-serialize and the title quality is much lower than what
 *  trend_news's source aggregation produces.
 */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ ticker: string }> },
) {
  const { ticker } = await ctx.params
  const decoded = decodeURIComponent(ticker)
  const url = new URL(req.url)
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "30", 10), 100)

  const apiUrl = new URL(`${TREND_NEWS_URL}/api/v1/news`)
  apiUrl.searchParams.set("ticker", decoded)
  apiUrl.searchParams.set("limit", String(limit))

  try {
    const res = await fetch(apiUrl.toString(), {
      headers: { "X-API-Key": TREND_NEWS_API_KEY },
      signal: AbortSignal.timeout(4000),
      cache: "no-store",
    })
    if (!res.ok) {
      return NextResponse.json(
        { items: [], error: `trend_news ${res.status} ${res.statusText}` },
        { status: 200 },
      )
    }
    type Raw = {
      title?: string
      url?: string
      source_id?: string
      crawled_at?: string
      sentiment_score?: number | null
      sentiment_label?: string | null
      relevance_score?: number | null
    }
    const raw = (await res.json()) as Raw[]
    const items: NewsItem[] = (Array.isArray(raw) ? raw : []).map((r) => ({
      title: r.title ?? "(no title)",
      url: r.url ?? "",
      source: r.source_id ?? "unknown",
      publishedAt: r.crawled_at ?? null,
      sentimentScore: r.sentiment_score ?? null,
      sentimentLabel: r.sentiment_label ?? null,
      relevance: r.relevance_score ?? null,
    }))
    return NextResponse.json({ items })
  } catch (e) {
    return NextResponse.json(
      {
        items: [],
        error: e instanceof Error ? e.message : String(e),
        hint: "trend_news server không chạy — mở /agent và bấm restart pill, hoặc chạy `bash trend_news/start-http.sh`.",
      },
      { status: 200 },
    )
  }
}

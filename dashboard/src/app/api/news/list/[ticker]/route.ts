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

export type NewsListResponse = {
  items: NewsItem[]
  /** Aggregated sentiment counts pulled from /api/v1/tickers/{ticker}. */
  sentiment?: {
    avg_score: number
    label: string
    bullish: number
    bearish: number
    neutral: number
    article_count: number
  }
  /** Set when no article is within `freshDays` days of the trade date. */
  staleWarning?: { latestPublishedAt: string; daysOld: number }
  error?: string
  hint?: string
  /** Diagnostic: which step in the fallback chain produced the items. */
  source?: "tickers-filter" | "fts-alias" | "empty"
}

const TREND_NEWS_URL = process.env.TREND_NEWS_URL ?? "http://localhost:8000"
const TREND_NEWS_API_KEY = process.env.TREND_NEWS_API_KEY ?? "dev-key"

/** Map dashboard ticker form (VIC.VN) to trend_news alias-map key (VIC). */
function bareTicker(ticker: string): string {
  return ticker.toUpperCase().replace(/\.VN$/, "")
}

type RawArticle = {
  title?: string
  url?: string
  source_id?: string
  crawled_at?: string
  sentiment_score?: number | null
  sentiment_label?: string | null
  relevance_score?: number | null
}

function toItem(r: RawArticle): NewsItem {
  return {
    title: r.title ?? "(no title)",
    url: r.url ?? "",
    source: r.source_id ?? "unknown",
    publishedAt: r.crawled_at ?? null,
    sentimentScore: r.sentiment_score ?? null,
    sentimentLabel: r.sentiment_label ?? null,
    relevance: r.relevance_score ?? null,
  }
}

async function trendNewsFetch(url: URL): Promise<RawArticle[]> {
  const res = await fetch(url.toString(), {
    headers: { "X-API-Key": TREND_NEWS_API_KEY },
    signal: AbortSignal.timeout(4000),
    cache: "no-store",
  })
  if (!res.ok) throw new Error(`trend_news ${res.status} ${res.statusText}`)
  const j = await res.json()
  return Array.isArray(j) ? (j as RawArticle[]) : []
}

/** GET /api/news/list/<ticker>?date=YYYY-MM-DD&days_back=N&limit=N
 *
 *  Three-layer fallback so the user sees *something* even when the
 *  ticker map / DB freshness is partial:
 *
 *    1. tickers=<bare>&start_date&end_date   — canonical filter
 *    2. tickers=<bare> (no date window)      — DB might be stale relative to trade date
 *    3. q=<alias>                            — FTS fallback per ticker alias
 *
 *  Always returns 200; check `source` and `staleWarning` to understand
 *  the freshness of what came back.
 */
export async function GET(
  req: Request,
  ctx: { params: Promise<{ ticker: string }> },
) {
  const { ticker } = await ctx.params
  const decoded = decodeURIComponent(ticker)
  const bare = bareTicker(decoded)

  const url = new URL(req.url)
  const tradeDate = url.searchParams.get("date") ?? new Date().toISOString().slice(0, 10)
  const daysBack = Math.max(1, parseInt(url.searchParams.get("days_back") ?? "30", 10))
  const limit = Math.min(parseInt(url.searchParams.get("limit") ?? "30", 10), 100)

  const startDate = (() => {
    const d = new Date(tradeDate)
    d.setUTCDate(d.getUTCDate() - daysBack)
    return d.toISOString().slice(0, 10)
  })()

  const buildUrl = (params: Record<string, string>) => {
    const u = new URL(`${TREND_NEWS_URL}/api/v1/news`)
    for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v)
    return u
  }

  let articles: RawArticle[] = []
  let sourceUsed: NewsListResponse["source"] = "empty"

  try {
    // Layer 1: scoped to the agent's lookback window
    articles = await trendNewsFetch(buildUrl({
      tickers: bare,
      start_date: startDate,
      end_date: tradeDate,
      limit: String(limit),
    }))
    if (articles.length > 0) sourceUsed = "tickers-filter"

    // Layer 2: drop the date constraint (DB might be stale relative to trade date)
    if (articles.length === 0) {
      articles = await trendNewsFetch(buildUrl({ tickers: bare, limit: String(limit) }))
      if (articles.length > 0) sourceUsed = "tickers-filter"
    }

    // Layer 3: FTS by alias. Pull aliases from /api/v1/tickers — if 404,
    // fall back to the bare ticker as the search term.
    if (articles.length === 0) {
      const aliasResp = await fetch(`${TREND_NEWS_URL}/api/v1/tickers/${bare}`, {
        headers: { "X-API-Key": TREND_NEWS_API_KEY },
        signal: AbortSignal.timeout(2500),
        cache: "no-store",
      }).catch(() => null)
      let aliases: string[] = [bare]
      if (aliasResp?.ok) {
        const j = (await aliasResp.json()) as { company_name?: string }
        if (j.company_name) aliases = [j.company_name, bare]
      }
      for (const alias of aliases) {
        articles = await trendNewsFetch(buildUrl({ q: alias, limit: String(limit) }))
        if (articles.length > 0) { sourceUsed = "fts-alias"; break }
      }
    }
  } catch (e) {
    return NextResponse.json<NewsListResponse>({
      items: [],
      source: "empty",
      error: e instanceof Error ? e.message : String(e),
      hint: "trend_news server không phản hồi — restart pill ở /agent, hoặc bấm 'Cập nhật tin' để trigger crawl.",
    })
  }

  // De-duplicate by URL (FTS layer can repeat hits from layer 1/2 if both run).
  const seen = new Set<string>()
  const items = articles
    .map(toItem)
    .filter((it) => {
      if (!it.url || seen.has(it.url)) return false
      seen.add(it.url)
      return true
    })
    // Newest first — DB return order isn't guaranteed.
    .sort((a, b) => (b.publishedAt ?? "").localeCompare(a.publishedAt ?? ""))
    .slice(0, limit)

  // Surface staleness: warn when the freshest article is far from the trade date.
  let staleWarning: NewsListResponse["staleWarning"]
  if (items.length > 0 && items[0].publishedAt) {
    const latest = new Date(items[0].publishedAt)
    const trade = new Date(tradeDate)
    const daysOld = Math.floor((trade.getTime() - latest.getTime()) / 86_400_000)
    if (daysOld > 7) {
      staleWarning = { latestPublishedAt: items[0].publishedAt, daysOld }
    }
  }

  // Best-effort: enrich with aggregated sentiment from /api/v1/tickers/<bare>.
  let sentiment: NewsListResponse["sentiment"]
  try {
    const r = await fetch(`${TREND_NEWS_URL}/api/v1/tickers/${bare}?days_back=${daysBack}`, {
      headers: { "X-API-Key": TREND_NEWS_API_KEY },
      signal: AbortSignal.timeout(2500),
      cache: "no-store",
    })
    if (r.ok) {
      const j = (await r.json()) as {
        avg_sentiment_score?: number
        sentiment_label?: string
        bullish_count?: number
        bearish_count?: number
        neutral_count?: number
        article_count?: number
      }
      if ((j.article_count ?? 0) > 0) {
        sentiment = {
          avg_score: j.avg_sentiment_score ?? 0,
          label: j.sentiment_label ?? "Neutral",
          bullish: j.bullish_count ?? 0,
          bearish: j.bearish_count ?? 0,
          neutral: j.neutral_count ?? 0,
          article_count: j.article_count ?? 0,
        }
      }
    }
  } catch { /* aggregated sentiment is optional */ }

  return NextResponse.json<NewsListResponse>({
    items,
    sentiment,
    staleWarning,
    source: items.length === 0 ? "empty" : sourceUsed,
  })
}

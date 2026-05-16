/** Type definitions + client helper for /api/markets/detail/[symbol].
 *
 *  Kept in its own module so the detail page and any future widget
 *  (e.g. an index-summary tile on the home page) share the same shape.
 */

export type ImpactRow = {
  symbol: string
  pct_change: number
  impact_pts: number
  match_price: number
  match_value_vnd: number
}

export type ForeignTickerRow = {
  symbol: string
  net_value_vnd: number
}

export type MarketDetail = {
  exchange: string | null
  group: string | null
  asof: string | null
  constituents: number
  advancers: number
  decliners: number
  unchanged: number
  flow: { up_vnd: number; down_vnd: number; flat_vnd: number }
  top_impact: ImpactRow[]
  foreign_today: {
    buy_volume: number
    sell_volume: number
    buy_value_vnd: number
    sell_value_vnd: number
    net_volume: number
    net_value_vnd: number
    by_ticker: ForeignTickerRow[]
  }
  ticker_count: number
  error: string | null
}

export async function fetchMarketDetail(symbol: string): Promise<MarketDetail> {
  const res = await fetch(`/api/markets/detail/${encodeURIComponent(symbol)}`, { cache: "no-store" })
  if (!res.ok) throw new Error(`market detail → ${res.status}`)
  return res.json()
}

/** Set of symbols that have rich aggregated data (VN exchange indices).
 *  Anything else still routes to /markets/[symbol] but only renders the
 *  price card + 30D chart. */
export function hasRichDetail(symbol: string): boolean {
  const upper = symbol.toUpperCase().replace(/^\^/, "")
  return ["VNINDEX", "VN30", "HNX", "HNXINDEX", "HNX30", "UPCOM", "UPCOMINDEX"].includes(upper)
}

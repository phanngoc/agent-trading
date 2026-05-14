/** Single-source API surface for the dashboard. All server-state calls
 *  flow through here so we have one place to swap fetch impls, add
 *  retries, or thread a base URL.
 */

export type Quote = {
  symbol: string
  name: string
  price: number
  changePercent: number
  change: number
  currency: string
  category: "index" | "commodity" | "crypto" | "vn"
  history?: { t: string; c: number }[]
}

export type AgentDecision = {
  ticker: string
  date: string
  decision: string                // "BUY" | "SELL" | "HOLD"
  rating?: string                 // "Buy" / "Overweight" / "Hold" / "Underweight" / "Sell"
  final_trade_decision?: string
  investment_plan?: string
  trader_investment_plan?: string
  market_report?: string
  sentiment_report?: string
  news_report?: string
  fundamentals_report?: string
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" })
  if (!res.ok) throw new Error(`${path} → ${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  quotes: () => get<{ quotes: Quote[] }>("/api/markets/quotes"),
  vnIndex: () => get<Quote>("/api/markets/vnindex"),
  agentRuns: () => get<{ runs: AgentDecision[] }>("/api/agent/runs"),
  agentRun: (ticker: string, date: string) =>
    get<AgentDecision>(`/api/agent/runs/${encodeURIComponent(ticker)}/${date}`),
  triggerAgent: async (ticker: string) => {
    const res = await fetch("/api/agent/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker }),
    })
    if (!res.ok) throw new Error(`trigger → ${res.status}`)
    return res.json() as Promise<{ ok: boolean; run_id: string; ticker: string; date: string }>
  },
}

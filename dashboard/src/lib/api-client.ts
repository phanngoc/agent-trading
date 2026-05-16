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

// ── Benchmark types — mirror dashboard/src/lib/benchmark.ts ───────────

export type StrategyScorecard = {
  strategy_id: string
  n_days: number
  total_return_pct: number
  annualized_return_pct: number
  annualized_vol_pct: number
  sharpe: number
  max_drawdown_pct: number
  n_trades: number
  hit_rate: number
  avg_return_per_trade_pct: number
  profit_factor: number | string
  alpha_annualized_pct: number | null
  beta: number | null
  r_squared: number | null
  t_stat: number | null
  p_value: number | null
}

export type RunScorecard = {
  run_date: string
  window: { start: string; end: string; n_trading_days: number }
  benchmark: string
  initial_capital_vnd: number
  strategies: StrategyScorecard[]
}

export type RunSummary = {
  date: string
  hasBrief: boolean
  hasScorecard: boolean
  hasReport: boolean
  agentLogs: string[]
  strategies?: string[]
}

export type LockStatus = { running: boolean; pid?: number; startedAt?: string }

export type DecisionRow = {
  strategy_id: string
  ticker: string
  decision_date: string
  action: "BUY" | "HOLD" | "SELL"
  rationale?: string | null
  source_path?: string | null
}

export type ExecutionRow = {
  decision_date: string
  ticker: string
  action: string
  fill_date: string | null
  status: string
  quantity: number
  fill_price: number
  realized_pnl_vnd: number
  note: string | null
}

export type StrategyDecisionDump = {
  strategy_id: string
  kind: string
  decisions: DecisionRow[]
  execution_log: ExecutionRow[]
  final_portfolio: unknown
}

export type RunDetail = {
  date: string
  scorecard: RunScorecard | null
  brief: string | null
  report: string | null
  decisions: Record<string, StrategyDecisionDump | null>
  agentLogs: string[]
  equityCurves: string | null
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

  // ── Benchmark surface ───────────────────────────────────────────
  benchmarkRuns: () => get<{ runs: RunSummary[]; lock: LockStatus }>("/api/benchmark/runs"),
  benchmarkRun: (date: string) => get<RunDetail>(`/api/benchmark/runs/${date}`),
  benchmarkAgentLog: async (date: string, ticker: string): Promise<string> => {
    const res = await fetch(`/api/benchmark/runs/${date}/agent-log/${ticker}`, { cache: "no-store" })
    if (!res.ok) throw new Error(`agent log → ${res.status}`)
    return res.text()
  },
  benchmarkCronLog: (lines = 200) =>
    get<{ lines: string[]; count: number }>(`/api/benchmark/cron-log?lines=${lines}`),
}

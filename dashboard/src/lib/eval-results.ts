/** Server-only readers for the eval_results/ directory the Python agent writes.
 *
 *  Directory layout (see tradingagents/graph/trading_graph.py `_log_state`):
 *    eval_results/
 *      <TICKER>/
 *        TradingAgentsStrategy_logs/
 *          full_states_log_<YYYY-MM-DD>.json   ← top-level keyed by date
 *
 *  Each JSON file is a dict keyed by trade_date with the full final state
 *  the graph produced. We read these directly from disk — no DB layer.
 */

import { promises as fs } from "node:fs"
import path from "node:path"
import type { AgentDecision } from "@/lib/api-client"

const EVAL_ROOT = path.resolve(process.cwd(), "..", "eval_results")

function inferDecisionLabel(final?: string): string {
  if (!final) return "HOLD"
  const m = final.toUpperCase().match(/\b(BUY|SELL|HOLD)\b/)
  return m?.[1] ?? "HOLD"
}

function inferRating(plan?: string): string | undefined {
  if (!plan) return undefined
  const m = plan.match(/\b(Buy|Overweight|Hold|Underweight|Sell)\b/i)
  return m?.[1] ? m[1][0].toUpperCase() + m[1].slice(1).toLowerCase() : undefined
}

export async function listAgentRuns(): Promise<AgentDecision[]> {
  let tickers: string[] = []
  try {
    tickers = (await fs.readdir(EVAL_ROOT, { withFileTypes: true }))
      .filter((d) => d.isDirectory())
      .map((d) => d.name)
  } catch {
    return []
  }

  const runs: AgentDecision[] = []
  for (const ticker of tickers) {
    const logsDir = path.join(EVAL_ROOT, ticker, "TradingAgentsStrategy_logs")
    let files: string[] = []
    try {
      files = await fs.readdir(logsDir)
    } catch {
      continue
    }
    for (const file of files) {
      if (!file.startsWith("full_states_log_") || !file.endsWith(".json")) continue
      try {
        const raw = await fs.readFile(path.join(logsDir, file), "utf-8")
        const data = JSON.parse(raw) as Record<string, Record<string, string>>
        for (const [date, state] of Object.entries(data)) {
          const final = state.final_trade_decision
          runs.push({
            ticker,
            date,
            decision: inferDecisionLabel(final),
            rating: inferRating(state.investment_plan ?? state.trader_investment_decision),
            final_trade_decision: final,
            investment_plan: state.investment_plan,
            trader_investment_plan:
              state.trader_investment_plan ?? state.trader_investment_decision,
            market_report: state.market_report,
            sentiment_report: state.sentiment_report,
            news_report: state.news_report,
            fundamentals_report: state.fundamentals_report,
          })
        }
      } catch {
        // Skip malformed JSON, keep harvesting.
      }
    }
  }

  // Most recent first.
  return runs.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.ticker.localeCompare(b.ticker)))
}

export async function getAgentRun(ticker: string, date: string): Promise<AgentDecision | null> {
  const all = await listAgentRuns()
  return all.find((r) => r.ticker === ticker && r.date === date) ?? null
}

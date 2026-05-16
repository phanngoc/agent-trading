/** Server-only readers for the benchmark/ directory the daily orchestrator writes.
 *
 *  Directory layout (see scripts/benchmark/run_daily.py + run_backtest.py):
 *    benchmarks/
 *      daily/
 *        <YYYY-MM-DD>/
 *          daily_brief.md         ← human-readable summary (markdown)
 *          report.md              ← full backtest report
 *          scorecard.json         ← machine-readable strategy metrics
 *          equity_curves.csv      ← daily NAV per strategy (incl. benchmark)
 *          decisions/<strategy>.json   ← decision + execution log per strategy
 *          _agent_logs/<TICKER>.log    ← raw subprocess output (one file/ticker)
 *        _cron.log                ← timestamped cron history (all runs)
 *      state/
 *        prices/<TICKER>.csv      ← cached OHLCV (raw VND for equities)
 *
 *  Mirrors the pattern in eval-results.ts — readers are pure server-side
 *  filesystem access with conservative parsing so a malformed file never
 *  breaks the whole dashboard.
 */

import { promises as fs } from "node:fs"
import path from "node:path"

const BENCHMARKS_ROOT = path.resolve(process.cwd(), "..", "benchmarks")
const DAILY_DIR = path.join(BENCHMARKS_ROOT, "daily")
const CRON_LOG = path.join(DAILY_DIR, "_cron.log")

// ── Types (kept thin; the dashboard renders most fields opportunistically) ─

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
  profit_factor: number | string  // "inf" when no losing trades
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

export type RunSummary = {
  date: string                           // ISO date
  hasBrief: boolean
  hasScorecard: boolean
  hasReport: boolean
  agentLogs: string[]                    // ticker names found under _agent_logs/
  strategies?: string[]                  // strategy ids if scorecard parsed
}

// ── Helpers ───────────────────────────────────────────────────────────────

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/

async function readJson<T>(filePath: string): Promise<T | null> {
  try {
    const raw = await fs.readFile(filePath, "utf-8")
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

async function readText(filePath: string): Promise<string | null> {
  try {
    return await fs.readFile(filePath, "utf-8")
  } catch {
    return null
  }
}

async function pathExists(p: string): Promise<boolean> {
  try {
    await fs.access(p)
    return true
  } catch {
    return false
  }
}

// ── Public API ───────────────────────────────────────────────────────────

/** List all run-date directories under benchmarks/daily/, newest first.
 *  Skips entries that don't match YYYY-MM-DD (so _cron.log etc. don't leak in). */
export async function listRuns(): Promise<RunSummary[]> {
  let entries: string[]
  try {
    entries = await fs.readdir(DAILY_DIR)
  } catch {
    return []
  }
  const dates = entries.filter((e) => ISO_DATE_RE.test(e)).sort().reverse()
  const out: RunSummary[] = []
  for (const date of dates) {
    const dayDir = path.join(DAILY_DIR, date)
    const briefPath = path.join(dayDir, "daily_brief.md")
    const scorecardPath = path.join(dayDir, "scorecard.json")
    const reportPath = path.join(dayDir, "report.md")
    const agentLogsDir = path.join(dayDir, "_agent_logs")

    const [hasBrief, hasScorecard, hasReport, sc] = await Promise.all([
      pathExists(briefPath),
      pathExists(scorecardPath),
      pathExists(reportPath),
      readJson<RunScorecard>(scorecardPath),
    ])

    let agentLogs: string[] = []
    try {
      const files = await fs.readdir(agentLogsDir)
      agentLogs = files.filter((f) => f.endsWith(".log")).map((f) => f.replace(/\.log$/, ""))
    } catch {
      // No _agent_logs/ — fine.
    }

    out.push({
      date,
      hasBrief,
      hasScorecard,
      hasReport,
      agentLogs,
      strategies: sc?.strategies.map((s) => s.strategy_id),
    })
  }
  return out
}

/** Read everything we have for one run date. */
export async function readRun(date: string): Promise<{
  date: string
  scorecard: RunScorecard | null
  brief: string | null
  report: string | null
  decisions: Record<string, StrategyDecisionDump | null>
  agentLogs: string[]
  equityCurves: string | null   // raw CSV — let the client parse
} | null> {
  if (!ISO_DATE_RE.test(date)) return null
  const dayDir = path.join(DAILY_DIR, date)
  if (!(await pathExists(dayDir))) return null

  const [scorecard, brief, report, equityCurves] = await Promise.all([
    readJson<RunScorecard>(path.join(dayDir, "scorecard.json")),
    readText(path.join(dayDir, "daily_brief.md")),
    readText(path.join(dayDir, "report.md")),
    readText(path.join(dayDir, "equity_curves.csv")),
  ])

  const decisions: Record<string, StrategyDecisionDump | null> = {}
  try {
    const files = await fs.readdir(path.join(dayDir, "decisions"))
    for (const file of files) {
      if (!file.endsWith(".json")) continue
      const id = file.replace(/\.json$/, "")
      decisions[id] = await readJson<StrategyDecisionDump>(
        path.join(dayDir, "decisions", file)
      )
    }
  } catch {
    // No decisions/ — fine on a partial run.
  }

  let agentLogs: string[] = []
  try {
    const files = await fs.readdir(path.join(dayDir, "_agent_logs"))
    agentLogs = files.filter((f) => f.endsWith(".log")).map((f) => f.replace(/\.log$/, ""))
  } catch {
    // No agent logs — fine.
  }

  return { date, scorecard, brief, report, decisions, agentLogs, equityCurves }
}

/** Stream-safe agent-log reader. Returns null if the path escapes
 *  the day directory (defense against `..` injection via URL). */
export async function readAgentLog(date: string, ticker: string): Promise<string | null> {
  if (!ISO_DATE_RE.test(date)) return null
  // Strict whitelist: tickers are uppercase letters / digits / dot (for .VN).
  if (!/^[A-Z0-9.]{1,12}$/.test(ticker.toUpperCase())) return null
  const dayDir = path.join(DAILY_DIR, date)
  const logPath = path.join(dayDir, "_agent_logs", `${ticker.toUpperCase()}.log`)
  // Confirm the resolved path is still inside the day dir.
  if (!logPath.startsWith(dayDir + path.sep)) return null
  return readText(logPath)
}

/** Last N lines of the cron log. Useful for the dashboard "Cron health" pane. */
export async function tailCronLog(maxLines = 200): Promise<string[]> {
  const text = await readText(CRON_LOG)
  if (!text) return []
  const lines = text.split("\n")
  return lines.slice(-maxLines)
}

/** Check whether a run is currently in flight (PID lock file present). */
export async function lockStatus(): Promise<{ running: boolean; pid?: number; startedAt?: string }> {
  const lockPath = path.join(BENCHMARKS_ROOT, "state", "run_daily.lock")
  const text = await readText(lockPath)
  if (!text) return { running: false }
  const m = text.trim().match(/^(\d+)\s+(\S+)/)
  if (!m) return { running: false }
  const pid = Number(m[1])
  if (!Number.isFinite(pid)) return { running: false }
  // We can't `kill -0` from the dashboard's Node runtime safely (sandbox),
  // so we report based on file presence. Stale locks get reaped by the
  // next run_daily invocation.
  return { running: true, pid, startedAt: m[2] }
}

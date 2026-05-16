/** Spawn the Python yfinance helper and parse its JSON output.
 *
 *  Yahoo's direct quote endpoint rate-limits non-browser User-Agents
 *  aggressively. yfinance handles the crumb-cookie handshake correctly,
 *  so we shell out to it. The Python process is short-lived and the
 *  output is small (a few KB), so the IPC cost is fine for a polled
 *  dashboard. We rely on Next.js fetch-style caching at the route
 *  layer to keep call volume low.
 */

import { spawn } from "node:child_process"
import path from "node:path"

type RawQuote = {
  symbol: string
  price: number | null
  change: number
  changePercent: number
  currency: string
  history: { t: string; c: number }[]
  error?: string
}

const PY = process.env.TRADINGAGENTS_PYTHON
  || path.resolve(process.cwd(), "..", "venv", "bin", "python")

const SCRIPT = path.resolve(process.cwd(), "scripts", "fetch_quotes.py")

export function fetchYFinanceQuotes(symbols: string[]): Promise<RawQuote[]> {
  if (symbols.length === 0) return Promise.resolve([])

  return new Promise((resolve, reject) => {
    const child = spawn(PY, [SCRIPT, ...symbols], {
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    })
    let stdout = ""
    let stderr = ""
    child.stdout.on("data", (chunk) => { stdout += chunk })
    child.stderr.on("data", (chunk) => { stderr += chunk })
    child.on("error", (err) => reject(err))
    child.on("close", (code) => {
      if (code !== 0) {
        return reject(new Error(`fetch_quotes.py exit ${code}: ${stderr.slice(0, 400)}`))
      }
      try {
        const parsed = JSON.parse(stdout) as { quotes: RawQuote[] }
        resolve(parsed.quotes ?? [])
      } catch (e) {
        reject(new Error(`fetch_quotes.py bad JSON: ${(e as Error).message}`))
      }
    })
  })
}

import { spawn } from "node:child_process"
import path from "node:path"
import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** GET /api/markets/detail/[symbol] — exchange-level aggregations.
 *
 *  Wraps ``dashboard/scripts/fetch_market_detail.py`` which calls
 *  vnstock's Trading.price_board for the index's constituents and
 *  rolls up advancers/decliners, flow distribution, top index
 *  contributors, and aggregate foreign trading. Same subprocess
 *  pattern as the existing ``fetch_quotes.py`` route — short-lived
 *  Python with a single JSON dict on stdout.
 *
 *  Symbol mapping is done in the Python helper; we accept anything the
 *  client sends and let the helper return ``{"error": ...}`` for
 *  unsupported codes.
 */

const PY = process.env.TRADINGAGENTS_PYTHON
  || path.resolve(process.cwd(), "..", "venv", "bin", "python")
const SCRIPT = path.resolve(process.cwd(), "scripts", "fetch_market_detail.py")

const SYMBOL_RE = /^[\^A-Za-z0-9.\-]{1,16}$/   // defense-in-depth — the script also validates

function runPython(symbol: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const child = spawn(PY, [SCRIPT, symbol], {
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    })
    let stdout = ""
    let stderr = ""
    child.stdout.on("data", (c) => { stdout += c })
    child.stderr.on("data", (c) => { stderr += c })
    child.on("error", reject)
    child.on("close", (code) => {
      if (code !== 0) {
        return reject(new Error(`fetch_market_detail.py exit ${code}: ${stderr.slice(0, 400)}`))
      }
      try {
        resolve(JSON.parse(stdout))
      } catch (e) {
        reject(new Error(`fetch_market_detail.py bad JSON: ${(e as Error).message}`))
      }
    })
  })
}

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ symbol: string }> },
) {
  const { symbol } = await ctx.params
  if (!SYMBOL_RE.test(symbol)) {
    return NextResponse.json({ error: "invalid symbol" }, { status: 400 })
  }
  try {
    const data = await runPython(symbol)
    return NextResponse.json(data, {
      // 60s ISR-style caching on the route — price_board is intraday and
      // a brief stale window keeps the dashboard snappy without pummeling
      // vnstock's rate limits.
      headers: { "Cache-Control": "public, max-age=60, stale-while-revalidate=120" },
    })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 502 },
    )
  }
}

import { NextResponse } from "next/server"
import { spawn } from "node:child_process"
import path from "node:path"
import { randomUUID } from "node:crypto"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** Spawn `python main.py --ticker <T>` against the parent repo and return
 *  immediately with a run_id. The Python process inherits the user's
 *  Claude Code OAuth credentials via the parent shell env, so no API
 *  key is plumbed through this route. Stdout/stderr are dropped — the
 *  authoritative output lands in eval_results/<TICKER>/ which the
 *  /api/agent/runs endpoint reads.
 *
 *  This is intentionally fire-and-forget. The full graph takes minutes;
 *  the UI should poll /api/agent/runs to detect completion.
 */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { ticker?: string; date?: string }
  const ticker = (body.ticker ?? "").trim()
  if (!/^[A-Za-z0-9.\-^]{1,32}$/.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 })
  }

  const repoRoot = path.resolve(process.cwd(), "..")
  const py = process.env.TRADINGAGENTS_PYTHON || path.join(repoRoot, "venv", "bin", "python")
  const date = body.date ?? new Date().toISOString().slice(0, 10)
  const runId = randomUUID()

  const child = spawn(
    py,
    [
      "main.py",
      "--ticker", ticker,
      "--date", date,
      "--provider", "anthropic",
      "--deep-model", "claude-haiku-4-5",
      "--quick-model", "claude-haiku-4-5",
      "--analysts", "market,news",
    ],
    { cwd: repoRoot, detached: true, stdio: "ignore", env: { ...process.env } },
  )
  child.unref()

  return NextResponse.json({ ok: true, run_id: runId, ticker, date })
}

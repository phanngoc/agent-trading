import { NextResponse } from "next/server"
import { spawn } from "node:child_process"
import { createWriteStream } from "node:fs"
import { promises as fs } from "node:fs"
import path from "node:path"
import { randomUUID } from "node:crypto"
import { logPath, runDir, writeStatus } from "@/lib/run-logs"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** Spawn `python main.py --debug --ticker <T>` in the parent repo. Captures
 *  stdout + stderr to eval_results/_runs/<run_id>/stdout.log so the
 *  `/api/agent/logs/[runId]` SSE endpoint can tail it. status.json tracks
 *  running/done/error so the SSE tail knows when to close the stream.
 *
 *  --debug makes TradingAgentsGraph.propagate() stream every node's output
 *  via pretty_print(), which is what the user sees in the drawer. Auth
 *  inherits the parent shell env (Claude Code OAuth from keychain).
 */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as {
    ticker?: string
    date?: string
    analysts?: string
  }
  const ticker = (body.ticker ?? "").trim()
  if (!/^[A-Za-z0-9.\-^]{1,32}$/.test(ticker)) {
    return NextResponse.json({ error: "invalid ticker" }, { status: 400 })
  }

  const date = body.date ?? new Date().toISOString().slice(0, 10)
  const analysts = body.analysts ?? "market,news"
  const runId = randomUUID()

  const repoRoot = path.resolve(process.cwd(), "..")
  const py = process.env.TRADINGAGENTS_PYTHON || path.join(repoRoot, "venv", "bin", "python")

  // Make sure the per-run dir exists before the child tries to write to it.
  await fs.mkdir(runDir(runId), { recursive: true })
  await writeStatus(runId, {
    status: "running",
    ticker,
    date,
    started_at: new Date().toISOString(),
  })

  // Open the log file as a write stream so we can pipe both stdout and
  // stderr into it without buffering everything in memory.
  const out = createWriteStream(logPath(runId), { flags: "a" })
  out.write(`[trigger] run_id=${runId} ticker=${ticker} date=${date} analysts=${analysts}\n`)
  out.write(`[trigger] cwd=${repoRoot}\n`)
  out.write(`[trigger] python=${py}\n\n`)

  const child = spawn(
    py,
    [
      "-u",                              // unbuffered stdout — critical for live tailing
      "main.py",
      "--ticker", ticker,
      "--date", date,
      "--provider", "anthropic",
      "--deep-model", "claude-haiku-4-5",
      "--quick-model", "claude-haiku-4-5",
      "--analysts", analysts,
      "--debug",
    ],
    {
      cwd: repoRoot,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    },
  )

  // Tee both streams into the same log so the user sees them interleaved.
  child.stdout.pipe(out, { end: false })
  child.stderr.pipe(out, { end: false })

  child.on("close", async (code) => {
    out.write(`\n[trigger] exit code=${code} at ${new Date().toISOString()}\n`)
    out.end()
    await writeStatus(runId, {
      status: code === 0 ? "done" : "error",
      ticker,
      date,
      started_at: new Date().toISOString(),  // overwritten in caller — we don't read this back
      finished_at: new Date().toISOString(),
      exit_code: code,
    }).catch(() => {})
  })

  child.on("error", async (err) => {
    out.write(`\n[trigger] spawn error: ${err.message}\n`)
    out.end()
    await writeStatus(runId, {
      status: "error",
      ticker,
      date,
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      exit_code: -1,
    }).catch(() => {})
  })

  return NextResponse.json({ ok: true, run_id: runId, ticker, date })
}

import { NextResponse } from "next/server"
import { readRun } from "@/lib/benchmark"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** GET /api/benchmark/runs/[date] — full payload for one run.
 *
 *  Returns scorecard, daily_brief markdown, report markdown, per-strategy
 *  decision/execution logs, the list of available agent-log tickers, and
 *  the raw equity_curves.csv string (parsed client-side so the network
 *  payload stays small and parsing is co-located with rendering).
 */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ date: string }> },
) {
  const { date } = await ctx.params
  try {
    const run = await readRun(date)
    if (!run) {
      return NextResponse.json({ error: `No run found for ${date}` }, { status: 404 })
    }
    return NextResponse.json(run)
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e) },
      { status: 500 },
    )
  }
}

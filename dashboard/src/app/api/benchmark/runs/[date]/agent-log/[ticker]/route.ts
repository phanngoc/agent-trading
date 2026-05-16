import { NextResponse } from "next/server"
import { readAgentLog } from "@/lib/benchmark"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** GET /api/benchmark/runs/[date]/agent-log/[ticker] — full text snapshot.
 *
 *  Use this for *finished* agent runs where streaming adds no value. For a
 *  run that is currently in flight, the client should instead subscribe to
 *  the `/stream` sibling route which tails the same file via SSE.
 */
export async function GET(
  _req: Request,
  ctx: { params: Promise<{ date: string; ticker: string }> },
) {
  const { date, ticker } = await ctx.params
  const text = await readAgentLog(date, ticker)
  if (text === null) {
    return NextResponse.json({ error: `log not found for ${ticker}` }, { status: 404 })
  }
  return new Response(text, {
    status: 200,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  })
}

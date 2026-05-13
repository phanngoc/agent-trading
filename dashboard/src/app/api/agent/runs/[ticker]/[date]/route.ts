import { NextResponse } from "next/server"
import { getAgentRun } from "@/lib/eval-results"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET(
  _req: Request,
  ctx: { params: Promise<{ ticker: string; date: string }> },
) {
  const { ticker, date } = await ctx.params
  const run = await getAgentRun(decodeURIComponent(ticker), date)
  if (!run) return NextResponse.json({ error: "not found" }, { status: 404 })
  return NextResponse.json(run)
}

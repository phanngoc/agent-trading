import { NextResponse } from "next/server"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

const TREND_NEWS_URL = process.env.TREND_NEWS_URL ?? "http://localhost:8000"
const TREND_NEWS_API_KEY = process.env.TREND_NEWS_API_KEY ?? "dev-key"

/** Proxy to trend_news scheduler.
 *
 *  GET   → /api/v1/scheduler/status     (job state, next/last run, durations)
 *  POST  → /api/v1/scheduler/trigger/<job>
 *          {job?: "crawl" | "llm_eval"} — default "crawl"
 *
 *  This is the user-facing crawl-now button: kicks the in-process
 *  scheduler ad-hoc so they don't wait for the 30-min cycle.
 */
export async function GET() {
  try {
    const r = await fetch(`${TREND_NEWS_URL}/api/v1/scheduler/status`, {
      headers: { "X-API-Key": TREND_NEWS_API_KEY },
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    })
    if (!r.ok) {
      return NextResponse.json(
        { error: `scheduler status ${r.status}`, jobs: [] },
        { status: 200 },
      )
    }
    return NextResponse.json(await r.json())
  } catch (e) {
    return NextResponse.json({
      error: e instanceof Error ? e.message : String(e),
      hint: "trend_news không chạy — bấm restart pill trên /agent.",
      jobs: [],
    }, { status: 200 })
  }
}

export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { job?: string }
  const job = body.job ?? "crawl"
  if (!/^[a-z_]{1,32}$/.test(job)) {
    return NextResponse.json({ error: "invalid job name" }, { status: 400 })
  }
  try {
    const r = await fetch(`${TREND_NEWS_URL}/api/v1/scheduler/trigger/${job}`, {
      method: "POST",
      headers: { "X-API-Key": TREND_NEWS_API_KEY },
      signal: AbortSignal.timeout(8000),
      cache: "no-store",
    })
    if (!r.ok) {
      const txt = await r.text().catch(() => "")
      return NextResponse.json(
        { ok: false, error: `trend_news ${r.status}`, detail: txt.slice(0, 240) },
        { status: 200 },
      )
    }
    return NextResponse.json({ ok: true, result: await r.json() })
  } catch (e) {
    return NextResponse.json({
      ok: false,
      error: e instanceof Error ? e.message : String(e),
    }, { status: 200 })
  }
}

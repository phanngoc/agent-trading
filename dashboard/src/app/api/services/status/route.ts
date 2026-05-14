import { NextResponse } from "next/server"
import { getTrendNewsStatus, restartTrendNews } from "@/lib/services"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET() {
  const trend_news = await getTrendNewsStatus()
  return NextResponse.json({ services: { trend_news } })
}

/** POST { action: "restart" } — restart a service by name (currently only trend_news). */
export async function POST(req: Request) {
  const body = (await req.json().catch(() => ({}))) as { action?: string; service?: string }
  if (body.service !== "trend_news") {
    return NextResponse.json({ error: "unknown service" }, { status: 400 })
  }
  if (body.action !== "restart") {
    return NextResponse.json({ error: "unsupported action" }, { status: 400 })
  }
  const status = await restartTrendNews()
  return NextResponse.json({ ok: true, status })
}

import { NextResponse } from "next/server"
import { tailCronLog } from "@/lib/benchmark"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** GET /api/benchmark/cron-log — return the last N lines of _cron.log.
 *
 *  Optional ?lines=N query parameter caps output. Used by the dashboard's
 *  "Cron health" panel to show recent automatic-run history without
 *  shipping the entire (potentially-large) file.
 */
export async function GET(req: Request) {
  const url = new URL(req.url)
  const lines = Math.min(Math.max(1, Number(url.searchParams.get("lines") ?? "200")), 2000)
  try {
    const log = await tailCronLog(lines)
    return NextResponse.json({ lines: log, count: log.length })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e), lines: [] },
      { status: 500 },
    )
  }
}

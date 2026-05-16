import { NextResponse } from "next/server"
import { listRuns, lockStatus } from "@/lib/benchmark"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** GET /api/benchmark/runs — list every available run date with summary metadata.
 *
 *  Also returns the current ``running`` flag so the overview page can show a
 *  "run in flight" banner without a separate request.
 */
export async function GET() {
  try {
    const [runs, lock] = await Promise.all([listRuns(), lockStatus()])
    return NextResponse.json({ runs, lock })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e), runs: [], lock: { running: false } },
      { status: 500 },
    )
  }
}

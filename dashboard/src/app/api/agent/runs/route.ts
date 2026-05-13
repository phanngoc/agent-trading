import { NextResponse } from "next/server"
import { listAgentRuns } from "@/lib/eval-results"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function GET() {
  try {
    const runs = await listAgentRuns()
    return NextResponse.json({ runs })
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : String(e), runs: [] },
      { status: 500 },
    )
  }
}

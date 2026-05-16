import { promises as fs } from "node:fs"
import path from "node:path"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** SSE tail of one ticker's agent log for a benchmark run.
 *
 *  Mirrors the existing `/api/agent/logs/[runId]` pattern: emit any
 *  bytes already on disk first (so a late subscriber catches up), then
 *  poll every 500ms for new content. Closes the stream on:
 *
 *    - file disappearing (run never started / cleaned up)
 *    - explicit done sentinel (we don't have status.json for benchmark
 *      runs, so we use a 30-second idle window — no new bytes for 30s
 *      means the subprocess has exited)
 *    - 15-minute absolute timeout (EventSource clients auto-reconnect)
 *
 *  Event types:
 *    data: { kind: "log",   text: "..."    }
 *    data: { kind: "done",  reason: "..." }
 *    data: { kind: "error", message: "..." }
 */

const POLL_MS = 500
const IDLE_DONE_MS = 30_000      // 30s with no new bytes ⇒ run finished
const MAX_DURATION_MS = 15 * 60_000

const BENCHMARKS_ROOT = path.resolve(process.cwd(), "..", "benchmarks")
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/

export async function GET(
  req: Request,
  ctx: { params: Promise<{ date: string; ticker: string }> },
) {
  const { date, ticker } = await ctx.params

  // Input validation — same whitelist as the snapshot route so SSE
  // can't be tricked into reading arbitrary files via path traversal.
  if (!ISO_DATE_RE.test(date) || !/^[A-Z0-9.]{1,12}$/.test(ticker.toUpperCase())) {
    return new Response("invalid params", { status: 400 })
  }

  const dayDir = path.join(BENCHMARKS_ROOT, "daily", date)
  const logFile = path.join(dayDir, "_agent_logs", `${ticker.toUpperCase()}.log`)
  if (!logFile.startsWith(dayDir + path.sep)) {
    return new Response("invalid params", { status: 400 })
  }

  const encoder = new TextEncoder()

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const enqueue = (kind: string, payload: Record<string, unknown>) => {
        try {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ kind, ...payload })}\n\n`),
          )
        } catch {
          // Controller already closed by the abort handler.
        }
      }

      let handle: Awaited<ReturnType<typeof fs.open>> | null = null
      let cursor = 0
      let lastNewBytesAt = Date.now()
      const startedAt = Date.now()

      try {
        handle = await fs.open(logFile, "r")
      } catch {
        enqueue("error", { message: `log not found: ${ticker} on ${date}` })
        controller.close()
        return
      }

      const flushNew = async () => {
        if (!handle) return false
        const st = await handle.stat()
        if (st.size > cursor) {
          const buf = Buffer.alloc(st.size - cursor)
          await handle.read(buf, 0, buf.length, cursor)
          cursor = st.size
          enqueue("log", { text: buf.toString("utf-8") })
          lastNewBytesAt = Date.now()
        }
        return true
      }

      await flushNew()

      const tick = async () => {
        try {
          await flushNew()

          if (Date.now() - lastNewBytesAt > IDLE_DONE_MS) {
            enqueue("done", { reason: "idle" })
            await handle?.close().catch(() => {})
            controller.close()
            return false
          }
          if (Date.now() - startedAt > MAX_DURATION_MS) {
            enqueue("error", { message: "stream timeout — reconnect to continue" })
            await handle?.close().catch(() => {})
            controller.close()
            return false
          }
          return true
        } catch (e) {
          enqueue("error", { message: e instanceof Error ? e.message : String(e) })
          await handle?.close().catch(() => {})
          controller.close()
          return false
        }
      }

      const interval = setInterval(async () => {
        const keepGoing = await tick()
        if (!keepGoing) clearInterval(interval)
      }, POLL_MS)

      req.signal.addEventListener("abort", () => {
        clearInterval(interval)
        handle?.close().catch(() => {})
        try { controller.close() } catch { /* already closed */ }
      })
    },
  })

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  })
}

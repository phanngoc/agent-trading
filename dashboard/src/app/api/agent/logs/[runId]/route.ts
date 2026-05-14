import { promises as fs } from "node:fs"
import { logPath, readStatus } from "@/lib/run-logs"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

/** Server-Sent Events tail for an agent run's stdout.log.
 *
 *  Event types emitted:
 *    data: { kind: "log",    text: "..."  }    each new line/chunk
 *    data: { kind: "status", ...              } whenever status.json changes
 *    data: { kind: "done",   exit_code: N }    final event before close
 *
 *  Strategy: read all existing bytes first (so a late subscriber gets the
 *  back-log), then poll for new bytes every 500ms. status.json is read at
 *  the same cadence — when it flips out of "running", we flush remaining
 *  bytes, send a `done` event, and close the stream.
 *
 *  Bounded duration: 15 min max. If the run is still going beyond that,
 *  the client will reconnect (EventSource auto-retries) and resume.
 */
const POLL_MS = 500
const MAX_DURATION_MS = 15 * 60_000

export async function GET(
  req: Request,
  ctx: { params: Promise<{ runId: string }> },
) {
  const { runId } = await ctx.params
  const file = logPath(runId)

  const encoder = new TextEncoder()

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const enqueue = (kind: string, payload: Record<string, unknown>) => {
        try {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ kind, ...payload })}\n\n`),
          )
        } catch {
          // Controller closed (client gone) — let the cleanup handler clear timers.
        }
      }

      let cursor = 0
      let lastStatus: string | null = null
      const startedAt = Date.now()

      // Initial snapshot: flush whatever's already on disk so a late
      // subscriber doesn't see a blank screen.
      const handle = await fs.open(file, "r").catch(() => null)
      if (!handle) {
        enqueue("error", { message: `log file not found for run ${runId}` })
        controller.close()
        return
      }

      const flushNew = async () => {
        const st = await handle.stat()
        if (st.size > cursor) {
          const buf = Buffer.alloc(st.size - cursor)
          await handle.read(buf, 0, buf.length, cursor)
          cursor = st.size
          enqueue("log", { text: buf.toString("utf-8") })
        }
      }

      await flushNew()

      const tick = async () => {
        try {
          await flushNew()
          const s = await readStatus(runId)
          if (s && s.status !== lastStatus) {
            lastStatus = s.status
            enqueue("status", {
              status: s.status,
              ticker: s.ticker,
              date: s.date,
              exit_code: s.exit_code ?? null,
            })
          }
          if (s && s.status !== "running") {
            // One more flush in case child wrote between our last read and
            // status flip, then announce completion.
            await flushNew()
            enqueue("done", { exit_code: s.exit_code ?? null })
            await handle.close().catch(() => {})
            controller.close()
            return false
          }
          if (Date.now() - startedAt > MAX_DURATION_MS) {
            enqueue("error", { message: "stream timeout — reconnect to continue" })
            await handle.close().catch(() => {})
            controller.close()
            return false
          }
          return true
        } catch (e) {
          enqueue("error", { message: e instanceof Error ? e.message : String(e) })
          await handle.close().catch(() => {})
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
        handle.close().catch(() => {})
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

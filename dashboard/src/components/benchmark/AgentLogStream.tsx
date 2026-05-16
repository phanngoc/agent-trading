"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, CheckCircle2, XCircle, Terminal } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type LogEvent =
  | { kind: "log"; text: string }
  | { kind: "done"; reason: string }
  | { kind: "error"; message: string }

type Status = "idle" | "streaming" | "done" | "error"

/** Live tail of one ticker's agent log via SSE.
 *
 *  Used by /benchmark/[date] when the user clicks a ticker tab — opens
 *  an EventSource, appends each "log" chunk to a scrollback buffer,
 *  closes on "done" or "error". The component degrades gracefully when
 *  the stream endpoint 404s (no log yet) by showing the static snapshot
 *  endpoint as a fallback.
 *
 *  Auto-scrolls to bottom unless the user has scrolled up — once they
 *  do, we leave the cursor put so they can read past chunks while new
 *  ones still arrive.
 */
export function AgentLogStream({
  date,
  ticker,
  autoStart = true,
}: {
  date: string
  ticker: string
  autoStart?: boolean
}) {
  const [lines, setLines] = useState<string[]>([])
  const [status, setStatus] = useState<Status>("idle")
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const esRef = useRef<EventSource | null>(null)

  const reset = () => {
    esRef.current?.close()
    esRef.current = null
    setLines([])
    setStatus("idle")
    setError(null)
  }

  const start = () => {
    reset()
    setStatus("streaming")

    const es = new EventSource(`/api/benchmark/runs/${date}/agent-log/${ticker}/stream`)
    esRef.current = es

    es.onmessage = (msg) => {
      try {
        const evt = JSON.parse(msg.data) as LogEvent
        if (evt.kind === "log") {
          const chunks = evt.text.split(/\r?\n/).filter((l) => l.length > 0)
          if (chunks.length) setLines((prev) => [...prev, ...chunks])
        } else if (evt.kind === "done") {
          setStatus("done")
          es.close()
        } else if (evt.kind === "error") {
          setStatus("error")
          setError(evt.message)
          es.close()
        }
      } catch {
        // Ignore malformed frames — the next one will likely be fine.
      }
    }

    es.onerror = () => {
      setStatus("error")
      setError("connection lost")
      es.close()
    }
  }

  // Kick off on mount when autoStart, and re-stream when ticker/date changes.
  useEffect(() => {
    if (!autoStart) return
    start()
    return () => {
      esRef.current?.close()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, ticker, autoStart])

  // Auto-scroll to bottom only when the user is sticking to the tail.
  useEffect(() => {
    const el = containerRef.current
    if (!el || !stickToBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [lines])

  const onScroll = () => {
    const el = containerRef.current
    if (!el) return
    // Within ~24px of bottom counts as "sticking".
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }

  return (
    <Card>
      <CardContent className="p-3 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Terminal className="size-4 text-muted-foreground" />
            <span className="font-medium">{ticker}</span>
            <span className="text-xs text-muted-foreground">{date}</span>
            <StatusBadge status={status} />
          </div>
          <div className="flex gap-2">
            {status === "streaming" ? (
              <Button size="sm" variant="ghost" onClick={() => esRef.current?.close()}>Stop</Button>
            ) : (
              <Button size="sm" variant="ghost" onClick={start}>Re-stream</Button>
            )}
          </div>
        </div>
        {error && (
          <p className="text-xs text-red-600 dark:text-red-400">⚠ {error}</p>
        )}
        <div
          ref={containerRef}
          onScroll={onScroll}
          className={cn(
            "h-[420px] overflow-y-auto rounded border bg-background/50 p-2",
            "font-mono text-xs leading-relaxed",
          )}
        >
          {lines.length === 0 && status === "idle" && (
            <p className="text-muted-foreground italic">Bấm Re-stream để tail log.</p>
          )}
          {lines.length === 0 && status === "streaming" && (
            <p className="text-muted-foreground italic">Chờ output…</p>
          )}
          {lines.map((l, i) => (
            <div key={i} className="whitespace-pre-wrap break-words">{l}</div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function StatusBadge({ status }: { status: Status }) {
  if (status === "streaming") {
    return (
      <Badge variant="outline" className="gap-1 text-xs">
        <Loader2 className="size-3 animate-spin" /> live
      </Badge>
    )
  }
  if (status === "done") {
    return (
      <Badge variant="outline" className="gap-1 text-xs text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="size-3" /> done
      </Badge>
    )
  }
  if (status === "error") {
    return (
      <Badge variant="outline" className="gap-1 text-xs text-red-600 dark:text-red-400">
        <XCircle className="size-3" /> error
      </Badge>
    )
  }
  return <Badge variant="outline" className="text-xs text-muted-foreground">idle</Badge>
}

"use client"

import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { CheckCircle2, Loader2, XCircle, Terminal } from "lucide-react"
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerDescription,
} from "@/components/ui/drawer"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type Status = "running" | "done" | "error"

type LogEvent =
  | { kind: "log"; text: string }
  | { kind: "status"; status: Status; ticker: string; date: string; exit_code: number | null }
  | { kind: "done"; exit_code: number | null }
  | { kind: "error"; message: string }

export function AgentRunDrawer({
  runId,
  ticker,
  open,
  onOpenChange,
}: {
  runId: string | null
  ticker: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [lines, setLines] = useState<string[]>([])
  const [status, setStatus] = useState<Status>("running")
  const [exitCode, setExitCode] = useState<number | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const logRef = useRef<HTMLDivElement>(null)
  const startedAtRef = useRef<number>(0)
  const qc = useQueryClient()

  // Subscribe to SSE when a run is active. Reset state every time the runId
  // changes so reopening for a new run doesn't carry old output.
  useEffect(() => {
    if (!runId || !open) return
    setLines([])
    setStatus("running")
    setExitCode(null)
    startedAtRef.current = Date.now()

    const es = new EventSource(`/api/agent/logs/${runId}`)

    es.onmessage = (msg) => {
      try {
        const evt = JSON.parse(msg.data) as LogEvent
        if (evt.kind === "log") {
          // Append by splitting into lines so the renderer can virtualize later.
          const newLines = evt.text.split(/\r?\n/).filter((l) => l.length > 0)
          if (newLines.length > 0) setLines((prev) => [...prev, ...newLines])
        } else if (evt.kind === "status") {
          setStatus(evt.status)
        } else if (evt.kind === "done") {
          setExitCode(evt.exit_code)
          setStatus(evt.exit_code === 0 ? "done" : "error")
          es.close()
          if (evt.exit_code === 0) {
            toast.success(`Phân tích ${ticker} hoàn tất`, {
              description: "Kết quả đã được ghi vào eval_results.",
            })
            // Surface the new result in the runs list immediately.
            qc.invalidateQueries({ queryKey: ["agent", "runs"] })
          } else {
            toast.error(`Phân tích ${ticker} thất bại (exit ${evt.exit_code})`)
          }
        } else if (evt.kind === "error") {
          setStatus("error")
          toast.error("Stream error", { description: evt.message })
        }
      } catch {
        // Bad JSON — ignore individual message but keep stream open.
      }
    }

    es.onerror = () => {
      // The browser EventSource auto-retries; we just surface the state.
      // If the run finished normally, we already saw `done` and closed.
    }

    return () => {
      es.close()
    }
  }, [runId, open, ticker, qc])

  // Auto-scroll to bottom on new lines.
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [lines])

  // Tick elapsed time while running.
  useEffect(() => {
    if (status !== "running") return
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [status])

  const StatusIcon =
    status === "running" ? Loader2 :
    status === "done" ? CheckCircle2 :
    XCircle
  const statusClass =
    status === "running" ? "text-[color:var(--neutral)]" :
    status === "done" ? "text-[color:var(--bullish)]" :
    "text-[color:var(--bearish)]"

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent className="max-h-[85vh]">
        <DrawerHeader className="border-b">
          <div className="flex items-start justify-between gap-3">
            <div>
              <DrawerTitle className="flex items-center gap-2 text-base">
                <Terminal className="size-4" />
                {ticker}
                <Badge variant="outline" className={cn("gap-1", statusClass)}>
                  <StatusIcon className={cn("size-3", status === "running" && "animate-spin")} />
                  {status === "running" ? "Đang chạy" : status === "done" ? "Hoàn tất" : "Lỗi"}
                </Badge>
              </DrawerTitle>
              <DrawerDescription className="text-xs">
                run_id <code className="font-mono">{runId?.slice(0, 8)}…</code>
                {status === "running" && (
                  <span className="ml-2 tabular">⏱ {formatElapsed(elapsed)}</span>
                )}
                {exitCode !== null && status !== "running" && (
                  <span className="ml-2">exit={exitCode}</span>
                )}
              </DrawerDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              Đóng
            </Button>
          </div>
        </DrawerHeader>

        <div
          ref={logRef}
          className="flex-1 overflow-y-auto bg-black/40 dark:bg-black/60 font-mono text-xs leading-relaxed px-4 py-3 min-h-[40vh]"
        >
          {lines.length === 0 ? (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              Đang khởi tạo agent...
            </div>
          ) : (
            lines.map((line, i) => (
              <div
                key={i}
                className={cn(
                  "whitespace-pre-wrap",
                  line.includes("[trigger]") && "text-[color:var(--neutral)]",
                  line.includes("Ai Message") && "text-[color:var(--bullish)] font-semibold mt-2",
                  line.includes("Tool Calls") && "text-[color:var(--chart-3)]",
                  line.includes("FINAL TRANSACTION") && "text-yellow-400 font-bold",
                  /error|Error|EXCEPTION/.test(line) && "text-[color:var(--bearish)]",
                )}
              >
                {line}
              </div>
            ))
          )}
        </div>
      </DrawerContent>
    </Drawer>
  )
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}

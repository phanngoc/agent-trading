"use client"

import { useState } from "react"
import { Play, Loader2 } from "lucide-react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api-client"

export function TriggerAgentButton({ defaultTicker = "VIC.VN" }: { defaultTicker?: string }) {
  const [busy, setBusy] = useState(false)
  const [ticker, setTicker] = useState(defaultTicker)
  const qc = useQueryClient()

  async function run() {
    setBusy(true)
    try {
      const r = await api.triggerAgent(ticker)
      toast.success(`Đã khởi chạy phân tích ${r.ticker}`, {
        description: "Quá trình mất 1–5 phút. Trang sẽ tự refresh khi có kết quả mới.",
      })
      // Poll the runs endpoint every 30s for a few minutes to pick up the new run.
      const stop = setInterval(() => qc.invalidateQueries({ queryKey: ["agent", "runs"] }), 30_000)
      setTimeout(() => clearInterval(stop), 6 * 60_000)
    } catch (e) {
      toast.error("Lỗi khởi chạy agent", {
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        placeholder="VIC.VN"
        className="h-8 w-32 rounded-md border bg-background px-2 text-sm tabular focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 outline-none"
      />
      <Button size="sm" onClick={run} disabled={busy || !ticker}>
        {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />}
        Chạy phân tích
      </Button>
    </div>
  )
}

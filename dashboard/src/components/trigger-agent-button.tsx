"use client"

import { useState } from "react"
import { Play, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api-client"
import { AgentRunDrawer } from "@/components/agent-run-drawer"

export function TriggerAgentButton({ defaultTicker = "VIC.VN" }: { defaultTicker?: string }) {
  const [busy, setBusy] = useState(false)
  const [ticker, setTicker] = useState(defaultTicker)
  const [activeRun, setActiveRun] = useState<{ runId: string; ticker: string } | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

  async function run() {
    setBusy(true)
    try {
      const r = await api.triggerAgent(ticker)
      setActiveRun({ runId: r.run_id, ticker: r.ticker })
      setDrawerOpen(true)
      toast.success(`Đã khởi chạy ${r.ticker}`, {
        description: "Theo dõi tiến trình ở khung log bên dưới.",
      })
    } catch (e) {
      toast.error("Lỗi khởi chạy agent", {
        description: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
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
        {activeRun && !drawerOpen && (
          <Button size="sm" variant="outline" onClick={() => setDrawerOpen(true)}>
            Xem log
          </Button>
        )}
      </div>

      <AgentRunDrawer
        runId={activeRun?.runId ?? null}
        ticker={activeRun?.ticker ?? ""}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </>
  )
}

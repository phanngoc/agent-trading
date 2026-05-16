"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Activity, Loader2, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type ServiceState = "up" | "down" | "starting"

type Status = {
  services: { trend_news: { state: ServiceState; url: string; pid?: number; message?: string } }
}

export function ServiceStatusPill({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()

  const { data, isLoading } = useQuery<Status>({
    queryKey: ["services", "status"],
    queryFn: () => fetch("/api/services/status").then((r) => r.json()),
    refetchInterval: 10_000,
  })

  const restart = useMutation({
    mutationFn: () =>
      fetch("/api/services/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ service: "trend_news", action: "restart" }),
      }).then((r) => r.json()),
    onSuccess: () => {
      toast.success("Đã yêu cầu restart trend_news")
      qc.invalidateQueries({ queryKey: ["services", "status"] })
    },
    onError: (e) => toast.error("Restart thất bại", { description: String(e) }),
  })

  if (isLoading) {
    return (
      <Badge variant="outline" className="gap-1 text-xs">
        <Loader2 className="size-3 animate-spin" /> Services…
      </Badge>
    )
  }

  const tn = data?.services?.trend_news
  const state: ServiceState = tn?.state ?? "down"
  const stateClass =
    state === "up" ? "text-[color:var(--bullish)]" :
    state === "starting" ? "text-[color:var(--neutral)]" :
    "text-[color:var(--bearish)]"

  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" className={cn("gap-1 text-xs", stateClass)}>
        <Activity className="size-3" />
        trend_news · {state}
      </Badge>
      {!compact && tn?.message && (
        <span className="text-xs text-muted-foreground hidden md:inline">
          {tn.message}
        </span>
      )}
      <Button
        variant="ghost"
        size="icon-xs"
        onClick={() => restart.mutate()}
        disabled={restart.isPending}
        aria-label="Restart trend_news"
      >
        {restart.isPending ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}
      </Button>
    </div>
  )
}

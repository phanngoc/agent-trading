"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { ChevronRight } from "lucide-react"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { TriggerAgentButton } from "@/components/trigger-agent-button"
import { ServiceStatusPill } from "@/components/service-status-pill"
import { decisionClass } from "@/lib/format"

export default function AgentPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["agent", "runs"],
    queryFn: api.agentRuns,
    refetchInterval: 30_000,
  })

  const runs = data?.runs ?? []

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Trade Agent</h1>
          <p className="text-sm text-muted-foreground">
            Lịch sử các lần chạy multi-agent (market → news → bull/bear → trader → risk).
            Mỗi quyết định kèm full debate history + sentiment + fundamentals.
          </p>
          <div className="mt-2"><ServiceStatusPill /></div>
        </div>
        <TriggerAgentButton />
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Lịch sử ({runs.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-14" />)}
            </div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Chưa có run nào. Bấm <strong>Chạy phân tích</strong> ở trên để bắt đầu.
            </p>
          ) : (
            <ul className="divide-y">
              {runs.map((r) => (
                <li key={`${r.ticker}-${r.date}`}>
                  <Link
                    href={`/agent/${encodeURIComponent(r.ticker)}/${r.date}`}
                    className="flex items-center justify-between gap-3 py-3 transition-colors hover:bg-accent/40 rounded-md px-2 -mx-2"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{r.ticker}</span>
                          <span className="text-xs text-muted-foreground tabular">{r.date}</span>
                        </div>
                        {r.final_trade_decision && (
                          <p className="text-xs text-muted-foreground line-clamp-1 max-w-md">
                            {r.final_trade_decision.replace(/[#*\n]+/g, " ").slice(0, 180)}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="outline" className={`text-xs ${decisionClass(r.decision)}`}>
                        {r.decision}
                      </Badge>
                      {r.rating && (
                        <Badge variant="secondary" className="text-xs">{r.rating}</Badge>
                      )}
                      <ChevronRight className="size-4 text-muted-foreground" />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

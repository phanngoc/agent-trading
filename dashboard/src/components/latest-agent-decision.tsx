"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { Bot, ChevronRight } from "lucide-react"
import { api } from "@/lib/api-client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { decisionClass } from "@/lib/format"

export function LatestAgentDecision() {
  const { data, isLoading } = useQuery({
    queryKey: ["agent", "runs"],
    queryFn: api.agentRuns,
    refetchInterval: 90_000,
  })

  const latest = data?.runs?.[0]

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="size-4" />
          Quyết định mới nhất từ Agent
        </CardTitle>
        <Button
          variant="ghost"
          size="sm"
          className="text-xs"
          nativeButton={false}
          render={<Link href="/agent" />}
        >
          Xem tất cả <ChevronRight className="size-3" />
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : !latest ? (
          <p className="text-sm text-muted-foreground">
            Chưa có run nào. Mở tab <strong>Trade Agent</strong> để chạy phân tích.
          </p>
        ) : (
          <Link
            href={`/agent/${encodeURIComponent(latest.ticker)}/${latest.date}`}
            className="block rounded-lg border p-3 transition-colors hover:bg-accent/50"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-base font-semibold">{latest.ticker}</span>
                  <span className="text-xs text-muted-foreground tabular">{latest.date}</span>
                </div>
                {latest.rating && (
                  <div className="mt-0.5 text-xs text-muted-foreground">Rating: {latest.rating}</div>
                )}
              </div>
              <Badge variant="outline" className={`text-xs ${decisionClass(latest.decision)}`}>
                {latest.decision}
              </Badge>
            </div>
            {latest.final_trade_decision && (
              <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                {latest.final_trade_decision.slice(0, 240)}…
              </p>
            )}
          </Link>
        )}
      </CardContent>
    </Card>
  )
}

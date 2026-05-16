"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo } from "react"
import { ChevronRight, Loader2, AlertCircle, CheckCircle2 } from "lucide-react"
import { api } from "@/lib/api-client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EquityCurvesChart } from "@/components/benchmark/EquityCurvesChart"
import { ScorecardTable } from "@/components/benchmark/ScorecardTable"

/** /benchmark — Overview of the daily benchmark pipeline.
 *
 *  Top section: cron health pill + "run in flight?" indicator.
 *  Middle: equity curves chart + scorecard table for the latest run.
 *  Bottom: list of recent runs (click → /benchmark/[date]).
 *
 *  All data is fetched via React Query so navigating away and back is
 *  cached. The overview polls `/api/benchmark/runs` every 30s so a fresh
 *  cron run is visible within that window without manual refresh.
 */
export default function BenchmarkOverviewPage() {
  const runsQuery = useQuery({
    queryKey: ["benchmark", "runs"],
    queryFn: api.benchmarkRuns,
    refetchInterval: 30_000,
  })
  const runs = runsQuery.data?.runs ?? []
  const lock = runsQuery.data?.lock

  const latestDate = runs.length > 0 ? runs[0].date : null

  const latestQuery = useQuery({
    queryKey: ["benchmark", "run", latestDate],
    queryFn: () => api.benchmarkRun(latestDate!),
    enabled: !!latestDate,
    refetchInterval: 60_000,
  })
  const latest = latestQuery.data

  const cronQuery = useQuery({
    queryKey: ["benchmark", "cron-log", 50],
    queryFn: () => api.benchmarkCronLog(50),
    refetchInterval: 60_000,
  })

  const lastCronTimestamp = useMemo(() => {
    const lines = cronQuery.data?.lines ?? []
    // Each cron invocation writes "=== <iso> start ===" / "=== <iso> end ===" markers.
    for (let i = lines.length - 1; i >= 0; i--) {
      const m = lines[i].match(/===\s*(\d{4}-\d{2}-\d{2}T[\d:]+Z)\s*(start|end)/)
      if (m) return { timestamp: m[1], state: m[2] }
    }
    return null
  }, [cronQuery.data])

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6 space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Benchmark Pipeline</h1>
          <p className="text-sm text-muted-foreground max-w-2xl">
            Đánh giá hiệu quả TradingAgents trên VN equities song song với baselines (Buy &amp; Hold, SMA, Random).
            Daily cron sinh ra scorecard mới mỗi phiên giao dịch — alpha thực sự cần ≥30 phiên để kết luận.
          </p>
        </div>
        <RunStatusPill lock={lock} cron={lastCronTimestamp} />
      </header>

      {/* Latest run preview */}
      {latestQuery.isLoading ? (
        <Skeleton className="h-[320px]" />
      ) : latest ? (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <EquityCurvesChart csv={latest.equityCurves} />
          </div>
          <div>
            <Card className="h-full">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Run gần nhất</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div>
                  <div className="text-xs text-muted-foreground uppercase">Ngày</div>
                  <div className="font-medium tabular-nums">{latest.date}</div>
                </div>
                {latest.scorecard && (
                  <>
                    <div>
                      <div className="text-xs text-muted-foreground uppercase">Window</div>
                      <div className="tabular-nums">
                        {latest.scorecard.window.start} → {latest.scorecard.window.end}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {latest.scorecard.window.n_trading_days} phiên · benchmark {latest.scorecard.benchmark}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-muted-foreground uppercase">Vốn ban đầu</div>
                      <div className="tabular-nums">
                        {(latest.scorecard.initial_capital_vnd / 1_000_000_000).toFixed(1)}B VND/strategy
                      </div>
                    </div>
                  </>
                )}
                <div>
                  <div className="text-xs text-muted-foreground uppercase">Agent logs</div>
                  <div className="text-xs">{latest.agentLogs.length} ticker</div>
                </div>
                <Link
                  href={`/benchmark/${latest.date}`}
                  className="inline-flex items-center gap-1 text-xs underline text-[color:var(--chart-2)]"
                >
                  Xem chi tiết <ChevronRight className="size-3" />
                </Link>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <EmptyState />
      )}

      {latest?.scorecard && <ScorecardTable scorecard={latest.scorecard} />}

      {/* Recent runs */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Lịch sử run ({runs.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {runsQuery.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}
            </div>
          ) : runs.length === 0 ? (
            <EmptyState />
          ) : (
            <ul className="divide-y">
              {runs.map((r) => (
                <li key={r.date}>
                  <Link
                    href={`/benchmark/${r.date}`}
                    className="flex items-center justify-between py-3 px-2 -mx-2 rounded hover:bg-accent/40 transition-colors"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div>
                        <div className="font-medium tabular-nums">{r.date}</div>
                        <div className="text-xs text-muted-foreground">
                          {r.strategies?.length ? `${r.strategies.length} strategies · ` : ""}
                          {r.agentLogs.length} agent log{r.agentLogs.length === 1 ? "" : "s"}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0 text-xs">
                      {r.hasBrief && <Badge variant="outline" className="text-[10px]">brief</Badge>}
                      {r.hasScorecard && <Badge variant="outline" className="text-[10px]">scorecard</Badge>}
                      {r.hasReport && <Badge variant="outline" className="text-[10px]">report</Badge>}
                      <ChevronRight className="size-4 text-muted-foreground" />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Cron log preview */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Cron log (50 dòng gần nhất)</CardTitle>
        </CardHeader>
        <CardContent>
          {cronQuery.isLoading ? (
            <Skeleton className="h-32" />
          ) : (cronQuery.data?.lines.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground italic">
              Chưa có _cron.log. Chạy <code className="text-xs">scripts/benchmark/install_cron.sh</code> để cài cron.
            </p>
          ) : (
            <pre className="text-xs font-mono leading-relaxed text-muted-foreground max-h-64 overflow-y-auto whitespace-pre-wrap">
              {(cronQuery.data?.lines ?? []).join("\n")}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function RunStatusPill({
  lock,
  cron,
}: {
  lock?: { running: boolean; pid?: number; startedAt?: string }
  cron: { timestamp: string; state: string } | null
}) {
  if (lock?.running) {
    return (
      <Badge variant="outline" className="gap-1.5 text-xs">
        <Loader2 className="size-3 animate-spin" />
        <span>Run đang chạy</span>
        {lock.startedAt && (
          <span className="text-muted-foreground">từ {lock.startedAt.slice(0, 19)}</span>
        )}
      </Badge>
    )
  }
  if (cron) {
    const Icon = cron.state === "end" ? CheckCircle2 : Loader2
    return (
      <Badge variant="outline" className="gap-1.5 text-xs">
        <Icon className={cn("size-3", cron.state === "end" ? "" : "animate-spin")} />
        Cron last {cron.state} · {cron.timestamp.slice(0, 19).replace("T", " ")}
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="gap-1.5 text-xs text-muted-foreground">
      <AlertCircle className="size-3" /> Chưa có cron run
    </Badge>
  )
}

function cn(...args: (string | false | null | undefined)[]) {
  return args.filter(Boolean).join(" ")
}

function EmptyState() {
  return (
    <p className="text-sm text-muted-foreground">
      Chưa có run nào. Chạy thủ công:{" "}
      <code className="text-xs">venv/bin/python -m scripts.benchmark.run_daily</code>
    </p>
  )
}

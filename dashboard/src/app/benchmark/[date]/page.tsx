"use client"

import { use, useState } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, Terminal } from "lucide-react"
import { api } from "@/lib/api-client"
import type { ExecutionRow, StrategyDecisionDump } from "@/lib/api-client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { MarkdownReport } from "@/components/markdown-report"
import { EquityCurvesChart } from "@/components/benchmark/EquityCurvesChart"
import { ScorecardTable } from "@/components/benchmark/ScorecardTable"
import { AgentLogStream } from "@/components/benchmark/AgentLogStream"
import { cn } from "@/lib/utils"

/** /benchmark/[date] — Detail view for one daily run.
 *
 *  Layout:
 *   1. Header with date + back link
 *   2. Daily brief (markdown — the "what does today say" overview)
 *   3. Equity curves chart for the same window
 *   4. Scorecard table
 *   5. Tabs:
 *      - "Agent logs": one per ticker, live-streams if log is still growing
 *      - "Execution": per-strategy fill / status table
 *      - "Decisions": per-strategy decision list with rationale
 *   6. Optional report.md (full backtest report) at the bottom for the
 *      curious. Collapsed by default.
 */
export default function BenchmarkRunDetail({
  params,
}: {
  params: Promise<{ date: string }>
}) {
  const { date } = use(params)
  const { data, isLoading, error } = useQuery({
    queryKey: ["benchmark", "run", date],
    queryFn: () => api.benchmarkRun(date),
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <div className="container mx-auto max-w-6xl px-4 py-6 space-y-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-[200px]" />
        <Skeleton className="h-[320px]" />
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="container mx-auto max-w-6xl px-4 py-6">
        <p className="text-sm text-red-600 dark:text-red-400">
          {error instanceof Error ? error.message : "Run not found"}
        </p>
        <Link href="/benchmark" className="text-sm underline">← Back</Link>
      </div>
    )
  }

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6 space-y-6">
      <div>
        <Link
          href="/benchmark"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Quay lại Benchmark
        </Link>
        <div className="mt-2 flex flex-wrap items-baseline gap-3">
          <h1 className="text-2xl font-bold tracking-tight tabular-nums">{date}</h1>
          {data.scorecard && (
            <span className="text-sm text-muted-foreground">
              {data.scorecard.window.start} → {data.scorecard.window.end} ·
              {" "}{data.scorecard.strategies.length} strategies
            </span>
          )}
          {data.agentLogs.length > 0 && (
            <Badge variant="outline" className="text-xs">
              {data.agentLogs.length} agent log{data.agentLogs.length === 1 ? "" : "s"}
            </Badge>
          )}
        </div>
      </div>

      {/* Daily brief */}
      {data.brief && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Daily Brief</CardTitle>
          </CardHeader>
          <CardContent>
            <MarkdownReport content={data.brief} />
          </CardContent>
        </Card>
      )}

      {/* Equity curves */}
      <EquityCurvesChart csv={data.equityCurves} />

      {/* Scorecard */}
      <ScorecardTable scorecard={data.scorecard} />

      {/* Tabs: agent logs / execution / decisions */}
      <DetailTabs
        date={date}
        agentLogs={data.agentLogs}
        decisions={data.decisions}
      />

      {/* Full report — collapsed under a details element */}
      {data.report && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Full backtest report (raw)</CardTitle>
          </CardHeader>
          <CardContent>
            <details>
              <summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
                Expand report.md
              </summary>
              <div className="mt-3">
                <MarkdownReport content={data.report} />
              </div>
            </details>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ── Detail tabs ─────────────────────────────────────────────────────────

function DetailTabs({
  date,
  agentLogs,
  decisions,
}: {
  date: string
  agentLogs: string[]
  decisions: Record<string, StrategyDecisionDump | null>
}) {
  const strategyIds = Object.keys(decisions).sort()
  const [activeTab, setActiveTab] = useState<"logs" | "execution" | "decisions">("logs")
  const [activeTicker, setActiveTicker] = useState<string>(agentLogs[0] ?? "")
  const [activeStrategy, setActiveStrategy] = useState<string>(strategyIds[0] ?? "")

  return (
    <Card>
      <CardContent className="p-3">
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          <TabsList className="grid w-full max-w-md grid-cols-3">
            <TabsTrigger value="logs">
              <Terminal className="mr-1.5 size-3.5" /> Agent logs
            </TabsTrigger>
            <TabsTrigger value="execution">Execution</TabsTrigger>
            <TabsTrigger value="decisions">Decisions</TabsTrigger>
          </TabsList>

          {/* Agent logs — one per ticker, live SSE tail */}
          <TabsContent value="logs" className="space-y-3 pt-3">
            {agentLogs.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">
                Chưa có _agent_logs/ — run sẽ ghi vào đây khi cron fire main.py.
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {agentLogs.map((t) => (
                    <button
                      key={t}
                      onClick={() => setActiveTicker(t)}
                      className={cn(
                        "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                        activeTicker === t
                          ? "bg-accent text-foreground"
                          : "text-muted-foreground hover:bg-accent/40",
                      )}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                {activeTicker && (
                  <AgentLogStream date={date} ticker={activeTicker} key={activeTicker} />
                )}
              </>
            )}
          </TabsContent>

          {/* Execution log — sortable-ish table per strategy */}
          <TabsContent value="execution" className="space-y-3 pt-3">
            <StrategyPicker
              strategies={strategyIds}
              active={activeStrategy}
              onChange={setActiveStrategy}
            />
            <ExecutionTable rows={decisions[activeStrategy]?.execution_log ?? []} />
          </TabsContent>

          {/* Decision list */}
          <TabsContent value="decisions" className="space-y-3 pt-3">
            <StrategyPicker
              strategies={strategyIds}
              active={activeStrategy}
              onChange={setActiveStrategy}
            />
            <DecisionList dump={decisions[activeStrategy]} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function StrategyPicker({
  strategies,
  active,
  onChange,
}: {
  strategies: string[]
  active: string
  onChange: (s: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {strategies.map((s) => (
        <button
          key={s}
          onClick={() => onChange(s)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
            active === s
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:bg-accent/40",
          )}
        >
          {s}
        </button>
      ))}
    </div>
  )
}

function ExecutionTable({ rows }: { rows: ExecutionRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground italic">— Không có execution row —</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular-nums">
        <thead>
          <tr className="border-b text-[10px] uppercase tracking-wide text-muted-foreground">
            <th className="py-2 text-left">Decision</th>
            <th className="py-2 text-left">Ticker</th>
            <th className="py-2 text-left">Action</th>
            <th className="py-2 text-left">Fill</th>
            <th className="py-2 text-left">Status</th>
            <th className="py-2 text-right">Qty</th>
            <th className="py-2 text-right">Price</th>
            <th className="py-2 text-right">Realized P&amp;L</th>
            <th className="py-2 text-left">Note</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-2">{r.decision_date}</td>
              <td className="py-2 font-medium">{r.ticker}</td>
              <td className={cn("py-2", actionColor(r.action))}>{r.action}</td>
              <td className="py-2 text-muted-foreground">{r.fill_date ?? "—"}</td>
              <td className={cn("py-2", statusColor(r.status))}>{r.status}</td>
              <td className="py-2 text-right">{r.quantity > 0 ? r.quantity.toLocaleString() : "—"}</td>
              <td className="py-2 text-right">
                {r.fill_price > 0 ? r.fill_price.toLocaleString() : "—"}
              </td>
              <td className={cn("py-2 text-right", pnlColor(r.realized_pnl_vnd))}>
                {r.realized_pnl_vnd !== 0 ? r.realized_pnl_vnd.toLocaleString() : "—"}
              </td>
              <td className="py-2 text-muted-foreground max-w-[280px] truncate">{r.note ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DecisionList({ dump }: { dump: StrategyDecisionDump | null | undefined }) {
  if (!dump) return <p className="text-sm text-muted-foreground italic">— No decisions —</p>
  if (dump.decisions.length === 0) {
    return <p className="text-sm text-muted-foreground italic">— Chưa có decision —</p>
  }
  return (
    <ul className="divide-y">
      {dump.decisions.map((d, i) => (
        <li key={i} className="py-2.5 flex items-start gap-3 text-xs">
          <Badge variant="outline" className={cn("text-[10px]", actionColor(d.action))}>
            {d.action}
          </Badge>
          <span className="font-medium">{d.ticker}</span>
          <span className="text-muted-foreground">{d.decision_date}</span>
          {d.rationale && (
            <span className="text-muted-foreground line-clamp-2 max-w-2xl">
              {d.rationale.replace(/[#*\n]+/g, " ").slice(0, 220)}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

function actionColor(action: string): string {
  if (action === "BUY") return "text-emerald-600 dark:text-emerald-400"
  if (action === "SELL") return "text-red-600 dark:text-red-400"
  return "text-amber-600 dark:text-amber-400"
}

function statusColor(status: string): string {
  if (status === "filled") return "text-emerald-600 dark:text-emerald-400"
  if (status.startsWith("skipped") || status === "no_price") return "text-muted-foreground"
  if (status === "noop_hold") return "text-amber-600 dark:text-amber-400"
  return ""
}

function pnlColor(pnl: number): string {
  if (pnl > 0) return "text-emerald-600 dark:text-emerald-400"
  if (pnl < 0) return "text-red-600 dark:text-red-400"
  return "text-muted-foreground"
}

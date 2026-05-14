"use client"

import { use } from "react"
import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { MarkdownReport } from "@/components/markdown-report"
import { NewsList } from "@/components/news-list"
import { decisionClass } from "@/lib/format"

type Props = { params: Promise<{ ticker: string; date: string }> }

type AgentRun = {
  ticker: string
  date: string
  decision: string
  rating?: string
  final_trade_decision?: string
  investment_plan?: string
  trader_investment_plan?: string
  market_report?: string
  sentiment_report?: string
  news_report?: string
  fundamentals_report?: string
  error?: string
}

const TABS = [
  { value: "market",       label: "Phân tích kỹ thuật", key: "market_report" },
  { value: "news",         label: "Tin tức",            key: "news_report" },
  { value: "sentiment",    label: "Cảm xúc thị trường", key: "sentiment_report" },
  { value: "fundamentals", label: "Cơ bản",             key: "fundamentals_report" },
  { value: "plan",         label: "Kế hoạch đầu tư",    key: "investment_plan" },
  { value: "trader",       label: "Kế hoạch giao dịch", key: "trader_investment_plan" },
] as const

const DECISION_VN: Record<string, string> = {
  BUY: "MUA", SELL: "BÁN", HOLD: "GIỮ",
}

export default function AgentRunPage({ params }: Props) {
  const { ticker, date } = use(params)
  const decodedTicker = decodeURIComponent(ticker)

  const { data: run, isLoading } = useQuery<AgentRun>({
    queryKey: ["agent", "run", decodedTicker, date],
    queryFn: () => fetch(`/api/agent/runs/${encodeURIComponent(decodedTicker)}/${date}`).then((r) => r.json()),
  })

  if (isLoading) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-6 space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }
  if (!run || run.error) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-6">
        <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/agent" />}>
          <ArrowLeft className="size-4" /> Quay lại
        </Button>
        <p className="mt-4 text-sm text-muted-foreground">
          Không tìm thấy run cho {decodedTicker} ngày {date}.
        </p>
      </div>
    )
  }

  const decisionLabel = DECISION_VN[run.decision] ?? run.decision

  return (
    <div className="container mx-auto max-w-5xl px-4 py-6 space-y-4">
      <Button variant="ghost" size="sm" nativeButton={false} render={<Link href="/agent" />}>
        <ArrowLeft className="size-4" /> Quay lại
      </Button>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {decodedTicker} <span className="text-base font-normal text-muted-foreground tabular">{date}</span>
          </h1>
          {run.rating && (
            <p className="mt-1 text-sm text-muted-foreground">
              Xếp hạng: <strong>{run.rating}</strong>
            </p>
          )}
        </div>
        <Badge variant="outline" className={`text-sm ${decisionClass(run.decision)}`}>
          {decisionLabel}
        </Badge>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Quyết định giao dịch cuối cùng</CardTitle>
        </CardHeader>
        <CardContent>
          <MarkdownReport content={run.final_trade_decision ?? ""} />
        </CardContent>
      </Card>

      <Tabs defaultValue="news">
        <TabsList className="flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
          ))}
        </TabsList>

        {TABS.map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-3 space-y-4">
            {/* News tab gets an extra "Tin tức nguồn" panel above the LLM's
                synthesized news report so the user can cross-check the
                agent's analysis against the raw articles. */}
            {t.value === "news" && <NewsList ticker={decodedTicker} />}

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{t.label}</CardTitle>
              </CardHeader>
              <CardContent>
                <MarkdownReport content={(run[t.key as keyof AgentRun] as string) ?? ""} />
              </CardContent>
            </Card>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}

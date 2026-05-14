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
import { decisionClass } from "@/lib/format"

type Props = { params: Promise<{ ticker: string; date: string }> }

export default function AgentRunPage({ params }: Props) {
  const { ticker, date } = use(params)
  const decodedTicker = decodeURIComponent(ticker)

  const { data: run, isLoading } = useQuery({
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
              Rating: <strong>{run.rating}</strong>
            </p>
          )}
        </div>
        <Badge variant="outline" className={`text-sm ${decisionClass(run.decision)}`}>
          {run.decision}
        </Badge>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Final Trade Decision</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
            {run.final_trade_decision ?? "—"}
          </pre>
        </CardContent>
      </Card>

      <Tabs defaultValue="market">
        <TabsList className="flex-wrap">
          <TabsTrigger value="market">Market</TabsTrigger>
          <TabsTrigger value="news">News</TabsTrigger>
          <TabsTrigger value="sentiment">Sentiment</TabsTrigger>
          <TabsTrigger value="fundamentals">Fundamentals</TabsTrigger>
          <TabsTrigger value="plan">Investment Plan</TabsTrigger>
          <TabsTrigger value="trader">Trader Plan</TabsTrigger>
        </TabsList>
        {[
          ["market", "market_report"],
          ["news", "news_report"],
          ["sentiment", "sentiment_report"],
          ["fundamentals", "fundamentals_report"],
          ["plan", "investment_plan"],
          ["trader", "trader_investment_plan"],
        ].map(([tab, key]) => (
          <TabsContent key={tab} value={tab} className="mt-3">
            <Card>
              <CardContent className="p-4">
                <pre className="whitespace-pre-wrap text-sm leading-relaxed font-sans">
                  {(run[key as keyof typeof run] as string) || "—"}
                </pre>
              </CardContent>
            </Card>
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}

"use client"

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ExternalLink, Loader2, Newspaper, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type NewsItem = {
  title: string
  url: string
  source: string
  publishedAt: string | null
  sentimentScore: number | null
  sentimentLabel: string | null
  relevance: number | null
}

type Response = {
  items: NewsItem[]
  sentiment?: {
    avg_score: number
    label: string
    bullish: number
    bearish: number
    neutral: number
    article_count: number
  }
  staleWarning?: { latestPublishedAt: string; daysOld: number }
  source?: "tickers-filter" | "fts-alias" | "empty"
  error?: string
  hint?: string
}

const SENTIMENT_CLASS: Record<string, string> = {
  bullish:  "text-[color:var(--bullish)] border-[color:var(--bullish)]/30",
  positive: "text-[color:var(--bullish)] border-[color:var(--bullish)]/30",
  bearish:  "text-[color:var(--bearish)] border-[color:var(--bearish)]/30",
  negative: "text-[color:var(--bearish)] border-[color:var(--bearish)]/30",
  neutral:  "text-[color:var(--neutral)] border-[color:var(--neutral)]/30",
  somewhat_bullish: "text-[color:var(--bullish)] border-[color:var(--bullish)]/30",
  somewhat_bearish: "text-[color:var(--bearish)] border-[color:var(--bearish)]/30",
}

const SOURCE_LABEL: Record<string, string> = {
  "tickers-filter": "ticker filter",
  "fts-alias": "FTS (Vingroup/VIC)",
  "empty": "không có dữ liệu",
}

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 10)
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })
}

export function NewsList({
  ticker,
  date,
  daysBack = 30,
  limit = 30,
}: {
  ticker: string
  date?: string
  daysBack?: number
  limit?: number
}) {
  const qc = useQueryClient()
  const [crawlRunning, setCrawlRunning] = useState(false)

  const queryUrl = (() => {
    const u = new URLSearchParams({ limit: String(limit), days_back: String(daysBack) })
    if (date) u.set("date", date)
    return `/api/news/list/${encodeURIComponent(ticker)}?${u.toString()}`
  })()

  const { data, isLoading, refetch, isFetching } = useQuery<Response>({
    queryKey: ["news", "list", ticker, date, daysBack, limit],
    queryFn: () => fetch(queryUrl).then((r) => r.json()),
  })

  // Trigger trend_news in-process scheduler for ad-hoc crawl.
  const crawl = useMutation({
    mutationFn: () =>
      fetch("/api/news/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job: "crawl" }),
      }).then((r) => r.json()),
    onSuccess: (res) => {
      if (!res.ok) {
        toast.error("Không trigger được crawl", { description: res.error ?? res.detail })
        return
      }
      toast.success("Đã trigger crawl — chạy nền ~30s", {
        description: "Khi xong, danh sách tin sẽ tự refresh.",
      })
      setCrawlRunning(true)
      // Poll for completion via scheduler status, then refetch news.
      let attempts = 0
      const id = setInterval(async () => {
        attempts += 1
        try {
          const s = await fetch("/api/news/crawl").then((r) => r.json())
          const crawlJob = (s.jobs || []).find((j: { name: string }) => j.name === "crawl")
          if (!crawlJob?.currently_running) {
            clearInterval(id)
            setCrawlRunning(false)
            qc.invalidateQueries({ queryKey: ["news", "list"] })
            const result = crawlJob?.last_result ?? {}
            const newArticles = result.new_articles ?? result.added ?? "?"
            toast.success(`Crawl xong (${newArticles} bài mới)`)
          }
        } catch { /* keep polling */ }
        if (attempts > 60) {  // 5 phút trần
          clearInterval(id)
          setCrawlRunning(false)
          qc.invalidateQueries({ queryKey: ["news", "list"] })
        }
      }, 5_000)
    },
    onError: (e) => toast.error("Lỗi trigger crawl", { description: String(e) }),
  })

  const items = data?.items ?? []
  const senti = data?.sentiment

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <Newspaper className="size-4" />
            Tin tức nguồn ({ticker})
          </span>
          <div className="flex items-center gap-1.5">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => refetch()}
              disabled={isFetching}
              className="text-xs"
            >
              {isFetching ? <Loader2 className="size-3 animate-spin" /> : <RefreshCw className="size-3" />}
              Refresh
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => crawl.mutate()}
              disabled={crawl.isPending || crawlRunning}
              className="text-xs"
            >
              {crawl.isPending || crawlRunning ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <RefreshCw className="size-3" />
              )}
              {crawlRunning ? "Đang crawl…" : "Cập nhật tin"}
            </Button>
          </div>
        </CardTitle>
        {senti && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground pt-1">
            <span>
              <strong>{senti.article_count}</strong> bài · trung bình{" "}
              <span className="tabular font-medium text-foreground">
                {senti.avg_score >= 0 ? "+" : ""}
                {senti.avg_score.toFixed(2)}
              </span>{" "}
              ({senti.label})
            </span>
            <span className="flex items-center gap-1">
              <span className="size-1.5 rounded-full bg-[color:var(--bullish)]" />
              {senti.bullish}
              <span className="text-muted-foreground/60 mx-1">·</span>
              <span className="size-1.5 rounded-full bg-[color:var(--neutral)]" />
              {senti.neutral}
              <span className="text-muted-foreground/60 mx-1">·</span>
              <span className="size-1.5 rounded-full bg-[color:var(--bearish)]" />
              {senti.bearish}
            </span>
            {data?.source && (
              <Badge variant="secondary" className="text-[10px] py-0">
                {SOURCE_LABEL[data.source] ?? data.source}
              </Badge>
            )}
          </div>
        )}
        {data?.staleWarning && (
          <div className="flex items-center gap-1.5 mt-1 text-xs text-[color:var(--bearish)]">
            <AlertTriangle className="size-3" />
            Dữ liệu cũ {data.staleWarning.daysOld} ngày so với ngày phân tích — bấm{" "}
            <strong>Cập nhật tin</strong> để crawl mới
          </div>
        )}
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12" />)}
          </div>
        ) : data?.error ? (
          <div className="text-sm text-muted-foreground">
            <p>Không lấy được tin tức ({data.error}).</p>
            {data.hint && <p className="mt-1 text-xs">{data.hint}</p>}
          </div>
        ) : items.length === 0 ? (
          <div className="text-sm text-muted-foreground italic">
            <p>Không có tin tức cho {ticker} trong {daysBack} ngày gần đây.</p>
            <p className="mt-1 not-italic text-xs">
              Bấm <strong>Cập nhật tin</strong> để chạy crawler trên trend_news.
            </p>
          </div>
        ) : (
          <ul className="divide-y">
            {items.map((item, i) => {
              const sent = item.sentimentLabel?.toLowerCase()
              const sentClass = sent ? SENTIMENT_CLASS[sent] : undefined
              return (
                <li key={`${item.url}-${i}`} className="py-2.5 first:pt-0 last:pb-0">
                  <a
                    href={item.url || "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group block"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium leading-snug group-hover:text-[color:var(--chart-2)]">
                          {item.title}
                        </p>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                          <span className="font-mono">{item.source}</span>
                          <span>·</span>
                          <span className="tabular">{formatDate(item.publishedAt)}</span>
                          {item.sentimentLabel && (
                            <Badge variant="outline" className={cn("text-[10px] py-0", sentClass)}>
                              {item.sentimentLabel}
                              {item.sentimentScore != null && (
                                <span className="ml-1 tabular">{item.sentimentScore.toFixed(2)}</span>
                              )}
                            </Badge>
                          )}
                          {item.relevance != null && item.relevance > 1 && (
                            <Badge variant="secondary" className="text-[10px] py-0">
                              relevance {item.relevance}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <ExternalLink className="size-3.5 mt-1 shrink-0 text-muted-foreground group-hover:text-foreground" />
                    </div>
                  </a>
                </li>
              )
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

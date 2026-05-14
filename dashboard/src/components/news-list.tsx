"use client"

import { useQuery } from "@tanstack/react-query"
import { ExternalLink, Newspaper } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
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

const SENTIMENT_CLASS: Record<string, string> = {
  bullish:  "text-[color:var(--bullish)] border-[color:var(--bullish)]/30",
  positive: "text-[color:var(--bullish)] border-[color:var(--bullish)]/30",
  bearish:  "text-[color:var(--bearish)] border-[color:var(--bearish)]/30",
  negative: "text-[color:var(--bearish)] border-[color:var(--bearish)]/30",
  neutral:  "text-[color:var(--neutral)] border-[color:var(--neutral)]/30",
}

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 10)
  return d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })
}

export function NewsList({ ticker, limit = 30 }: { ticker: string; limit?: number }) {
  const { data, isLoading } = useQuery<{ items: NewsItem[]; error?: string; hint?: string }>({
    queryKey: ["news", "list", ticker, limit],
    queryFn: () => fetch(`/api/news/list/${encodeURIComponent(ticker)}?limit=${limit}`).then((r) => r.json()),
  })

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          <span className="flex items-center gap-2">
            <Newspaper className="size-4" />
            Tin tức nguồn ({ticker})
          </span>
          {data?.items && (
            <span className="text-xs text-muted-foreground font-normal tabular">
              {data.items.length} bài
            </span>
          )}
        </CardTitle>
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
        ) : !data?.items || data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">
            Không có tin tức cho {ticker} trong khoảng thời gian này.
          </p>
        ) : (
          <ul className="divide-y">
            {data.items.map((item, i) => {
              const sent = item.sentimentLabel?.toLowerCase()
              const sentClass = sent ? SENTIMENT_CLASS[sent] : SENTIMENT_CLASS.neutral
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

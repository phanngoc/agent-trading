"use client"

import { useQuery } from "@tanstack/react-query"
import { api, type Quote } from "@/lib/api-client"
import { QuoteCard } from "@/components/quote-card"
import { Skeleton } from "@/components/ui/skeleton"

const CATEGORY_LABEL: Record<Quote["category"], string> = {
  vn: "Việt Nam",
  index: "Chỉ số toàn cầu",
  commodity: "Hàng hóa & Vàng",
  crypto: "Crypto",
}

const CATEGORY_ORDER: Quote["category"][] = ["vn", "index", "commodity", "crypto"]

export function MarketsGrid({ filter }: { filter?: Quote["category"] }) {
  const { data, isLoading } = useQuery({
    queryKey: ["markets", "quotes"],
    queryFn: api.quotes,
    refetchInterval: 60_000,
  })

  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    )
  }

  const quotes = data?.quotes ?? []
  const filtered = filter ? quotes.filter((q) => q.category === filter) : quotes

  if (filter) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.map((q) => (
          <QuoteCard key={q.symbol} quote={q} />
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {CATEGORY_ORDER.map((cat) => {
        const inCat = quotes.filter((q) => q.category === cat)
        if (inCat.length === 0) return null
        return (
          <section key={cat}>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {CATEGORY_LABEL[cat]}
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {inCat.map((q) => (
                <QuoteCard key={q.symbol} quote={q} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

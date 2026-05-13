"use client"

import { ArrowDownRight, ArrowUpRight } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Sparkline } from "@/components/sparkline"
import { changeClass, formatPercent, formatPrice } from "@/lib/format"
import type { Quote } from "@/lib/api-client"

export function QuoteCard({ quote, compact = false }: { quote: Quote; compact?: boolean }) {
  const positive = (quote.changePercent ?? 0) >= 0
  const ArrowIcon = positive ? ArrowUpRight : ArrowDownRight
  return (
    <Card className="overflow-hidden">
      <CardContent className={compact ? "p-3" : "p-4"}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              {quote.symbol}
            </div>
            <div className="truncate text-sm font-medium">{quote.name}</div>
          </div>
          <div className={`flex items-center gap-0.5 text-xs ${changeClass(quote.changePercent)}`}>
            <ArrowIcon className="size-3.5" />
            {formatPercent(quote.changePercent)}
          </div>
        </div>
        <div className="mt-2 flex items-end justify-between gap-3">
          <div className="tabular text-xl font-semibold">{formatPrice(quote.price, quote.currency)}</div>
          <div className="w-24 shrink-0">
            <Sparkline data={quote.history ?? []} positive={positive} />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

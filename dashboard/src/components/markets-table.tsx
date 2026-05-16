"use client"

import { useRouter } from "next/navigation"
import { useState } from "react"
import { ArrowDownIcon, ArrowUpIcon, ArrowUpDown } from "lucide-react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Sparkline } from "@/components/sparkline"
import { cn } from "@/lib/utils"
import { changeClass, formatPercent, formatPrice } from "@/lib/format"
import type { Quote } from "@/lib/api-client"

type SortKey = "name" | "price" | "changePercent"

export function MarketsTable({ quotes }: { quotes: Quote[] }) {
  const router = useRouter()
  const [sortBy, setSortBy] = useState<SortKey>("changePercent")
  const [dir, setDir] = useState<1 | -1>(-1)

  const sorted = [...quotes].sort((a, b) => {
    if (sortBy === "name") return a.name.localeCompare(b.name) * dir
    const av = (a[sortBy] as number) ?? 0
    const bv = (b[sortBy] as number) ?? 0
    return (av - bv) * dir
  })

  const toggle = (k: SortKey) => {
    if (sortBy === k) setDir((d) => (d === 1 ? -1 : 1))
    else { setSortBy(k); setDir(-1) }
  }

  const SortIcon = ({ k }: { k: SortKey }) =>
    sortBy !== k ? <ArrowUpDown className="size-3 inline ml-1 opacity-30" /> :
    dir === 1 ? <ArrowUpIcon className="size-3 inline ml-1" /> :
    <ArrowDownIcon className="size-3 inline ml-1" />

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="cursor-pointer select-none" onClick={() => toggle("name")}>
              Tên <SortIcon k="name" />
            </TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right cursor-pointer select-none" onClick={() => toggle("price")}>
              Giá <SortIcon k="price" />
            </TableHead>
            <TableHead className="text-right cursor-pointer select-none" onClick={() => toggle("changePercent")}>
              %Δ <SortIcon k="changePercent" />
            </TableHead>
            <TableHead className="w-32 text-right">30D</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((q) => {
            const positive = (q.changePercent ?? 0) >= 0
            return (
              <TableRow
                key={q.symbol}
                className="text-sm cursor-pointer hover:bg-accent/40 transition-colors"
                onClick={() => router.push(`/markets/${encodeURIComponent(q.symbol)}`)}
              >
                <TableCell className="font-medium">{q.name}</TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">{q.symbol}</TableCell>
                <TableCell className="text-right tabular">{formatPrice(q.price, q.currency)}</TableCell>
                <TableCell className={cn("text-right tabular", changeClass(q.changePercent))}>
                  {formatPercent(q.changePercent)}
                </TableCell>
                <TableCell>
                  <div className="ml-auto w-24">
                    <Sparkline data={q.history ?? []} positive={positive} height={24} />
                  </div>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

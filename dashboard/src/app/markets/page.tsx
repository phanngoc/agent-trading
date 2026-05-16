"use client"

import { useQuery } from "@tanstack/react-query"
import { api, type Quote } from "@/lib/api-client"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { MarketsTable } from "@/components/markets-table"

const TABS: { value: string; label: string; filter: (q: Quote) => boolean }[] = [
  { value: "all",       label: "Tất cả",       filter: () => true },
  { value: "vn",        label: "Việt Nam",     filter: (q) => q.category === "vn" },
  { value: "index",     label: "Chỉ số TG",    filter: (q) => q.category === "index" },
  { value: "commodity", label: "Hàng hóa/Vàng",filter: (q) => q.category === "commodity" },
  { value: "crypto",    label: "Crypto",       filter: (q) => q.category === "crypto" },
]

export default function MarketsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["markets", "quotes"],
    queryFn: api.quotes,
    refetchInterval: 60_000,
  })

  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Markets</h1>
        <p className="text-sm text-muted-foreground">
          Bảng tổng hợp giá real-time với 30-day sparkline. Click cột để sắp xếp.
        </p>
      </header>

      <Tabs defaultValue="all">
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {TABS.map((t) => (
          <TabsContent key={t.value} value={t.value} className="mt-4">
            {isLoading ? (
              <Skeleton className="h-80 w-full" />
            ) : (
              <MarketsTable quotes={(data?.quotes ?? []).filter(t.filter)} />
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}

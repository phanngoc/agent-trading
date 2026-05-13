"use client"

import { useQuery } from "@tanstack/react-query"
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useUIStore, type Timeframe } from "@/store/ui-store"
import { changeClass, formatPercent, formatPrice } from "@/lib/format"
import { api } from "@/lib/api-client"

const RANGE_FOR: Record<Timeframe, { range: string; interval: string }> = {
  "1D": { range: "1d", interval: "5m" },
  "1W": { range: "5d", interval: "15m" },
  "1M": { range: "1mo", interval: "1d" },
  "3M": { range: "3mo", interval: "1d" },
  "1Y": { range: "1y", interval: "1d" },
}

export function VnIndexChart() {
  const timeframe = useUIStore((s) => s.timeframe)
  const setTimeframe = useUIStore((s) => s.setTimeframe)

  const { data, isLoading } = useQuery({
    queryKey: ["vnindex", timeframe],
    queryFn: () => {
      const { range, interval } = RANGE_FOR[timeframe]
      return fetch(`/api/markets/vnindex?range=${range}&interval=${interval}`).then((r) => r.json())
    },
    refetchInterval: 60_000,
  })

  const positive = (data?.changePercent ?? 0) >= 0
  const color = positive ? "var(--bullish)" : "var(--bearish)"

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 pb-2">
        <div>
          <CardTitle className="text-base">VN-Index</CardTitle>
          {isLoading ? (
            <Skeleton className="mt-1 h-8 w-44" />
          ) : (
            <div className="mt-1 flex items-baseline gap-3">
              <span className="tabular text-3xl font-semibold">
                {formatPrice(data?.price, "VND")}
              </span>
              <span className={`tabular text-sm font-medium ${changeClass(data?.changePercent)}`}>
                {formatPercent(data?.changePercent)}
              </span>
            </div>
          )}
        </div>
        <Tabs
          value={timeframe}
          onValueChange={(v) => setTimeframe(v as Timeframe)}
          className="w-fit"
        >
          <TabsList>
            {(Object.keys(RANGE_FOR) as Timeframe[]).map((tf) => (
              <TabsTrigger key={tf} value={tf} className="px-2 text-xs">
                {tf}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </CardHeader>
      <CardContent>
        <div className="h-72">
          {isLoading || !data?.history ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <ResponsiveContainer>
              <AreaChart data={data.history} margin={{ top: 10, right: 8, left: 8, bottom: 0 }}>
                <defs>
                  <linearGradient id="vn-fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={color} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={color} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.4} />
                <XAxis
                  dataKey="t"
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  tickFormatter={(v) => {
                    const d = new Date(v)
                    return timeframe === "1D" || timeframe === "1W"
                      ? d.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })
                      : d.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit" })
                  }}
                  minTickGap={32}
                />
                <YAxis
                  domain={["auto", "auto"]}
                  tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                  tickFormatter={(v) => formatPrice(v, "VND")}
                  width={56}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--popover)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(v) => formatPrice(typeof v === "number" ? v : Number(v), "VND")}
                  labelFormatter={(v) =>
                    new Date(v as string).toLocaleString("vi-VN", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  }
                />
                <Area
                  type="monotone"
                  dataKey="c"
                  stroke={color}
                  strokeWidth={2}
                  fill="url(#vn-fill)"
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

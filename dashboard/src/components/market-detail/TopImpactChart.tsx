"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ImpactRow } from "@/lib/market-detail"

/** Top index contributors / detractors as a signed bar chart.
 *
 *  Sorted with the largest positive impact on the left, the largest
 *  negative on the right — matches Fireant's "Top cổ phiếu tác động"
 *  layout. The y-axis is the proxy "mức kéo / đẩy" score (pct change ×
 *  market cap in trillions ÷ 10); see fetch_market_detail.py for the
 *  caveat that this proxy uses raw market cap rather than the official
 *  free-float weight.
 */

export function TopImpactChart({ rows }: { rows: ImpactRow[] }) {
  const data = [...rows].sort((a, b) => b.impact_pts - a.impact_pts)

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Top cổ phiếu tác động</CardTitle>
        <p className="text-xs text-muted-foreground">
          Mức độ kéo / đẩy chỉ số (proxy: % biến động × vốn hóa)
        </p>
      </CardHeader>
      <CardContent>
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="symbol" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                formatter={(_, name, item) => {
                  const r = item.payload as ImpactRow
                  return [
                    `${r.impact_pts >= 0 ? "+" : ""}${r.impact_pts.toFixed(2)}`,
                    `${r.pct_change >= 0 ? "+" : ""}${r.pct_change.toFixed(2)}%`,
                  ]
                }}
                labelFormatter={(label) => `${label}`}
              />
              <Bar dataKey="impact_pts">
                {data.map((r, i) => (
                  <Cell key={i} fill={r.impact_pts >= 0 ? "#10b981" : "#ef4444"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

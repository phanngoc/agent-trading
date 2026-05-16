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

/** Flow distribution bar chart: turnover split across Tăng / Giảm / Kh.đổi.
 *
 *  Mirrors Fireant's "Phân bổ dòng tiền" with labels in tỷ (1 tỷ = 1B VND).
 */

const COLORS = ["#10b981", "#ef4444", "#f59e0b"] as const

export function FlowChart({
  upVnd,
  downVnd,
  flatVnd,
}: {
  upVnd: number
  downVnd: number
  flatVnd: number
}) {
  // Convert VND → tỷ for the y-axis (1 tỷ = 1e9 VND).
  const data = [
    { name: "Tăng", value: upVnd / 1e9 },
    { name: "Giảm", value: downVnd / 1e9 },
    { name: "Kh. đổi", value: flatVnd / 1e9 },
  ]

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Phân bổ dòng tiền</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 16, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v.toFixed(0)} tỷ`} />
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                formatter={(v) => `${Number(v).toFixed(1)} tỷ`}
              />
              <Bar dataKey="value">
                {data.map((_, i) => (
                  <Cell key={i} fill={COLORS[i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

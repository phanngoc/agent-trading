"use client"

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip, Legend } from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/** Advancers / Decliners / Unchanged pie chart.
 *
 *  Colors match the rest of the dashboard: emerald for advance, red for
 *  decline, amber for unchanged. The legend is the chart's "axis" — it
 *  also shows counts so a glance gives both ratio and absolute size.
 */

const COLORS = {
  up: "#10b981",
  down: "#ef4444",
  flat: "#f59e0b",
} as const

export function BreadthChart({
  advancers,
  decliners,
  unchanged,
}: {
  advancers: number
  decliners: number
  unchanged: number
}) {
  const data = [
    { name: `Tăng (${advancers})`, value: advancers, fill: COLORS.up },
    { name: `Giảm (${decliners})`, value: decliners, fill: COLORS.down },
    { name: `Không đổi (${unchanged})`, value: unchanged, fill: COLORS.flat },
  ]
  const total = advancers + decliners + unchanged

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Số lượng CP Tăng / Giảm / Không đổi</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={90}
                innerRadius={50}
                paddingAngle={2}
              >
                {data.map((d, i) => (
                  <Cell key={i} fill={d.fill} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 6,
                  fontSize: 12,
                }}
                formatter={(v) => `${v} (${((Number(v) / total) * 100).toFixed(1)}%)`}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}

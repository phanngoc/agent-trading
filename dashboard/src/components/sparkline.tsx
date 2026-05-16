"use client"

import { Line, LineChart, ResponsiveContainer } from "recharts"

export function Sparkline({
  data,
  positive,
  height = 36,
}: {
  data: { t: string; c: number }[]
  positive: boolean
  height?: number
}) {
  if (!data || data.length === 0) return null
  const color = positive ? "var(--bullish)" : "var(--bearish)"
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
        <Line
          type="monotone"
          dataKey="c"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

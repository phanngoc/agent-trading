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
  Treemap,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ForeignTickerRow, MarketDetail } from "@/lib/market-detail"

/** Combined "Khối ngoại" panel — top summary cards + per-ticker treemap.
 *
 *  Maps directly to Fireant's two "Giao dịch nhà đầu tư nước ngoài" cards.
 *  We split the layout so the summary numbers are always visible above
 *  the chart even on narrow screens.
 */

function fmtVnd(value: number, decimals = 1): string {
  if (value === 0) return "0"
  const abs = Math.abs(value)
  if (abs >= 1e12) return `${(value / 1e12).toFixed(decimals)} nghìn tỷ`
  if (abs >= 1e9) return `${(value / 1e9).toFixed(decimals)} tỷ`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(decimals)} triệu`
  return value.toLocaleString()
}

function fmtVol(value: number): string {
  return value.toLocaleString()
}

export function ForeignPanel({ data }: { data: MarketDetail }) {
  const f = data.foreign_today
  const netVolClass = f.net_volume >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"
  const netValClass = f.net_value_vnd >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Giao dịch nhà đầu tư nước ngoài</CardTitle>
        <p className="text-xs text-muted-foreground">Net mua/bán và phân bổ theo mã.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary cards row */}
        <div className="grid grid-cols-3 gap-3 text-sm tabular-nums">
          <div className="rounded-md border p-3">
            <div className="text-xs text-muted-foreground uppercase">Khối lượng</div>
            <div className="mt-1 grid grid-cols-3 gap-2">
              <div>
                <div className="text-[10px] text-muted-foreground">NN Mua</div>
                <div className="text-emerald-600 dark:text-emerald-400">{fmtVol(f.buy_volume)}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">NN Bán</div>
                <div className="text-red-600 dark:text-red-400">{fmtVol(f.sell_volume)}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">Mua − Bán</div>
                <div className={netVolClass}>{fmtVol(f.net_volume)}</div>
              </div>
            </div>
          </div>
          <div className="rounded-md border p-3">
            <div className="text-xs text-muted-foreground uppercase">Giá trị (VND)</div>
            <div className="mt-1 grid grid-cols-3 gap-2">
              <div>
                <div className="text-[10px] text-muted-foreground">NN Mua</div>
                <div className="text-emerald-600 dark:text-emerald-400">{fmtVnd(f.buy_value_vnd)}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">NN Bán</div>
                <div className="text-red-600 dark:text-red-400">{fmtVnd(f.sell_value_vnd)}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground">Mua − Bán</div>
                <div className={netValClass}>{fmtVnd(f.net_value_vnd)}</div>
              </div>
            </div>
          </div>
          <div className="rounded-md border p-3">
            <div className="text-xs text-muted-foreground uppercase">Tổng quan</div>
            <div className="mt-1 space-y-1.5">
              <div className="flex justify-between">
                <span className="text-[10px] text-muted-foreground">Mã thuần mua</span>
                <span className="text-emerald-600 dark:text-emerald-400">
                  {f.by_ticker.filter((t) => t.net_value_vnd > 0).length}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-[10px] text-muted-foreground">Mã thuần bán</span>
                <span className="text-red-600 dark:text-red-400">
                  {f.by_ticker.filter((t) => t.net_value_vnd < 0).length}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Per-ticker treemap */}
        <ForeignByTickerChart rows={f.by_ticker} />
      </CardContent>
    </Card>
  )
}

function ForeignByTickerChart({ rows }: { rows: ForeignTickerRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground italic">— Không có dữ liệu khối ngoại —</p>
  }
  // Use a bar chart for top 15 by abs(net) — easier to read than a treemap
  // when the longest bar is much bigger than the shortest. Sort ascending
  // by net value so the chart reads "biggest sell on left, biggest buy
  // on right" naturally.
  const top = [...rows].slice(0, 15).sort((a, b) => a.net_value_vnd - b.net_value_vnd)
  const data = top.map((r) => ({
    symbol: r.symbol,
    value: r.net_value_vnd / 1e9, // tỷ
  }))

  return (
    <div>
      <div className="text-xs text-muted-foreground mb-2">Top 15 mã NN mua / bán ròng (tỷ VND)</div>
      <div className="h-[260px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey="symbol" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v.toFixed(0)}`} />
            <Tooltip
              contentStyle={{
                background: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: 6,
                fontSize: 12,
              }}
              formatter={(v) => `${Number(v).toFixed(2)} tỷ`}
            />
            <Bar dataKey="value">
              {data.map((d, i) => (
                <Cell key={i} fill={d.value >= 0 ? "#10b981" : "#ef4444"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

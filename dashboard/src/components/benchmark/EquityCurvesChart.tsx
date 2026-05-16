"use client"

import { useMemo } from "react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

/** Render the per-strategy NAV time series from equity_curves.csv as
 *  overlapping line charts. The CSV's first column is the date index
 *  followed by one column per strategy plus the benchmark.
 *
 *  Normalization: NAV is shown as a percentage move from day-0 so all
 *  strategies share the same y-axis regardless of initial capital. The
 *  raw VND values stay in the tooltip for users who want the absolute
 *  number.
 */

type Row = { date: string } & Record<string, number | string>

function parseCsv(raw: string): { columns: string[]; rows: Row[] } {
  const lines = raw.trim().split(/\r?\n/).filter(Boolean)
  if (lines.length < 2) return { columns: [], rows: [] }

  const header = lines[0].split(",").map((s) => s.trim())
  // First column in the CSV is the pandas index (date). Skip it if it's empty.
  const dateColIndex = header.findIndex((c) => c.toLowerCase() === "" || c.toLowerCase() === "date")
  const strategyCols = header.filter((_, i) => i !== dateColIndex)

  const rows: Row[] = []
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split(",")
    const date = cells[dateColIndex >= 0 ? dateColIndex : 0]
    const row: Row = { date }
    strategyCols.forEach((col, idx) => {
      const cellIdx = idx >= dateColIndex ? idx + 1 : idx
      const val = cells[cellIdx]
      row[col] = val ? Number(val) : NaN
    })
    rows.push(row)
  }
  return { columns: strategyCols, rows }
}

function normalizeToPctMove(rows: Row[], cols: string[]): Row[] {
  // Use the first row's value per column as the baseline so each line
  // starts at 0% and diverges from there.
  if (rows.length === 0) return rows
  const baseline: Record<string, number> = {}
  for (const col of cols) {
    const v = rows[0][col]
    baseline[col] = typeof v === "number" && Number.isFinite(v) ? v : 1
  }
  return rows.map((r) => {
    const out: Row = { date: r.date }
    for (const col of cols) {
      const v = r[col]
      if (typeof v === "number" && Number.isFinite(v) && baseline[col]) {
        out[col] = ((v / baseline[col]) - 1) * 100
      } else {
        out[col] = NaN
      }
    }
    return out
  })
}

// Reach for the dashboard's chart palette so colors stay consistent with
// the rest of the site. We cap at 6 — anything beyond cycles through.
const PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "#888",
]

export function EquityCurvesChart({ csv }: { csv: string | null }) {
  const { columns, rows } = useMemo(() => {
    if (!csv) return { columns: [], rows: [] as Row[] }
    const parsed = parseCsv(csv)
    return { columns: parsed.columns, rows: normalizeToPctMove(parsed.rows, parsed.columns) }
  }, [csv])

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Equity curves (chuẩn hóa % từ day-0)</CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">
            — Chưa có equity_curves.csv —
          </p>
        ) : (
          <div className="h-[320px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(d) => String(d).slice(5)}
                  minTickGap={32}
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v) => `${v.toFixed(0)}%`}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  contentStyle={{
                    background: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  formatter={(v) => (typeof v === "number" ? `${v.toFixed(2)}%` : String(v ?? "—"))}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {columns.map((col, i) => (
                  <Line
                    key={col}
                    type="monotone"
                    dataKey={col}
                    stroke={PALETTE[i % PALETTE.length]}
                    strokeWidth={2}
                    dot={false}
                    name={col}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

"use client"

import type { RunScorecard, StrategyScorecard } from "@/lib/api-client"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"

/** Strategy comparison table with conditional formatting:
 *  - Total / Annualized / Alpha: green when positive, red when negative.
 *  - p-value: green when < 0.05 (statistically significant out-perf).
 *  - Sharpe: green when > 1, amber when 0-1, red when negative.
 *
 *  These colors are advisory — the metrics' full meaning lives in the
 *  interpretation guide at the bottom of the page. The goal here is to
 *  give the eye a fast scan of "who's winning" without reading numbers.
 */

function fmtPct(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—"
  return `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%`
}

function fmt(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—"
  return value.toFixed(decimals)
}

function pctClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ""
  if (value > 0) return "text-emerald-600 dark:text-emerald-400"
  if (value < 0) return "text-red-600 dark:text-red-400"
  return ""
}

function sharpeClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ""
  if (value >= 1) return "text-emerald-600 dark:text-emerald-400 font-medium"
  if (value <= 0) return "text-red-600 dark:text-red-400"
  return "text-amber-600 dark:text-amber-400"
}

function pvalueClass(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ""
  if (value < 0.05) return "text-emerald-600 dark:text-emerald-400 font-medium"
  if (value < 0.10) return "text-amber-600 dark:text-amber-400"
  return "text-muted-foreground"
}

export function ScorecardTable({ scorecard }: { scorecard: RunScorecard | null }) {
  if (!scorecard || !scorecard.strategies?.length) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Bảng điểm chiến lược</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground italic">— Chưa có scorecard.json —</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">
          Bảng điểm chiến lược
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {scorecard.window.start} → {scorecard.window.end} ({scorecard.window.n_trading_days} phiên · benchmark {scorecard.benchmark})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-2 text-left">Strategy</th>
              <th className="py-2 text-right">Total</th>
              <th className="py-2 text-right">Annualized</th>
              <th className="py-2 text-right">Sharpe</th>
              <th className="py-2 text-right">Max DD</th>
              <th className="py-2 text-right">Trades</th>
              <th className="py-2 text-right">Hit</th>
              <th className="py-2 text-right">α annual</th>
              <th className="py-2 text-right">β</th>
              <th className="py-2 text-right">p-value</th>
            </tr>
          </thead>
          <tbody>
            {scorecard.strategies.map((s: StrategyScorecard) => (
              <tr key={s.strategy_id} className="border-b last:border-0">
                <td className="py-2 font-medium">{s.strategy_id}</td>
                <td className={cn("py-2 text-right", pctClass(s.total_return_pct))}>
                  {fmtPct(s.total_return_pct)}
                </td>
                <td className={cn("py-2 text-right", pctClass(s.annualized_return_pct))}>
                  {fmtPct(s.annualized_return_pct)}
                </td>
                <td className={cn("py-2 text-right", sharpeClass(s.sharpe))}>{fmt(s.sharpe)}</td>
                <td className={cn("py-2 text-right", pctClass(s.max_drawdown_pct))}>
                  {fmtPct(s.max_drawdown_pct)}
                </td>
                <td className="py-2 text-right text-muted-foreground">{s.n_trades}</td>
                <td className="py-2 text-right text-muted-foreground">{fmt(s.hit_rate * 100, 0)}%</td>
                <td className={cn("py-2 text-right", pctClass(s.alpha_annualized_pct))}>
                  {fmtPct(s.alpha_annualized_pct)}
                </td>
                <td className="py-2 text-right text-muted-foreground">{fmt(s.beta ?? null)}</td>
                <td className={cn("py-2 text-right", pvalueClass(s.p_value))}>{fmt(s.p_value, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-4 text-xs text-muted-foreground">
          <strong>p-value</strong> &lt; 0.05 (xanh) ⇒ alpha có ý nghĩa thống kê.{" "}
          <strong>Sharpe</strong> ≥ 1 = tốt, ≥ 2 = rất hiếm. Cần ≥30 phiên để kết luận tin cậy.
        </p>
      </CardContent>
    </Card>
  )
}

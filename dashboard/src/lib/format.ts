/** Display helpers for prices, percent changes, and timestamps. */

export function formatPrice(value: number | null | undefined, currency = "USD"): string {
  if (value == null || !Number.isFinite(value)) return "—"
  if (currency === "VND") return new Intl.NumberFormat("vi-VN").format(Math.round(value))
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: value < 10 ? 2 : 2,
    maximumFractionDigits: value < 10 ? 4 : 2,
  }).format(value)
}

export function formatPercent(value: number | null | undefined, fractionDigits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(fractionDigits)}%`
}

export function changeClass(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value === 0) return "text-muted-foreground"
  return value > 0 ? "text-[color:var(--bullish)]" : "text-[color:var(--bearish)]"
}

export function decisionClass(decision: string | null | undefined): string {
  const d = (decision ?? "").toUpperCase()
  if (d.includes("BUY")) return "bg-[color:var(--bullish)]/15 text-[color:var(--bullish)] border-[color:var(--bullish)]/30"
  if (d.includes("SELL")) return "bg-[color:var(--bearish)]/15 text-[color:var(--bearish)] border-[color:var(--bearish)]/30"
  return "bg-[color:var(--neutral)]/15 text-[color:var(--neutral)] border-[color:var(--neutral)]/30"
}

import { NextResponse } from "next/server"
import { spawn } from "node:child_process"
import path from "node:path"

export const runtime = "nodejs"
export const revalidate = 60

const PY = process.env.TRADINGAGENTS_PYTHON
  || path.resolve(process.cwd(), "..", "venv", "bin", "python")

// Maps the dashboard's range/interval flags to the lookback window vnstock expects.
const RANGE_DAYS: Record<string, number> = {
  "1d":  5, "5d": 7, "1mo": 35, "3mo": 100, "6mo": 200, "1y": 380, "5y": 1900,
}
const VNSTOCK_INTERVAL: Record<string, string> = {
  "5m": "5m", "15m": "15m", "1h": "1H", "1d": "1D",
}

function fetchVnIndexFromPy(range: string, interval: string): Promise<{
  price: number | null
  change: number
  changePercent: number
  history: { t: string; c: number }[]
}> {
  const days = RANGE_DAYS[range] ?? 35
  const ivl = VNSTOCK_INTERVAL[interval] ?? "1D"
  return new Promise((resolve, reject) => {
    // vnai's promo banner still lands on stdout occasionally on the
    // first call of a fresh subprocess (the deprecated Vnstock() helper
    // banner is gone, but vnai is a separate library that prints its
    // own "INSIDERS PROGRAM" notice). Stdout here is reserved for the
    // JSON the Node caller will JSON.parse, so we redirect vnstock's
    // imports to stderr for the duration of the API call, then restore
    // stdout for the final json.dumps line.
    const child = spawn(PY, ["-c", `
import contextlib, json, sys
from datetime import datetime, timedelta

end = datetime.now().strftime("%Y-%m-%d")
start = (datetime.now() - timedelta(days=${days})).strftime("%Y-%m-%d")
out = {"price": None, "change": 0.0, "changePercent": 0.0, "history": []}
with contextlib.redirect_stdout(sys.stderr):
    from vnstock.api.quote import Quote
    quote = Quote(source="VCI", symbol="VNINDEX")
    h = quote.history(start=start, end=end, interval=${JSON.stringify(ivl)})

if h is not None and not h.empty:
    out["history"] = [
        {"t": str(t), "c": float(c)}
        for t, c in zip(h["time"].tolist(), h["close"].tolist())
        if c is not None and c == c
    ]
    closes = [p["c"] for p in out["history"]]
    if len(closes) >= 2:
        last, prev = closes[-1], closes[-2]
        out["price"] = last
        out["change"] = last - prev
        out["changePercent"] = (last - prev) / prev * 100 if prev else 0
    elif len(closes) == 1:
        out["price"] = closes[-1]
print(json.dumps(out))
`], { env: { ...process.env, PYTHONIOENCODING: "utf-8" } })
    let stdout = ""
    let stderr = ""
    child.stdout.on("data", (c) => (stdout += c))
    child.stderr.on("data", (c) => (stderr += c))
    child.on("error", reject)
    child.on("close", (code) => {
      if (code !== 0) return reject(new Error(`vnindex exit ${code}: ${stderr}`))
      try {
        resolve(JSON.parse(stdout))
      } catch (e) {
        reject(e)
      }
    })
  })
}

export async function GET(req: Request) {
  const url = new URL(req.url)
  const range = url.searchParams.get("range") ?? "1y"
  const interval = url.searchParams.get("interval") ?? "1d"
  try {
    const data = await fetchVnIndexFromPy(range, interval)
    return NextResponse.json({
      symbol: "^VNINDEX",
      name: "VN-Index",
      price: data.price,
      change: data.change,
      changePercent: data.changePercent,
      currency: "VND",
      category: "vn" as const,
      history: data.history,
    })
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 502 })
  }
}

"use client"

import { use } from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, TrendingUp, TrendingDown } from "lucide-react"
import { api } from "@/lib/api-client"
import { fetchMarketDetail, hasRichDetail, type MarketDetail } from "@/lib/market-detail"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BreadthChart } from "@/components/market-detail/BreadthChart"
import { FlowChart } from "@/components/market-detail/FlowChart"
import { TopImpactChart } from "@/components/market-detail/TopImpactChart"
import { ForeignPanel } from "@/components/market-detail/ForeignPanel"
import { Sparkline } from "@/components/sparkline"
import { cn } from "@/lib/utils"

/** /markets/[symbol] — exchange / instrument detail.
 *
 *  For VN indices (VNINDEX / HNX / UPCOM / VN30): renders the rich panel
 *  set — breadth pie, flow distribution, top contributors, foreign
 *  trading. For everything else (US indices, commodities, crypto) we
 *  still render the page so navigation always works, but only show the
 *  quote header + 30D sparkline since vnstock doesn't have those.
 */
export default function MarketDetailPage({
  params,
}: {
  params: Promise<{ symbol: string }>
}) {
  const { symbol } = use(params)
  const decoded = decodeURIComponent(symbol)
  const rich = hasRichDetail(decoded)

  // Always fetch the quotes list — we extract the matching row for the
  // header (price + sparkline). It's cached so repeated visits are cheap.
  const quotesQuery = useQuery({
    queryKey: ["markets", "quotes"],
    queryFn: api.quotes,
    refetchInterval: 60_000,
  })
  const quote = quotesQuery.data?.quotes.find(
    (q) => q.symbol.toUpperCase() === decoded.toUpperCase(),
  )

  // Only call the detail endpoint when we know it has data — otherwise
  // we'd burn a vnstock request on a non-VN symbol just to see "error".
  const detailQuery = useQuery({
    queryKey: ["market-detail", decoded],
    queryFn: () => fetchMarketDetail(decoded),
    enabled: rich,
    refetchInterval: 60_000,
  })
  const detail = detailQuery.data

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6 space-y-6">
      <Link
        href="/markets"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> Quay lại Markets
      </Link>

      <QuoteHeader symbol={decoded} quote={quote} asof={detail?.asof} />

      {!rich && (
        <Card>
          <CardContent className="p-6">
            <p className="text-sm text-muted-foreground">
              Chi tiết theo sàn (số CP tăng/giảm, dòng tiền, khối ngoại) chỉ có cho VN-Index / HNX-Index /
              UPCoM-Index / VN30. Symbol này hiển thị giá + sparkline 30 ngày.
            </p>
          </CardContent>
        </Card>
      )}

      {rich && detailQuery.isLoading && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-[300px]" />
          <Skeleton className="h-[300px]" />
        </div>
      )}

      {rich && detail?.error && (
        <Card>
          <CardContent className="p-6">
            <p className="text-sm text-red-600 dark:text-red-400">
              ⚠ Lỗi tải chi tiết: <code className="text-xs">{detail.error}</code>
            </p>
          </CardContent>
        </Card>
      )}

      {rich && detail && !detail.error && <DetailBlocks detail={detail} />}
    </div>
  )
}

function QuoteHeader({
  symbol,
  quote,
  asof,
}: {
  symbol: string
  quote?: { name: string; price: number; change: number; changePercent: number; currency: string; history?: { t: string; c: number }[] }
  asof?: string | null
}) {
  if (!quote) {
    return (
      <Card>
        <CardContent className="p-4">
          <Skeleton className="h-8 w-48" />
        </CardContent>
      </Card>
    )
  }
  const isUp = quote.changePercent >= 0
  return (
    <Card>
      <CardContent className="p-4 flex flex-wrap items-center justify-between gap-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">{quote.name}</h1>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <code className="text-xs">{symbol}</code>
            {asof && (
              <span className="text-[10px]">
                cập nhật: {asof.slice(0, 16).replace("T", " ")}
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold tabular-nums">
            {quote.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </div>
          <div
            className={cn(
              "flex items-center gap-1.5 justify-end text-sm tabular-nums",
              isUp ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
            )}
          >
            {isUp ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
            {isUp ? "+" : ""}{quote.change.toFixed(2)} ({isUp ? "+" : ""}{quote.changePercent.toFixed(2)}%)
          </div>
        </div>
        {quote.history && quote.history.length > 0 && (
          <div className="w-full sm:w-1/2 h-24">
            <Sparkline data={quote.history} positive={isUp} height={96} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function DetailBlocks({ detail }: { detail: MarketDetail }) {
  return (
    <>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <TrendingUp className="size-4 text-muted-foreground" />
            Biến động theo sàn
            {detail.exchange && (
              <span className="text-xs font-normal text-muted-foreground">
                · {detail.exchange} · {detail.constituents} mã
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground mb-4">
            So sánh đóng góp và nhịp chỉ số theo mã.
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            <BreadthChart
              advancers={detail.advancers}
              decliners={detail.decliners}
              unchanged={detail.unchanged}
            />
            <FlowChart
              upVnd={detail.flow.up_vnd}
              downVnd={detail.flow.down_vnd}
              flatVnd={detail.flow.flat_vnd}
            />
          </div>
        </CardContent>
      </Card>

      <TopImpactChart rows={detail.top_impact} />

      <ForeignPanel data={detail} />

      <Card>
        <CardContent className="p-4 text-xs text-muted-foreground">
          <strong>Lưu ý số liệu:</strong> Lấy từ vnstock <code>price_board</code> tại phiên gần nhất.
          Chỉ số "Tác động" là proxy (% biến động × vốn hóa raw), không phải index point chính thức —
          dùng để xếp hạng mã ảnh hưởng, không thay thế index attribution chính thức của HOSE/HNX.
        </CardContent>
      </Card>
    </>
  )
}

import { VnIndexChart } from "@/components/vnindex-chart"
import { LatestAgentDecision } from "@/components/latest-agent-decision"
import { MarketsGrid } from "@/components/markets-grid"

export default function VnIndexPage() {
  return (
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">VNINDEX</h1>
        <p className="text-sm text-muted-foreground">
          Trang chuyên sâu cho VN-Index: chart, các chỉ số phụ trợ, và quyết định mới nhất từ agent.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2"><VnIndexChart /></div>
        <div><LatestAgentDecision /></div>
      </div>

      <section>
        <h2 className="mb-3 text-lg font-semibold">VN markets</h2>
        <MarketsGrid filter="vn" />
      </section>
    </div>
  )
}

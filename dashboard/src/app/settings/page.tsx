import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function SettingsPage() {
  return (
    <div className="container mx-auto max-w-3xl px-4 py-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Cài đặt</h1>
        <p className="text-sm text-muted-foreground">Cấu hình dashboard + agent runs.</p>
      </header>

      <Card>
        <CardHeader><CardTitle className="text-base">Trade Agent</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            Trade agent dùng credentials Anthropic từ env / Claude Code OAuth keychain (xem
            <code className="mx-1 rounded bg-muted px-1.5 py-0.5 text-xs">tradingagents/llm_clients/anthropic_client.py</code>).
            Không có API key nào được lưu trong dashboard này.
          </p>
          <p>
            Để chạy hằng ngày, dùng cron / launchd với script
            <code className="mx-1 rounded bg-muted px-1.5 py-0.5 text-xs">scripts/run_daily.sh</code>.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Data sources</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          <p>• <strong>VN indices/equities</strong> → vnstock (VCI)</p>
          <p>• <strong>Global indices, vàng, dầu, crypto</strong> → yfinance</p>
          <p>• <strong>Polling</strong> mỗi 60s (server cache) + TanStack Query refetchInterval</p>
        </CardContent>
      </Card>
    </div>
  )
}

# TradingAgents Dashboard

Next.js 16 + React 19 + Tailwind 4 + shadcn/ui + Zustand + TanStack Query.
Theo dõi VNINDEX, chỉ số toàn cầu, vàng, dầu, crypto, và trade-agent daily runs.

## Quick start

```bash
cd dashboard
pnpm install
pnpm dev           # http://localhost:3000
```

Yêu cầu môi trường: Python venv của repo cha (`../venv`) đã cài `yfinance`
và `vnstock`. Dashboard gọi vào Python qua child_process — không có lib
market-data nào trong package.json.

### Scripts

| Command | Mô tả |
|---|---|
| `pnpm dev` | Dev server (Turbopack), port 3000 |
| `pnpm build` | Production build |
| `pnpm typecheck` | TypeScript strict check, không emit |
| `pnpm lint` | ESLint trên src/ |
| `pnpm smoke` | Bash smoke test: start dev → curl tất cả pages + API JSON probes |
| `pnpm run-daily` | Chạy watchlist VN qua `scripts/run_daily.sh` |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser                                                      │
│   ├─ Zustand     ui-store (timeframe, selectedTicker, theme) │
│   └─ TanStack Q  server cache (quotes, vnindex, agent runs)  │
└───────────────┬──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Next.js Route Handlers (Node runtime)                        │
│   /api/markets/quotes  ←  scripts/fetch_quotes.py             │
│   /api/markets/vnindex ←  inline python -c (vnstock)          │
│   /api/agent/runs      ←  fs.readdir(eval_results/)           │
│   /api/agent/trigger   →  spawn main.py (detached)            │
└───────────────┬──────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Python venv (repo root)                                      │
│   ├─ yfinance  → global indices, vàng, dầu, crypto            │
│   ├─ vnstock   → VNINDEX, HNX, UPCoM, VN equities             │
│   └─ main.py   → TradingAgentsGraph (anthropic OAuth)         │
└──────────────────────────────────────────────────────────────┘
```

## Pages

| Path              | Purpose |
|---|---|
| `/`               | Tổng quan — VNINDEX chart + latest agent decision + grouped markets grid |
| `/markets`        | Bảng đầy đủ với tabs (VN / Global / Commodity / Crypto), sort cột |
| `/vnindex`        | Chuyên sâu VN — chart + các index VN phụ |
| `/agent`          | Lịch sử run + nút trigger phân tích thủ công |
| `/agent/:t/:d`    | Chi tiết một run — final decision + reports breakdown |
| `/settings`       | Cấu hình + ghi chú vận hành |

## Daily run

Lên lịch chạy agent hằng ngày:

```bash
# Manual one-shot
TICKERS="VIC.VN HPG.VN MWG.VN VCB.VN" ./scripts/run_daily.sh

# macOS: launchd (weekdays at 19:00 sau khi VN market đóng)
cp scripts/com.tradingagents.dailyrun.plist.example \
   ~/Library/LaunchAgents/com.tradingagents.dailyrun.plist
# Edit the path inside, then:
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.tradingagents.dailyrun.plist

# Linux: cron
0 19 * * 1-5 /path/to/dashboard/scripts/run_daily.sh
```

Auth: script không cần API key — kế thừa Claude Code OAuth từ
`~/Library/Keychains/...Claude Code-credentials` (auto-discovery trong
`tradingagents/llm_clients/anthropic_client.py`).

## Symbols tracking

Sửa `src/lib/symbols.ts` để thêm/bớt symbol. Auto routing:
- `^VN*`, `VN30`, `HNX*`, `UPCOM*` → vnstock
- `*.VN` → vnstock (strip suffix)
- Khác → yfinance

## Configuration

Env vars (optional):
- `TRADINGAGENTS_PYTHON` — đường dẫn python venv (default `../venv/bin/python`)

## Lưu ý đầu tư

Dashboard là công cụ research, **không phải lời khuyên đầu tư**.
Mỗi quyết định từ agent là kết quả của một chuỗi LLM calls với
risk model + market data tại thời điểm chạy. Hãy kiểm tra full
debate history (`/agent/:ticker/:date`) trước khi vào lệnh thật.

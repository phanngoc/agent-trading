# Benchmark Pipeline

Một hệ thống đánh giá độ hiệu quả của TradingAgents trên thị trường VN, song song với baselines (Buy & Hold, SMA, Random) để trả lời hai câu hỏi:

1. **Alpha có tồn tại?** TradingAgents có beat VNINDEX sau phí giao dịch không?
2. **Có thuật toán nào tốt hơn?** So với baselines miễn phí, agent có thắng?

## Quick start

### Lần đầu cài đặt

```bash
# 1. Backfill 180 ngày OHLCV cho watchlist (chạy 1 lần)
venv/bin/python -m scripts.benchmark.seed_history --days 180

# 2. Chạy backtest đầu tiên trên data hiện có
venv/bin/python -m scripts.benchmark.run_backtest

# 3. Mở report
open benchmarks/daily/$(date +%F)/report.md
```

### Daily workflow

```bash
# Manual run (skip agent nếu đã có log hôm nay)
venv/bin/python -m scripts.benchmark.run_daily

# Backfill 1 ngày bị miss
venv/bin/python -m scripts.benchmark.run_daily --date 2026-05-15 --force

# Plan only — không gọi LLM, không ghi file
venv/bin/python -m scripts.benchmark.run_daily --dry-run

# Test loop mà không tốn token API
venv/bin/python -m scripts.benchmark.run_daily --skip-agent
```

### Cài cron auto-run hàng ngày

```bash
scripts/benchmark/install_cron.sh           # cài (idempotent)
scripts/benchmark/install_cron.sh --status  # kiểm tra
scripts/benchmark/install_cron.sh --remove  # gỡ
```

Cron chạy **17:00 ICT (10:00 UTC) Thứ 2-Thứ 6**. Log tại `benchmarks/daily/_cron.log`.

## Cấu hình

Mọi tham số trong `benchmarks/config.yaml`:

- **watchlist**: 10 ticker VN30 (VNM, HPG, TCB, VIC, FPT, MWG, MBB, CTG, BID, GAS)
- **initial_capital_vnd**: 1 tỉ
- **fee_buy_pct / fee_sell_pct**: 0.15% / 0.25% (chuẩn broker VN retail)
- **cash_settlement_days**: 3 (T+2.5 HOSE)
- **target_weight_pct**: 0.10 (equal-weight 10%/position)
- **strategies**: 4 — `tradingagents`, `buyhold_vn30`, `sma_crossover`, `random_walk`

Sửa file YAML → re-run backtest. Đổi watchlist mid-run sẽ làm dữ liệu lịch sử không so sánh được — document trong `benchmarks/CHANGELOG.md` nếu phải đổi.

## Danh mục thực của bạn

Tạo `benchmarks/state/user_portfolio.json`:

```json
{
  "updated_at": "2026-05-16",
  "positions": [
    {
      "ticker": "HPG",
      "quantity": 1000,
      "entry_date": "2026-04-01",
      "entry_price": 30000,
      "notes": "DCA sau Q1 earnings"
    },
    {
      "ticker": "VNM",
      "quantity": 500,
      "entry_date": "2026-05-01",
      "entry_price": 62000
    }
  ]
}
```

Mỗi sáng daily brief sẽ:
- Show P&L mark-to-market cho mỗi position
- Cross-reference signal TradingAgents (SELL/HOLD/BUY) cho ticker bạn đang giữ
- Highlight 🔴 SELL signal trên positions held = action cần xử lý

## Output mỗi ngày

```
benchmarks/daily/YYYY-MM-DD/
├── daily_brief.md        # đọc cái này mỗi sáng
├── report.md             # backtest report đầy đủ
├── scorecard.json        # machine-readable metrics
├── equity_curves.csv     # NAV per day per strategy
├── decisions/
│   ├── tradingagents.json
│   ├── buyhold_vn30.json
│   ├── sma_crossover.json
│   └── random_walk.json
└── _agent_logs/
    ├── VNM.log
    ├── HPG.log
    └── ...
```

## Đọc scorecard

| Metric | Ý nghĩa |
|---|---|
| **Total %** | Cumulative return từ start window đến giờ |
| **Annualized %** | Quy về theo năm (252 trading days) |
| **Sharpe** | Risk-adjusted return; >1.0 = tốt, >2.0 = hiếm |
| **Max DD %** | Worst peak-to-trough decline |
| **α annual %** | Alpha sau khi loại bỏ exposure thị trường (CAPM beta) |
| **β** | Sensitivity tới VNINDEX; β=1 = move giống index |
| **t-stat / p-value** | Test thống kê: alpha có khác 0 không? |

**Quy ước**:
- p-value < 0.05 + sample ≥30 phiên ⇒ alpha có ý nghĩa
- p-value 0.05-0.10 + sample lớn ⇒ "thấy có gì đó", chưa kết luận
- p-value > 0.10 ⇒ chưa có evidence; có thể là noise

## Architecture

```
benchmarks/config.yaml ──────┐
benchmarks/state/prices/*.csv │
eval_results/*/...json ──┐    │
                         ▼    ▼
              tradingagents/benchmark/
              ├── models.py        Decision, Position, Trade, Portfolio
              ├── prices.py        PriceBook (VND-normalized)
              ├── execution.py     Fills, fees, T+2.5 settlement
              ├── metrics.py       Sharpe, alpha, t-test
              ├── baselines.py     B&H, SMA, random
              ├── eval_results_reader.py
              ├── user_portfolio.py
              ├── calendar.py
              └── lockfile.py

scripts/benchmark/
├── seed_history.py    Backfill OHLCV
├── run_backtest.py    Replay tất cả strategies
├── run_daily.py       Orchestrator (cron target)
└── install_cron.sh    Setup local cron
```

## Tests

```bash
venv/bin/python -m pytest tests/benchmark/ -v
```

26 unit tests cover dataclasses, execution mechanics, all metric formulas.

## Roadmap

- [x] **Phase 1** — data model + parser + price cache
- [x] **Phase 2** — paper portfolio + execution + metrics + baselines + backtest runner
- [x] **Phase 4** — daily orchestrator + local cron + user portfolio integration
- [ ] **Phase 3** — LSTM next-day predictor as second algorithm baseline
- [ ] **Phase 5** — dashboard `/benchmark` page (equity curves + scoreboard)
- [ ] **Phase 6** — Telegram notification on daily brief completion

## Troubleshooting

**Cron không chạy**

```bash
# Check cron entry tồn tại
scripts/benchmark/install_cron.sh --status

# Tail log
tail -f benchmarks/daily/_cron.log

# Test command identical to what cron sẽ chạy
cd "$REPO_ROOT" && venv/bin/python -m scripts.benchmark.run_daily
```

**vnstock rate limited (20 req/min guest)**

Backfill tự throttle 3.5s. Nếu vẫn bị limit, đăng ký API key miễn phí ở https://vnstocks.com/login (lên 60 req/min).

**Agent run timeout**

Mỗi ticker có 15-min cap. Nếu thường xuyên timeout, giảm `--analysts market,news` (bỏ fundamentals) hoặc switch sang `claude-haiku-4-5` (đã default).

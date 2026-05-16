# Benchmark Report — 2026-05-16

**Window**: 2025-11-16 → 2026-05-15  
**Universe**: VNM, HPG, TCB, VIC, FPT, MWG, MBB, CTG, BID, GAS (10 tickers)  
**Benchmark**: VNINDEX  

## Strategy comparison

| Strategy | Total % | Annualized % | Sharpe | Max DD % | Trades | Hit | Avg/Trade % | α (annual) % | β | t-stat | p-value |
|---|---|---|---|---|---|---|---|---|---|---|---|
| tradingagents | +0.59% | +1.99% | -0.89 | -0.74% | 0 | 0.00 | +0.00% | +1.68% | 0.04 | -0.136 | 0.8917 |
| buyhold_vn30 | -6.06% | -18.94% | -0.86 | -18.60% | 0 | 0.00 | +0.00% | -25.25% | 0.951 | -1.337 | 0.1811 |
| sma_crossover | +3.65% | +12.81% | 1.68 | -1.09% | 4 | 0.25 | -2.51% | +11.75% | 0.054 | 0.1 | 0.9202 |
| random_walk | -12.89% | -37.10% | -3.10 | -17.45% | 71 | 0.42 | -2.06% | -49.45% | 0.557 | -2.137 | 0.0326 |

## Interpretation guide

- **α (annual)** > 0 means the strategy out-performed the benchmark on a risk-adjusted basis.
- **p-value** < 0.05 supports the claim that alpha is statistically real, not noise. Needs ≥30 daily observations for the t-distribution assumption to be robust.
- **Sharpe** above 1.0 is good, above 2.0 is rare. Both are annualized at 252 trading days, risk-free 4%.
- **Hit rate** alone is misleading without **avg/trade** — a strategy can win 80% of trades but still lose money if losing trades are large.
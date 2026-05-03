# vwap_ema_pullback validation raw report
Generated at: 2026-04-27 11:28:06.428936  
execution_mode=next_open, exit_mode=body_below_ema

## Signal stats
| ticker | interval | 기간 | candles | BUY | SELL | HOLD | trades | avg_hold |
|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | 3m | 4311 | 141 | 140 | 4030 | 140 | 8.7 bars / 4.3h |
| KRW-BTC | 30m | 6m | 8623 | 260 | 259 | 8104 | 259 | 8.5 bars / 4.3h |
| KRW-BTC | 30m | 1y | 17481 | 563 | 562 | 16356 | 562 | 8.6 bars / 4.3h |
| KRW-BTC | 1h | 3m | 2157 | 72 | 71 | 2014 | 71 | 8.8 bars / 8.8h |
| KRW-BTC | 1h | 6m | 4314 | 133 | 132 | 4049 | 132 | 8.2 bars / 8.2h |
| KRW-BTC | 1h | 1y | 8745 | 276 | 275 | 8194 | 275 | 9.1 bars / 9.1h |
| KRW-BTC | day | 3m | 91 | 3 | 2 | 86 | 2 | 3.5 bars / 3.5d |
| KRW-BTC | day | 6m | 181 | 4 | 3 | 174 | 3 | 5.3 bars / 5.3d |
| KRW-BTC | day | 1y | 365 | 10 | 9 | 346 | 9 | 7.3 bars / 7.3d |
| KRW-ETH | 30m | 3m | 4311 | 122 | 121 | 4068 | 121 | 9.6 bars / 4.8h |
| KRW-ETH | 30m | 6m | 8623 | 258 | 257 | 8108 | 257 | 8.7 bars / 4.4h |
| KRW-ETH | 30m | 1y | 17481 | 556 | 555 | 16370 | 555 | 9.1 bars / 4.6h |
| KRW-ETH | 1h | 3m | 2157 | 72 | 71 | 2014 | 71 | 7.5 bars / 7.5h |
| KRW-ETH | 1h | 6m | 4314 | 143 | 142 | 4029 | 142 | 8.2 bars / 8.2h |
| KRW-ETH | 1h | 1y | 8745 | 292 | 291 | 8162 | 291 | 9.0 bars / 9.0h |
| KRW-ETH | day | 3m | 91 | 3 | 2 | 86 | 2 | 3.5 bars / 3.5d |
| KRW-ETH | day | 6m | 181 | 4 | 3 | 174 | 3 | 5.7 bars / 5.7d |
| KRW-ETH | day | 1y | 365 | 10 | 9 | 346 | 9 | 7.1 bars / 7.1d |
| KRW-SOL | 30m | 3m | 4311 | 125 | 124 | 4062 | 124 | 9.2 bars / 4.6h |
| KRW-SOL | 30m | 6m | 8623 | 249 | 248 | 8126 | 248 | 8.8 bars / 4.4h |
| KRW-SOL | 30m | 1y | 17480 | 536 | 535 | 16409 | 535 | 9.1 bars / 4.5h |
| KRW-SOL | 1h | 3m | 2157 | 66 | 65 | 2026 | 65 | 7.6 bars / 7.6h |
| KRW-SOL | 1h | 6m | 4314 | 127 | 126 | 4061 | 126 | 7.9 bars / 7.9h |
| KRW-SOL | 1h | 1y | 8744 | 277 | 276 | 8191 | 276 | 8.5 bars / 8.5h |
| KRW-SOL | day | 3m | 91 | 1 | 1 | 89 | 1 | 4.0 bars / 4.0d |
| KRW-SOL | day | 6m | 181 | 1 | 1 | 179 | 1 | 4.0 bars / 4.0d |
| KRW-SOL | day | 1y | 365 | 7 | 7 | 351 | 7 | 9.4 bars / 9.4d |
| KRW-XRP | 30m | 3m | 4311 | 125 | 125 | 4061 | 125 | 8.3 bars / 4.1h |
| KRW-XRP | 30m | 6m | 8623 | 238 | 238 | 8147 | 238 | 8.4 bars / 4.2h |
| KRW-XRP | 30m | 1y | 17481 | 530 | 530 | 16421 | 530 | 8.6 bars / 4.3h |
| KRW-XRP | 1h | 3m | 2157 | 52 | 52 | 2053 | 52 | 7.2 bars / 7.2h |
| KRW-XRP | 1h | 6m | 4314 | 100 | 100 | 4114 | 100 | 7.4 bars / 7.4h |
| KRW-XRP | 1h | 1y | 8745 | 240 | 240 | 8265 | 240 | 8.7 bars / 8.7h |
| KRW-XRP | day | 3m | 91 | 1 | 0 | 90 | 0 | 0.0 bars / 0 |
| KRW-XRP | day | 6m | 181 | 2 | 1 | 178 | 1 | 3.0 bars / 3.0d |
| KRW-XRP | day | 1y | 365 | 6 | 5 | 354 | 5 | 4.2 bars / 4.2d |

## Backtest stats (custom execution simulator; fee=0.0005, slippage=0.0005)
| ticker | interval | 기간 | total | B&H | MDD | win | trades | PF | avg_hold |
|---|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | 3m | -17.57% | -9.59% | -20.70% | +20.57% | 141 | 0.69 | 0.18d |
| KRW-BTC | 30m | 6m | -42.94% | -29.99% | -42.96% | +18.85% | 260 | 0.53 | 0.18d |
| KRW-BTC | 30m | 1y | -71.38% | -14.20% | -72.08% | +18.47% | 563 | 0.44 | 0.18d |
| KRW-BTC | 1h | 3m | -16.20% | -9.67% | -17.80% | +19.44% | 72 | 0.59 | 0.37d |
| KRW-BTC | 1h | 6m | -34.99% | -30.11% | -36.61% | +19.55% | 133 | 0.48 | 0.34d |
| KRW-BTC | 1h | 1y | -49.03% | -13.79% | -51.77% | +22.83% | 276 | 0.51 | 0.38d |
| KRW-BTC | day | 3m | +0.22% | -9.54% | -1.84% | +33.33% | 3 | 1.09 | 6.67d |
| KRW-BTC | day | 6m | -1.40% | -28.73% | -6.01% | +25.00% | 4 | 0.86 | 7.25d |
| KRW-BTC | day | 1y | +3.89% | -14.25% | -9.69% | +30.00% | 10 | 1.32 | 7.90d |
| KRW-ETH | 30m | 3m | -10.12% | -17.82% | -11.35% | +27.87% | 122 | 0.85 | 0.20d |
| KRW-ETH | 30m | 6m | -45.64% | -40.32% | -46.36% | +22.48% | 258 | 0.60 | 0.18d |
| KRW-ETH | 30m | 1y | -49.03% | +33.77% | -58.57% | +25.18% | 556 | 0.80 | 0.19d |
| KRW-ETH | 1h | 3m | -29.67% | -17.83% | -30.22% | +16.67% | 72 | 0.44 | 0.32d |
| KRW-ETH | 1h | 6m | -45.92% | -40.54% | -46.66% | +20.28% | 143 | 0.49 | 0.35d |
| KRW-ETH | 1h | 1y | -34.92% | +35.34% | -54.20% | +21.23% | 292 | 0.84 | 0.38d |
| KRW-ETH | day | 3m | +2.47% | -19.58% | -2.24% | +33.33% | 3 | 1.42 | 9.33d |
| KRW-ETH | day | 6m | -1.44% | -39.44% | -7.46% | +25.00% | 4 | 0.94 | 9.50d |
| KRW-ETH | day | 1y | +2.89% | +36.47% | -14.13% | +40.00% | 10 | 1.19 | 8.50d |
| KRW-SOL | 30m | 3m | -12.64% | -28.78% | -23.35% | +33.60% | 125 | 0.81 | 0.19d |
| KRW-SOL | 30m | 6m | -51.32% | -55.10% | -50.64% | +26.51% | 249 | 0.53 | 0.18d |
| KRW-SOL | 30m | 1y | -72.90% | -39.50% | -75.08% | +26.12% | 536 | 0.61 | 0.19d |
| KRW-SOL | 1h | 3m | -29.24% | -28.76% | -29.82% | +22.73% | 66 | 0.41 | 0.32d |
| KRW-SOL | 1h | 6m | -47.72% | -55.24% | -48.37% | +23.62% | 127 | 0.38 | 0.33d |
| KRW-SOL | 1h | 1y | -59.05% | -38.72% | -64.69% | +25.99% | 277 | 0.61 | 0.35d |
| KRW-SOL | day | 3m | -7.03% | -29.83% | +0.00% | +0.00% | 1 | 0.00 | 4.00d |
| KRW-SOL | day | 6m | -7.03% | -55.31% | +0.00% | +0.00% | 1 | 0.00 | 4.00d |
| KRW-SOL | day | 1y | -12.47% | -39.15% | -18.30% | +42.86% | 7 | 0.62 | 9.43d |
| KRW-XRP | 30m | 3m | -12.15% | -23.76% | -19.73% | +20.00% | 125 | 0.82 | 0.17d |
| KRW-XRP | 30m | 6m | -30.68% | -45.33% | -30.47% | +18.91% | 238 | 0.76 | 0.17d |
| KRW-XRP | 30m | 1y | -49.16% | -32.50% | -58.47% | +22.08% | 530 | 0.79 | 0.18d |
| KRW-XRP | 1h | 3m | -12.12% | -23.79% | -17.45% | +17.31% | 52 | 0.68 | 0.30d |
| KRW-XRP | 1h | 6m | -23.15% | -45.45% | -24.97% | +20.00% | 100 | 0.70 | 0.31d |
| KRW-XRP | 1h | 1y | -19.11% | -31.95% | -35.93% | +24.58% | 240 | 0.91 | 0.36d |
| KRW-XRP | day | 3m | -0.57% | -23.51% | +0.00% | +0.00% | 1 | 0.00 | 3.00d |
| KRW-XRP | day | 6m | -4.49% | -44.13% | -0.57% | +0.00% | 2 | 0.00 | 3.00d |
| KRW-XRP | day | 1y | -16.72% | -35.48% | -15.03% | +0.00% | 6 | 0.00 | 4.00d |

## Interval aggregate, 6m
| interval | avg_trades_6m | avg_return_6m | avg_MDD_6m |
|---|---|---|---|
| 30m | 251.2 | -42.64% | -42.61% |
| 1h | 125.8 | -37.94% | -39.15% |
| day | 2.8 | -3.59% | -3.51% |

## Recent BUY samples
| timestamp | ticker | interval | close | vwap | ema9 | low | is_sideways | reason |
|---|---|---|---|---|---|---|---|---|
| 2026-04-27 07:00:00 | KRW-BTC | 30m | 116570000.00 | 115929081.13 | 116111927.29 | 116300000.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 07:00:00 | KRW-BTC | 30m | 116570000.00 | 115929081.13 | 116111927.29 | 116300000.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 07:00:00 | KRW-BTC | 30m | 116570000.00 | 115929081.13 | 116111927.29 | 116300000.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 04:30:00 | KRW-SOL | 30m | 128900.00 | 128445.91 | 128569.83 | 128500.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 04:30:00 | KRW-SOL | 30m | 128900.00 | 128445.91 | 128569.83 | 128500.00 | False | close>vwap, not sideways, EMA touch, bullish |

## Recent SELL samples
| timestamp | ticker | interval | close | ema9 | entry | pnl | reason |
|---|---|---|---|---|---|---|---|
| 2026-04-26 22:00:00 | KRW-BTC | 1h | 115882000.00 | 115884978.45 | 116074000.00 | -0.17% | close<ema9 |
| 2026-04-26 22:00:00 | KRW-BTC | 1h | 115882000.00 | 115884978.45 | 116074000.00 | -0.17% | close<ema9 |
| 2026-04-26 22:00:00 | KRW-BTC | 1h | 115882000.00 | 115884978.45 | 116074000.00 | -0.17% | close<ema9 |
| 2026-04-26 22:00:00 | KRW-SOL | 1h | 128100.00 | 128485.09 | 128200.00 | -0.08% | close<ema9 |
| 2026-04-26 22:00:00 | KRW-SOL | 1h | 128100.00 | 128485.09 | 128200.00 | -0.08% | close<ema9 |

## Sensitivity (one-at-a-time, BTC/ETH, 6m)
| scope | param | value | BUY | SELL | trades | return | MDD | PF |
|---|---|---|---|---|---|---|---|---|
| KRW-BTC/30m/6m | ema_touch_tolerance | 0.003 | 372 | 371 | 372 | -58.88% | -58.91% | 0.37 |
| KRW-BTC/30m/6m | ema_touch_tolerance | 0.005 | 375 | 374 | 375 | -58.92% | -58.96% | 0.38 |
| KRW-BTC/30m/6m | ema_touch_tolerance | 0.01 | 380 | 379 | 380 | -60.81% | -60.85% | 0.37 |
| KRW-BTC/30m/6m | min_ema_slope_ratio | 0.0005 | 404 | 403 | 404 | -61.17% | -61.20% | 0.38 |
| KRW-BTC/30m/6m | min_ema_slope_ratio | 0.001 | 372 | 371 | 372 | -58.88% | -58.91% | 0.37 |
| KRW-BTC/30m/6m | min_ema_slope_ratio | 0.002 | 314 | 313 | 314 | -50.92% | -50.96% | 0.42 |
| KRW-BTC/30m/6m | max_vwap_cross_count | 2 | 342 | 341 | 342 | -54.19% | -54.14% | 0.40 |
| KRW-BTC/30m/6m | max_vwap_cross_count | 3 | 372 | 371 | 372 | -58.88% | -58.91% | 0.37 |
| KRW-BTC/30m/6m | max_vwap_cross_count | 5 | 398 | 397 | 398 | -61.68% | -61.71% | 0.37 |
| KRW-BTC/30m/6m | require_bullish_candle | True | 372 | 371 | 372 | -58.88% | -58.91% | 0.37 |
| KRW-BTC/30m/6m | require_bullish_candle | False | 402 | 401 | 402 | -62.13% | -61.98% | 0.36 |
| KRW-BTC/1h/6m | ema_touch_tolerance | 0.003 | 188 | 187 | 188 | -38.36% | -39.18% | 0.46 |
| KRW-BTC/1h/6m | ema_touch_tolerance | 0.005 | 188 | 187 | 188 | -38.32% | -39.14% | 0.46 |
| KRW-BTC/1h/6m | ema_touch_tolerance | 0.01 | 189 | 188 | 189 | -38.76% | -39.57% | 0.46 |
| KRW-BTC/1h/6m | min_ema_slope_ratio | 0.0005 | 200 | 199 | 200 | -41.70% | -42.48% | 0.43 |
| KRW-BTC/1h/6m | min_ema_slope_ratio | 0.001 | 188 | 187 | 188 | -38.36% | -39.18% | 0.46 |
| KRW-BTC/1h/6m | min_ema_slope_ratio | 0.002 | 168 | 167 | 168 | -34.09% | -34.90% | 0.48 |
| KRW-BTC/1h/6m | max_vwap_cross_count | 2 | 175 | 174 | 175 | -34.29% | -34.96% | 0.49 |
| KRW-BTC/1h/6m | max_vwap_cross_count | 3 | 188 | 187 | 188 | -38.36% | -39.18% | 0.46 |
| KRW-BTC/1h/6m | max_vwap_cross_count | 5 | 207 | 206 | 207 | -40.66% | -41.50% | 0.47 |
| KRW-BTC/1h/6m | require_bullish_candle | True | 188 | 187 | 188 | -38.36% | -39.18% | 0.46 |
| KRW-BTC/1h/6m | require_bullish_candle | False | 199 | 198 | 199 | -39.21% | -40.11% | 0.46 |
| KRW-ETH/30m/6m | ema_touch_tolerance | 0.003 | 375 | 374 | 375 | -60.30% | -60.75% | 0.48 |
| KRW-ETH/30m/6m | ema_touch_tolerance | 0.005 | 382 | 381 | 382 | -62.30% | -62.73% | 0.47 |
| KRW-ETH/30m/6m | ema_touch_tolerance | 0.01 | 387 | 386 | 387 | -65.18% | -65.58% | 0.45 |
| KRW-ETH/30m/6m | min_ema_slope_ratio | 0.0005 | 382 | 381 | 382 | -59.49% | -59.95% | 0.49 |
| KRW-ETH/30m/6m | min_ema_slope_ratio | 0.001 | 375 | 374 | 375 | -60.30% | -60.75% | 0.48 |
| KRW-ETH/30m/6m | min_ema_slope_ratio | 0.002 | 333 | 332 | 333 | -56.15% | -56.58% | 0.49 |
| KRW-ETH/30m/6m | max_vwap_cross_count | 2 | 346 | 345 | 346 | -59.71% | -60.07% | 0.45 |
| KRW-ETH/30m/6m | max_vwap_cross_count | 3 | 375 | 374 | 375 | -60.30% | -60.75% | 0.48 |
| KRW-ETH/30m/6m | max_vwap_cross_count | 5 | 408 | 407 | 408 | -64.78% | -65.18% | 0.45 |
| KRW-ETH/30m/6m | require_bullish_candle | True | 375 | 374 | 375 | -60.30% | -60.75% | 0.48 |
| KRW-ETH/30m/6m | require_bullish_candle | False | 392 | 391 | 392 | -61.08% | -61.52% | 0.49 |
| KRW-ETH/1h/6m | ema_touch_tolerance | 0.003 | 199 | 198 | 199 | -46.54% | -47.20% | 0.49 |
| KRW-ETH/1h/6m | ema_touch_tolerance | 0.005 | 199 | 198 | 199 | -45.22% | -45.90% | 0.50 |
| KRW-ETH/1h/6m | ema_touch_tolerance | 0.01 | 200 | 199 | 200 | -46.22% | -46.89% | 0.49 |
| KRW-ETH/1h/6m | min_ema_slope_ratio | 0.0005 | 201 | 200 | 201 | -47.15% | -47.81% | 0.48 |
| KRW-ETH/1h/6m | min_ema_slope_ratio | 0.001 | 199 | 198 | 199 | -46.54% | -47.20% | 0.49 |
| KRW-ETH/1h/6m | min_ema_slope_ratio | 0.002 | 184 | 183 | 184 | -48.15% | -48.51% | 0.45 |
| KRW-ETH/1h/6m | max_vwap_cross_count | 2 | 192 | 191 | 192 | -48.45% | -49.09% | 0.44 |
| KRW-ETH/1h/6m | max_vwap_cross_count | 3 | 199 | 198 | 199 | -46.54% | -47.20% | 0.49 |
| KRW-ETH/1h/6m | max_vwap_cross_count | 5 | 210 | 209 | 210 | -50.93% | -51.54% | 0.46 |
| KRW-ETH/1h/6m | require_bullish_candle | True | 199 | 198 | 199 | -46.54% | -47.20% | 0.49 |
| KRW-ETH/1h/6m | require_bullish_candle | False | 210 | 209 | 210 | -46.93% | -47.69% | 0.50 |
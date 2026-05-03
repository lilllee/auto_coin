# vwap_ema_pullback validation raw report
Generated at: 2026-04-27 11:32:12.103973  
execution_mode=next_open, exit_mode=atr_buffer_exit

## Signal stats
| ticker | interval | 기간 | candles | BUY | SELL | HOLD | trades | avg_hold |
|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | 3m | 4311 | 144 | 143 | 4024 | 143 | 7.9 bars / 4.0h |
| KRW-BTC | 30m | 6m | 8623 | 273 | 272 | 8078 | 272 | 7.6 bars / 3.8h |
| KRW-BTC | 30m | 1y | 17481 | 609 | 608 | 16264 | 608 | 7.4 bars / 3.7h |
| KRW-BTC | 1h | 3m | 2157 | 79 | 78 | 2000 | 78 | 7.5 bars / 7.5h |
| KRW-BTC | 1h | 6m | 4314 | 142 | 141 | 4031 | 141 | 7.2 bars / 7.2h |
| KRW-BTC | 1h | 1y | 8745 | 295 | 294 | 8156 | 294 | 8.0 bars / 8.0h |
| KRW-BTC | day | 3m | 91 | 3 | 2 | 86 | 2 | 2.5 bars / 2.5d |
| KRW-BTC | day | 6m | 181 | 4 | 3 | 174 | 3 | 4.3 bars / 4.3d |
| KRW-BTC | day | 1y | 365 | 9 | 8 | 348 | 8 | 7.9 bars / 7.9d |
| KRW-ETH | 30m | 3m | 4311 | 131 | 130 | 4050 | 130 | 8.5 bars / 4.3h |
| KRW-ETH | 30m | 6m | 8623 | 276 | 275 | 8072 | 275 | 7.6 bars / 3.8h |
| KRW-ETH | 30m | 1y | 17481 | 593 | 592 | 16296 | 592 | 8.1 bars / 4.1h |
| KRW-ETH | 1h | 3m | 2157 | 70 | 69 | 2018 | 69 | 7.3 bars / 7.3h |
| KRW-ETH | 1h | 6m | 4314 | 149 | 148 | 4017 | 148 | 7.3 bars / 7.3h |
| KRW-ETH | 1h | 1y | 8745 | 299 | 298 | 8148 | 298 | 8.2 bars / 8.2h |
| KRW-ETH | day | 3m | 91 | 3 | 2 | 86 | 2 | 11.0 bars / 11.0d |
| KRW-ETH | day | 6m | 181 | 4 | 3 | 174 | 3 | 10.3 bars / 10.3d |
| KRW-ETH | day | 1y | 365 | 10 | 9 | 346 | 9 | 8.7 bars / 8.7d |
| KRW-SOL | 30m | 3m | 4311 | 134 | 133 | 4044 | 133 | 8.2 bars / 4.1h |
| KRW-SOL | 30m | 6m | 8623 | 268 | 267 | 8088 | 267 | 7.6 bars / 3.8h |
| KRW-SOL | 30m | 1y | 17480 | 585 | 584 | 16311 | 584 | 7.8 bars / 3.9h |
| KRW-SOL | 1h | 3m | 2157 | 69 | 68 | 2020 | 68 | 6.6 bars / 6.6h |
| KRW-SOL | 1h | 6m | 4314 | 134 | 133 | 4047 | 133 | 6.9 bars / 6.9h |
| KRW-SOL | 1h | 1y | 8744 | 291 | 290 | 8163 | 290 | 7.5 bars / 7.5h |
| KRW-SOL | day | 3m | 91 | 1 | 1 | 89 | 1 | 3.0 bars / 3.0d |
| KRW-SOL | day | 6m | 181 | 1 | 1 | 179 | 1 | 3.0 bars / 3.0d |
| KRW-SOL | day | 1y | 365 | 6 | 6 | 353 | 6 | 11.0 bars / 11.0d |
| KRW-XRP | 30m | 3m | 4311 | 127 | 127 | 4057 | 127 | 7.8 bars / 3.9h |
| KRW-XRP | 30m | 6m | 8623 | 242 | 242 | 8139 | 242 | 7.9 bars / 3.9h |
| KRW-XRP | 30m | 1y | 17481 | 552 | 552 | 16377 | 552 | 7.9 bars / 3.9h |
| KRW-XRP | 1h | 3m | 2157 | 49 | 49 | 2059 | 49 | 7.3 bars / 7.3h |
| KRW-XRP | 1h | 6m | 4314 | 96 | 96 | 4122 | 96 | 7.3 bars / 7.3h |
| KRW-XRP | 1h | 1y | 8745 | 249 | 249 | 8247 | 249 | 7.9 bars / 7.9h |
| KRW-XRP | day | 3m | 91 | 1 | 0 | 90 | 0 | 0.0 bars / 0 |
| KRW-XRP | day | 6m | 181 | 2 | 1 | 178 | 1 | 5.0 bars / 5.0d |
| KRW-XRP | day | 1y | 365 | 5 | 4 | 356 | 4 | 5.5 bars / 5.5d |

## Backtest stats (custom execution simulator; fee=0.0005, slippage=0.0005)
| ticker | interval | 기간 | total | B&H | MDD | win | trades | PF | avg_hold |
|---|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | 3m | -22.27% | -9.59% | -25.45% | +20.14% | 144 | 0.60 | 0.16d |
| KRW-BTC | 30m | 6m | -47.32% | -29.99% | -47.27% | +17.22% | 273 | 0.48 | 0.16d |
| KRW-BTC | 30m | 1y | -75.62% | -14.20% | -75.66% | +16.09% | 609 | 0.39 | 0.15d |
| KRW-BTC | 1h | 3m | -20.40% | -9.67% | -20.38% | +20.25% | 79 | 0.53 | 0.31d |
| KRW-BTC | 1h | 6m | -37.11% | -30.11% | -37.47% | +19.72% | 142 | 0.47 | 0.30d |
| KRW-BTC | 1h | 1y | -49.57% | -13.79% | -52.23% | +21.36% | 295 | 0.53 | 0.33d |
| KRW-BTC | day | 3m | +3.23% | -9.54% | -1.75% | +33.33% | 3 | 2.06 | 6.00d |
| KRW-BTC | day | 6m | +5.54% | -28.73% | -3.19% | +50.00% | 4 | 2.76 | 6.50d |
| KRW-BTC | day | 1y | +15.11% | -14.25% | -3.19% | +44.44% | 9 | 2.98 | 8.44d |
| KRW-ETH | 30m | 3m | -18.06% | -17.82% | -19.59% | +25.19% | 131 | 0.73 | 0.18d |
| KRW-ETH | 30m | 6m | -54.56% | -40.32% | -55.21% | +21.38% | 276 | 0.52 | 0.16d |
| KRW-ETH | 30m | 1y | -57.34% | +33.77% | -63.49% | +23.10% | 593 | 0.74 | 0.17d |
| KRW-ETH | 1h | 3m | -25.95% | -17.83% | -24.99% | +21.43% | 70 | 0.49 | 0.31d |
| KRW-ETH | 1h | 6m | -43.26% | -40.54% | -43.88% | +18.79% | 149 | 0.51 | 0.31d |
| KRW-ETH | 1h | 1y | -29.93% | +35.34% | -52.43% | +21.74% | 299 | 0.87 | 0.34d |
| KRW-ETH | day | 3m | +5.54% | -19.58% | +0.00% | +66.67% | 3 | 2.91 | 9.33d |
| KRW-ETH | day | 6m | +9.21% | -39.44% | -2.94% | +75.00% | 4 | 4.10 | 9.25d |
| KRW-ETH | day | 1y | +12.89% | +36.47% | -3.52% | +60.00% | 10 | 2.06 | 8.40d |
| KRW-SOL | 30m | 3m | -24.80% | -28.78% | -29.85% | +26.87% | 134 | 0.62 | 0.17d |
| KRW-SOL | 30m | 6m | -58.31% | -55.10% | -58.09% | +21.64% | 268 | 0.45 | 0.16d |
| KRW-SOL | 30m | 1y | -77.92% | -39.50% | -79.59% | +23.93% | 585 | 0.56 | 0.16d |
| KRW-SOL | 1h | 3m | -28.80% | -28.76% | -29.17% | +21.74% | 69 | 0.39 | 0.28d |
| KRW-SOL | 1h | 6m | -46.65% | -55.24% | -46.51% | +23.13% | 134 | 0.39 | 0.29d |
| KRW-SOL | 1h | 1y | -57.30% | -38.72% | -62.38% | +27.84% | 291 | 0.61 | 0.31d |
| KRW-SOL | day | 3m | -3.95% | -29.83% | +0.00% | +0.00% | 1 | 0.00 | 3.00d |
| KRW-SOL | day | 6m | -3.95% | -55.31% | +0.00% | +0.00% | 1 | 0.00 | 3.00d |
| KRW-SOL | day | 1y | -2.56% | -39.15% | -15.59% | +33.33% | 6 | 1.00 | 11.00d |
| KRW-XRP | 30m | 3m | -14.20% | -23.76% | -18.57% | +20.47% | 127 | 0.79 | 0.16d |
| KRW-XRP | 30m | 6m | -29.32% | -45.33% | -28.73% | +19.83% | 242 | 0.76 | 0.16d |
| KRW-XRP | 30m | 1y | -54.20% | -32.50% | -58.15% | +22.64% | 552 | 0.75 | 0.16d |
| KRW-XRP | 1h | 3m | -8.08% | -23.79% | -17.84% | +16.33% | 49 | 0.80 | 0.30d |
| KRW-XRP | 1h | 6m | -16.86% | -45.45% | -20.24% | +17.71% | 96 | 0.79 | 0.30d |
| KRW-XRP | 1h | 1y | -22.04% | -31.95% | -38.16% | +23.29% | 249 | 0.89 | 0.33d |
| KRW-XRP | day | 3m | -0.57% | -23.51% | +0.00% | +0.00% | 1 | 0.00 | 3.00d |
| KRW-XRP | day | 6m | -7.53% | -44.13% | -0.57% | +0.00% | 2 | 0.00 | 4.00d |
| KRW-XRP | day | 1y | -15.85% | -35.48% | -11.83% | +20.00% | 5 | 0.01 | 5.00d |

## Interval aggregate, 6m
| interval | avg_trades_6m | avg_return_6m | avg_MDD_6m |
|---|---|---|---|
| 30m | 264.8 | -47.38% | -47.32% |
| 1h | 130.2 | -35.97% | -37.03% |
| day | 2.8 | +0.82% | -1.68% |

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
| 2026-04-27 01:00:00 | KRW-BTC | 1h | 115810000.00 | 115924044.96 | 116054000.00 | -0.21% | close<ema9 |
| 2026-04-27 01:00:00 | KRW-BTC | 1h | 115810000.00 | 115924044.96 | 116054000.00 | -0.21% | close<ema9 |
| 2026-04-27 01:00:00 | KRW-BTC | 1h | 115810000.00 | 115924044.96 | 116054000.00 | -0.21% | close<ema9 |
| 2026-04-26 21:30:00 | KRW-BTC | 30m | 115763000.00 | 115997767.78 | 116094000.00 | -0.29% | close<ema9 |
| 2026-04-26 21:30:00 | KRW-BTC | 30m | 115763000.00 | 115997767.78 | 116094000.00 | -0.29% | close<ema9 |

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
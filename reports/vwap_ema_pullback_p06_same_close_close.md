# vwap_ema_pullback validation raw report
Generated at: 2026-04-27 11:24:14.301331  
execution_mode=same_close, exit_mode=close_below_ema

## Signal stats
| ticker | interval | 기간 | candles | BUY | SELL | HOLD | trades | avg_hold |
|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | 3m | 4311 | 195 | 194 | 3922 | 194 | 5.1 bars / 2.5h |
| KRW-BTC | 30m | 6m | 8623 | 372 | 371 | 7880 | 371 | 4.8 bars / 2.4h |
| KRW-BTC | 30m | 1y | 17481 | 824 | 823 | 15834 | 823 | 4.7 bars / 2.3h |
| KRW-BTC | 1h | 3m | 2157 | 107 | 106 | 1944 | 106 | 4.9 bars / 4.9h |
| KRW-BTC | 1h | 6m | 4314 | 188 | 187 | 3939 | 187 | 4.7 bars / 4.7h |
| KRW-BTC | 1h | 1y | 8745 | 405 | 404 | 7936 | 404 | 5.1 bars / 5.1h |
| KRW-BTC | day | 3m | 91 | 4 | 3 | 84 | 3 | 3.7 bars / 3.7d |
| KRW-BTC | day | 6m | 181 | 5 | 4 | 172 | 4 | 4.8 bars / 4.8d |
| KRW-BTC | day | 1y | 365 | 12 | 11 | 342 | 11 | 5.6 bars / 5.6d |
| KRW-ETH | 30m | 3m | 4311 | 173 | 172 | 3966 | 172 | 5.8 bars / 2.9h |
| KRW-ETH | 30m | 6m | 8623 | 375 | 374 | 7874 | 374 | 5.0 bars / 2.5h |
| KRW-ETH | 30m | 1y | 17481 | 826 | 825 | 15830 | 825 | 5.1 bars / 2.5h |
| KRW-ETH | 1h | 3m | 2157 | 96 | 95 | 1966 | 95 | 4.7 bars / 4.7h |
| KRW-ETH | 1h | 6m | 4314 | 199 | 198 | 3917 | 198 | 4.9 bars / 4.9h |
| KRW-ETH | 1h | 1y | 8745 | 414 | 413 | 7918 | 413 | 5.3 bars / 5.3h |
| KRW-ETH | day | 3m | 91 | 5 | 4 | 82 | 4 | 5.8 bars / 5.8d |
| KRW-ETH | day | 6m | 181 | 6 | 5 | 170 | 5 | 6.4 bars / 6.4d |
| KRW-ETH | day | 1y | 365 | 15 | 14 | 336 | 14 | 5.0 bars / 5.0d |
| KRW-SOL | 30m | 3m | 4311 | 179 | 178 | 3954 | 178 | 5.2 bars / 2.6h |
| KRW-SOL | 30m | 6m | 8623 | 351 | 350 | 7922 | 350 | 5.0 bars / 2.5h |
| KRW-SOL | 30m | 1y | 17480 | 769 | 768 | 15943 | 768 | 5.2 bars / 2.6h |
| KRW-SOL | 1h | 3m | 2157 | 88 | 87 | 1982 | 87 | 4.5 bars / 4.5h |
| KRW-SOL | 1h | 6m | 4314 | 175 | 174 | 3965 | 174 | 4.6 bars / 4.6h |
| KRW-SOL | 1h | 1y | 8744 | 390 | 389 | 7965 | 389 | 4.9 bars / 4.9h |
| KRW-SOL | day | 3m | 91 | 1 | 1 | 89 | 1 | 3.0 bars / 3.0d |
| KRW-SOL | day | 6m | 181 | 1 | 1 | 179 | 1 | 3.0 bars / 3.0d |
| KRW-SOL | day | 1y | 365 | 12 | 12 | 341 | 12 | 4.5 bars / 4.5d |
| KRW-XRP | 30m | 3m | 4311 | 174 | 174 | 3963 | 174 | 4.8 bars / 2.4h |
| KRW-XRP | 30m | 6m | 8623 | 326 | 326 | 7971 | 326 | 5.0 bars / 2.5h |
| KRW-XRP | 30m | 1y | 17481 | 753 | 753 | 15975 | 753 | 5.0 bars / 2.5h |
| KRW-XRP | 1h | 3m | 2157 | 67 | 67 | 2023 | 67 | 4.5 bars / 4.5h |
| KRW-XRP | 1h | 6m | 4314 | 127 | 127 | 4060 | 127 | 4.6 bars / 4.6h |
| KRW-XRP | 1h | 1y | 8745 | 333 | 333 | 8079 | 333 | 5.1 bars / 5.1h |
| KRW-XRP | day | 3m | 91 | 1 | 0 | 90 | 0 | 0.0 bars / 0 |
| KRW-XRP | day | 6m | 181 | 2 | 1 | 178 | 1 | 2.0 bars / 2.0d |
| KRW-XRP | day | 1y | 365 | 7 | 6 | 352 | 6 | 2.0 bars / 2.0d |

## Backtest stats (custom execution simulator; fee=0.0005, slippage=0.0005)
| ticker | interval | 기간 | total | B&H | MDD | win | trades | PF | avg_hold |
|---|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | 3m | -30.51% | -9.59% | -32.89% | +17.44% | 195 | 0.51 | 0.11d |
| KRW-BTC | 30m | 6m | -58.88% | -29.99% | -58.91% | +15.59% | 372 | 0.37 | 0.10d |
| KRW-BTC | 30m | 1y | -86.53% | -14.20% | -86.50% | +13.96% | 824 | 0.30 | 0.10d |
| KRW-BTC | 1h | 3m | -20.62% | -9.67% | -21.46% | +23.36% | 107 | 0.53 | 0.21d |
| KRW-BTC | 1h | 6m | -38.36% | -30.11% | -39.18% | +20.74% | 188 | 0.46 | 0.20d |
| KRW-BTC | 1h | 1y | -58.90% | -13.79% | -60.20% | +20.00% | 405 | 0.45 | 0.21d |
| KRW-BTC | day | 3m | +0.78% | -9.54% | -1.70% | +25.00% | 4 | 1.27 | 4.50d |
| KRW-BTC | day | 6m | +3.07% | -28.73% | -3.20% | +40.00% | 5 | 1.98 | 5.20d |
| KRW-BTC | day | 1y | +13.81% | -14.25% | -3.20% | +41.67% | 12 | 2.76 | 5.75d |
| KRW-ETH | 30m | 3m | -20.57% | -17.82% | -21.52% | +20.81% | 173 | 0.71 | 0.12d |
| KRW-ETH | 30m | 6m | -60.30% | -40.32% | -60.75% | +16.80% | 375 | 0.48 | 0.10d |
| KRW-ETH | 30m | 1y | -75.86% | +33.77% | -78.61% | +18.64% | 826 | 0.61 | 0.11d |
| KRW-ETH | 1h | 3m | -26.85% | -17.83% | -25.92% | +17.71% | 96 | 0.50 | 0.20d |
| KRW-ETH | 1h | 6m | -46.54% | -40.54% | -47.20% | +16.58% | 199 | 0.49 | 0.20d |
| KRW-ETH | 1h | 1y | -46.45% | +35.34% | -58.96% | +20.05% | 414 | 0.77 | 0.22d |
| KRW-ETH | day | 3m | +3.15% | -19.58% | -1.86% | +60.00% | 5 | 1.70 | 5.00d |
| KRW-ETH | day | 6m | +6.77% | -39.44% | -4.72% | +66.67% | 6 | 2.43 | 5.67d |
| KRW-ETH | day | 1y | +3.32% | +36.47% | -14.25% | +40.00% | 15 | 1.20 | 4.80d |
| KRW-SOL | 30m | 3m | -27.43% | -28.78% | -31.14% | +21.23% | 179 | 0.61 | 0.11d |
| KRW-SOL | 30m | 6m | -62.95% | -55.10% | -62.62% | +19.09% | 351 | 0.43 | 0.10d |
| KRW-SOL | 30m | 1y | -85.51% | -39.50% | -86.18% | +20.81% | 769 | 0.48 | 0.11d |
| KRW-SOL | 1h | 3m | -26.74% | -28.76% | -26.81% | +19.32% | 88 | 0.44 | 0.19d |
| KRW-SOL | 1h | 6m | -48.64% | -55.24% | -48.56% | +18.29% | 175 | 0.40 | 0.19d |
| KRW-SOL | 1h | 1y | -68.79% | -38.72% | -71.47% | +23.33% | 390 | 0.54 | 0.20d |
| KRW-SOL | day | 3m | -4.09% | -29.83% | +0.00% | +0.00% | 1 | 0.00 | 3.00d |
| KRW-SOL | day | 6m | -4.09% | -55.31% | +0.00% | +0.00% | 1 | 0.00 | 3.00d |
| KRW-SOL | day | 1y | -8.71% | -39.15% | -17.95% | +33.33% | 12 | 0.76 | 4.50d |
| KRW-XRP | 30m | 3m | -25.05% | -23.76% | -29.52% | +14.37% | 174 | 0.64 | 0.10d |
| KRW-XRP | 30m | 6m | -39.42% | -45.33% | -38.94% | +15.03% | 326 | 0.68 | 0.10d |
| KRW-XRP | 30m | 1y | -69.83% | -32.50% | -70.91% | +17.93% | 753 | 0.65 | 0.10d |
| KRW-XRP | 1h | 3m | -6.79% | -23.79% | -13.34% | +13.43% | 67 | 0.84 | 0.19d |
| KRW-XRP | 1h | 6m | -12.53% | -45.45% | -16.39% | +15.75% | 127 | 0.85 | 0.19d |
| KRW-XRP | 1h | 1y | -25.70% | -31.95% | -38.94% | +21.02% | 333 | 0.86 | 0.21d |
| KRW-XRP | day | 3m | -0.57% | -23.51% | +0.00% | +0.00% | 1 | 0.00 | 4.00d |
| KRW-XRP | day | 6m | -4.21% | -44.13% | -0.57% | +0.00% | 2 | 0.00 | 3.00d |
| KRW-XRP | day | 1y | -21.80% | -35.48% | -19.64% | +0.00% | 7 | 0.00 | 2.29d |

## Interval aggregate, 6m
| interval | avg_trades_6m | avg_return_6m | avg_MDD_6m |
|---|---|---|---|
| 30m | 356.0 | -55.39% | -55.30% |
| 1h | 172.2 | -36.52% | -37.83% |
| day | 3.5 | +0.38% | -2.12% |

## Recent BUY samples
| timestamp | ticker | interval | close | vwap | ema9 | low | is_sideways | reason |
|---|---|---|---|---|---|---|---|---|
| 2026-04-27 09:30:00 | KRW-SOL | 30m | 129400.00 | 128588.57 | 128801.92 | 128400.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 09:30:00 | KRW-SOL | 30m | 129400.00 | 128588.57 | 128801.92 | 128400.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 09:30:00 | KRW-SOL | 30m | 129400.00 | 128588.57 | 128801.92 | 128400.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 09:00:00 | KRW-SOL | 1h | 129400.00 | 128551.96 | 128782.07 | 128400.00 | False | close>vwap, not sideways, EMA touch, bullish |
| 2026-04-27 09:00:00 | KRW-SOL | 1h | 129400.00 | 128551.96 | 128782.07 | 128400.00 | False | close>vwap, not sideways, EMA touch, bullish |

## Recent SELL samples
| timestamp | ticker | interval | close | ema9 | entry | pnl | reason |
|---|---|---|---|---|---|---|---|
| 2026-04-27 09:00:00 | KRW-SOL | 30m | 128700.00 | 128827.40 | 129100.00 | -0.31% | close<ema9 |
| 2026-04-27 09:00:00 | KRW-SOL | 30m | 128700.00 | 128827.40 | 129100.00 | -0.31% | close<ema9 |
| 2026-04-27 09:00:00 | KRW-SOL | 30m | 128700.00 | 128827.40 | 129100.00 | -0.31% | close<ema9 |
| 2026-04-27 08:00:00 | KRW-BTC | 30m | 116155000.00 | 116227233.46 | 116570000.00 | -0.36% | close<ema9 |
| 2026-04-27 08:00:00 | KRW-BTC | 30m | 116155000.00 | 116227233.46 | 116570000.00 | -0.36% | close<ema9 |

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
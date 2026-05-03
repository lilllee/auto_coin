# vwap_ema_pullback P0.6 체결/청산 검증 요약
fee=0.05%, slippage=0.05% 반영. 집계는 KRW-BTC/ETH/SOL/XRP 평균입니다.

## same_close vs next_open 비교 (6m, close_below_ema)
| interval | exit mode | execution | return | MDD | win rate | trades | PF | avg hold |
|---|---|---|---|---|---|---|---|---|
| 30m | close_below_ema | same_close | -55.39% | -55.30% | +16.63% | 356.0 | 0.49 | 2.5h |
| 30m | close_below_ema | next_open | -54.66% | -54.56% | +16.62% | 356.0 | 0.50 | 2.5h |
| 1h | close_below_ema | same_close | -36.52% | -37.83% | +17.84% | 172.2 | 0.55 | 4.7h |
| 1h | close_below_ema | next_open | -35.81% | -37.34% | +17.84% | 172.2 | 0.55 | 4.7h |
| day | close_below_ema | same_close | +0.38% | -2.12% | +26.67% | 3.5 | 1.10 | 101.2h |
| day | close_below_ema | next_open | +0.39% | -2.14% | +31.67% | 3.5 | 1.09 | 96.0h |

## exit mode별 비교 (6m, next_open)
| interval | exit mode | return | MDD | win rate | trades | PF | avg hold | 해석 |
|---|---|---|---|---|---|---|---|---|
| 30m | close_below_ema | -54.66% | -54.56% | +16.62% | 356.0 | 0.50 | 2.5h | 기존 기준선 |
| 30m | body_below_ema | -42.64% | -42.61% | +21.69% | 251.2 | 0.61 | 4.3h | 거래 감소/보유 증가, 30m 개선폭 큼 |
| 30m | confirm_close_below_ema | -42.28% | -42.19% | +21.72% | 250.0 | 0.61 | 4.3h | body와 거의 유사, 일부 손실 확대 |
| 30m | atr_buffer_exit | -47.38% | -47.32% | +20.02% | 264.8 | 0.55 | 3.8h | day 최선, 1h는 close 대비 소폭 개선 |
| 1h | close_below_ema | -35.81% | -37.34% | +17.84% | 172.2 | 0.55 | 4.7h | 기존 기준선 |
| 1h | body_below_ema | -37.94% | -39.15% | +20.86% | 125.8 | 0.51 | 8.0h | 거래 감소/보유 증가, 30m 개선폭 큼 |
| 1h | confirm_close_below_ema | -38.40% | -39.55% | +21.03% | 126.2 | 0.51 | 7.9h | body와 거의 유사, 일부 손실 확대 |
| 1h | atr_buffer_exit | -35.97% | -37.03% | +19.84% | 130.2 | 0.54 | 7.2h | day 최선, 1h는 close 대비 소폭 개선 |
| day | close_below_ema | +0.39% | -2.14% | +31.67% | 3.5 | 1.09 | 96.0h | 기존 기준선 |
| day | body_below_ema | -3.59% | -3.51% | +12.50% | 2.8 | 0.45 | 142.5h | 거래 감소/보유 증가, 30m 개선폭 큼 |
| day | confirm_close_below_ema | -3.59% | -3.51% | +12.50% | 2.8 | 0.45 | 142.5h | body와 거의 유사, 일부 손실 확대 |
| day | atr_buffer_exit | +0.82% | -1.68% | +31.25% | 2.8 | 1.71 | 136.5h | day 최선, 1h는 close 대비 소폭 개선 |

## body_below_ema 상세 (6m, next_open)
| ticker | interval | return | B&H | MDD | win rate | trades | PF | avg hold |
|---|---|---|---|---|---|---|---|---|
| KRW-BTC | 30m | -42.94% | -29.99% | -42.96% | +18.85% | 260 | 0.53 | 4.2h |
| KRW-ETH | 30m | -45.64% | -40.32% | -46.36% | +22.48% | 258 | 0.60 | 4.4h |
| KRW-SOL | 30m | -51.32% | -55.10% | -50.64% | +26.51% | 249 | 0.53 | 4.4h |
| KRW-XRP | 30m | -30.68% | -45.33% | -30.47% | +18.91% | 238 | 0.76 | 4.2h |
| KRW-BTC | 1h | -34.99% | -30.11% | -36.61% | +19.55% | 133 | 0.48 | 8.2h |
| KRW-ETH | 1h | -45.92% | -40.54% | -46.66% | +20.28% | 143 | 0.49 | 8.3h |
| KRW-SOL | 1h | -47.72% | -55.24% | -48.37% | +23.62% | 127 | 0.38 | 7.9h |
| KRW-XRP | 1h | -23.15% | -45.45% | -24.97% | +20.00% | 100 | 0.70 | 7.4h |
| KRW-BTC | day | -1.40% | -28.73% | -6.01% | +25.00% | 4 | 0.86 | 174.0h |
| KRW-ETH | day | -1.44% | -39.44% | -7.46% | +25.00% | 4 | 0.94 | 228.0h |
| KRW-SOL | day | -7.03% | -55.31% | +0.00% | +0.00% | 1 | 0.00 | 96.0h |
| KRW-XRP | day | -4.49% | -44.13% | -0.57% | +0.00% | 2 | 0.00 | 72.0h |

## 상대적으로 나은 6m 후보
| rank | ticker | interval | execution | exit mode | return | MDD | PF | trades | reason |
|---|---|---|---|---|---|---|---|---|---|
| 1 | KRW-ETH | day | next_open | atr_buffer_exit | +9.21% | -2.94% | 4.10 | 4 | 6m 기준 상대적으로 손실/거래수/MDD가 낮음 |
| 2 | KRW-BTC | day | next_open | atr_buffer_exit | +5.54% | -3.19% | 2.76 | 4 | 6m 기준 상대적으로 손실/거래수/MDD가 낮음 |
| 3 | KRW-ETH | day | next_open | close_below_ema | +6.65% | -4.81% | 2.38 | 6 | 6m 기준 상대적으로 손실/거래수/MDD가 낮음 |
| 4 | KRW-BTC | day | next_open | close_below_ema | +3.06% | -3.19% | 1.98 | 5 | 6m 기준 상대적으로 손실/거래수/MDD가 낮음 |
| 5 | KRW-ETH | day | next_open | body_below_ema | -1.44% | -7.46% | 0.94 | 4 | 6m 기준 상대적으로 손실/거래수/MDD가 낮음 |
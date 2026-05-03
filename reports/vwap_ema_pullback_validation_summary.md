# vwap_ema_pullback 전략 검증 보고서

## 1. 한 줄 결론

`vwap_ema_pullback`은 30m/1h/day 모두에서 신호는 정상 발생하지만, 30m·1h는 거래가 매우 잦고 평균 보유가 2~5시간으로 짧아 수수료/슬리피지 반영 후 성과가 크게 불리합니다. 지표 계산 자체는 shift(1) 기반으로 안전하지만, 기존 generic backtest가 신호 발생 candle의 close로 즉시 체결하므로 실전성 관점의 execution bias가 의심됩니다.

## 2. 검증한 파일/구조

| 파일 | 확인 내용 |
|---|---|
| `src/auto_coin/strategy/vwap_ema_pullback.py` | Entry/Exit/long-only/Volume Profile OFF 로직 |
| `src/auto_coin/data/candles.py` | EMA/VWAP/sideways enrich 및 shift 정책 |
| `src/auto_coin/backtest/runner.py` | generic backtest 체결 가격/수수료/슬리피지 정책 |
| `src/auto_coin/strategy/__init__.py` | registry/params/execution mode 등록 |
| `reports/vwap_ema_pullback_validation.md` | 전체 raw signal/backtest/sensitivity 결과 |
| `reports/vwap_ema_pullback_validation.json` | 전체 검증 데이터 JSON |

## 3. lookahead bias 점검

판단: **의심**

근거:
- EMA9는 `ewm(...).shift(1)`로 직전 확정 EMA를 사용합니다.
- VWAP도 rolling VWAP 계산 후 `shift(1)`로 직전 확정 VWAP을 사용합니다.
- VWAP cross와 EMA slope도 shift된 VWAP/EMA 기반이라 indicator 자체의 미래 참조는 발견되지 않았습니다.
- 다만 전략은 현재 candle의 `open/high/low/close`가 확정된 뒤 판단하는 구조이고, 기존 generic backtest는 같은 row의 `close`로 즉시 진입/청산합니다. 이는 “종가 신호를 종가에 체결”하는 가정이라 실거래/보수적 백테스트 기준으로 execution bias가 있습니다.

수정 필요 여부:
- indicator 로직은 즉시 수정 필요 없음.
- Phase 2 전에는 next-bar open 체결 또는 close+1 체결 모드로 재검증 권장.

## 4. 신호 발생 현황, 6개월 기준

| ticker | interval | 기간 | candle 수 | BUY | SELL | HOLD | trade 수 | avg hold |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| KRW-BTC | 30m | 6m | 8623 | 372 | 371 | 7880 | 371 | 4.8 bars / 2.4h |
| KRW-ETH | 30m | 6m | 8623 | 375 | 374 | 7874 | 374 | 5.0 bars / 2.5h |
| KRW-SOL | 30m | 6m | 8623 | 351 | 350 | 7922 | 350 | 5.0 bars / 2.5h |
| KRW-XRP | 30m | 6m | 8623 | 326 | 326 | 7971 | 326 | 5.0 bars / 2.5h |
| KRW-BTC | 1h | 6m | 4314 | 188 | 187 | 3939 | 187 | 4.7 bars / 4.7h |
| KRW-ETH | 1h | 6m | 4314 | 199 | 198 | 3917 | 198 | 4.9 bars / 4.9h |
| KRW-SOL | 1h | 6m | 4314 | 175 | 174 | 3965 | 174 | 4.6 bars / 4.6h |
| KRW-XRP | 1h | 6m | 4314 | 127 | 127 | 4060 | 127 | 4.6 bars / 4.6h |
| KRW-BTC | day | 6m | 181 | 5 | 4 | 172 | 4 | 4.8 bars / 4.8d |
| KRW-ETH | day | 6m | 181 | 6 | 5 | 170 | 5 | 6.4 bars / 6.4d |
| KRW-SOL | day | 6m | 181 | 1 | 1 | 179 | 1 | 3.0 bars / 3.0d |
| KRW-XRP | day | 6m | 181 | 2 | 1 | 178 | 1 | 2.0 bars / 2.0d |

## 5. 백테스트 결과, 6개월 기준

기존 generic runner 기준, fee=0.05%, slippage=0.05% 반영.

| ticker | interval | 기간 | total return | B&H return | MDD | win rate | trades | profit factor | avg hold |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| KRW-BTC | 30m | 6m | -58.88% | -29.99% | -58.91% | 15.59% | 372 | 0.37 | 0.10d |
| KRW-ETH | 30m | 6m | -60.30% | -40.32% | -60.75% | 16.80% | 375 | 0.48 | 0.10d |
| KRW-SOL | 30m | 6m | -62.95% | -55.10% | -62.62% | 19.09% | 351 | 0.43 | 0.10d |
| KRW-XRP | 30m | 6m | -39.42% | -45.33% | -38.94% | 15.03% | 326 | 0.68 | 0.10d |
| KRW-BTC | 1h | 6m | -38.36% | -30.11% | -39.18% | 20.74% | 188 | 0.46 | 0.20d |
| KRW-ETH | 1h | 6m | -46.54% | -40.54% | -47.20% | 16.58% | 199 | 0.49 | 0.20d |
| KRW-SOL | 1h | 6m | -48.64% | -55.24% | -48.56% | 18.29% | 175 | 0.40 | 0.19d |
| KRW-XRP | 1h | 6m | -12.53% | -45.45% | -16.39% | 15.75% | 127 | 0.85 | 0.19d |
| KRW-BTC | day | 6m | +3.07% | -28.73% | -3.20% | 40.00% | 5 | 1.98 | 5.20d |
| KRW-ETH | day | 6m | +6.77% | -39.44% | -4.72% | 66.67% | 6 | 2.43 | 5.67d |
| KRW-SOL | day | 6m | -4.09% | -55.31% | 0.00% | 0.00% | 1 | 0.00 | 3.00d |
| KRW-XRP | day | 6m | -4.21% | -44.13% | -0.57% | 0.00% | 2 | 0.00 | 3.00d |

## 6. interval별 평가

### 30m

- 장점: 24시간 rolling VWAP 의미는 자연스럽고 신호는 충분히 발생합니다.
- 문제: 6개월 평균 약 356회 거래, 평균 보유 약 2.4~2.5h로 매우 잦습니다. 비용 반영 후 4개 티커 모두 큰 손실입니다.
- 추천 여부: **비추천**. Phase 2 전 청산/진입 빈도 제어가 필요합니다.

### 1h

- 장점: 30m 대비 거래 수가 절반 수준이고 XRP에서는 방어력이 상대적으로 좋았습니다.
- 문제: 그래도 6개월 127~199회 거래로 많고, 평균 보유가 4~5h에 불과합니다. BTC/ETH/SOL 손익비가 낮습니다.
- 추천 여부: **조건부 후보**. 30m보다 낫지만 기본값 그대로 실전/Phase 2 진행은 이릅니다.

### day

- 장점: 거래 수가 적고 BTC/ETH 6개월·1년에서는 양호한 결과가 나왔습니다.
- 문제: `vwap_period=48`은 48일이라 신호가 느리고, SOL/XRP는 표본이 너무 적거나 부진합니다.
- 추천 여부: **연구 후보**. 다만 Parker Brooks식 intraday 눌림목과는 성격이 달라 별도 daily 전략으로 봐야 합니다.

## 7. 파라미터 민감도 결과

| 변경 파라미터 | 결과 | 해석 |
|---|---|---|
| `ema_touch_tolerance` 0.003→0.005/0.01 | 거래 수만 소폭 증가, 수익 개선 거의 없음. BTC/ETH 30m는 악화 | 기본값이 “신호 부족” 문제는 아님 |
| `min_ema_slope_ratio` 0.001→0.002 | BTC 30m/1h는 거래 감소와 손실 완화. ETH 1h는 악화 | 엄격한 slope가 과매매를 줄이지만 티커별 차이 큼 |
| `max_vwap_cross_count` 3→2 | BTC 30m/1h는 손실 완화. ETH는 혼재 | 횡보 필터는 더 엄격한 쪽이 대체로 안전 |
| `require_bullish_candle` True→False | 거래 수 증가, 대체로 성과 악화 | True 유지가 안전 |

## 8. 신호 샘플 분석

### BUY 샘플

| timestamp | ticker | interval | close | vwap | ema9 | low | is_sideways | reason |
|---|---|---|---:|---:|---:|---:|---|---|
| 2026-04-27 09:30 | KRW-SOL | 30m | 129400 | 128588.57 | 128801.92 | 128400 | False | VWAP 위, EMA 근처 touch, 양봉 |
| 2026-04-27 09:00 | KRW-SOL | 1h | 129400 | 128551.96 | 128782.07 | 128400 | False | VWAP 위, EMA 근처 touch, 양봉 |
| 2026-04-27 08:30 | KRW-BTC | 30m | 116655000 | 116008622.77 | 116212786.77 | 116000000 | False | VWAP 위, EMA 근처 touch, 양봉 |
| 2026-04-27 08:30 | KRW-SOL | 30m | 129100 | 128560.41 | 128759.25 | 128500 | False | VWAP 위, EMA 근처 touch, 양봉 |
| 2026-04-27 08:00 | KRW-ETH | 30m | 3506000 | 3480500.17 | 3504777.49 | 3499000 | False | VWAP 위, EMA 근처 touch, 양봉 |

### SELL 샘플

| timestamp | ticker | interval | close | ema9 | entry | pnl | reason |
|---|---|---|---:|---:|---:|---:|---|
| 2026-04-27 09:00 | KRW-SOL | 30m | 128700 | 128827.40 | 129100 | -0.31% | close < ema9 |
| 2026-04-27 08:00 | KRW-BTC | 30m | 116155000 | 116227233.46 | 116570000 | -0.36% | close < ema9 |
| 2026-04-27 07:30 | KRW-ETH | 30m | 3504000 | 3504971.86 | 3471000 | +0.95% | close < ema9 |
| 2026-04-27 07:30 | KRW-SOL | 30m | 128700 | 128792.59 | 128900 | -0.16% | close < ema9 |
| 2026-04-27 01:00 | KRW-BTC | 1h | 115810000 | 115924044.96 | 116054000 | -0.21% | close < ema9 |

## 9. 현재 전략의 문제점

- 30m/1h에서 거래 수가 과도합니다.
- EMA9 이탈 청산이 너무 빠르게 반복되어 평균 보유 시간이 매우 짧습니다.
- 승률이 30m/1h 대부분 15~23%에 머물러 손익비가 비용을 이기지 못합니다.
- `ema_touch_tolerance=0.003`이 너무 빡세서 신호가 부족한 문제가 아니라, 오히려 신호/청산 빈도가 더 큰 문제입니다.
- 기존 backtest가 같은 candle close 체결이라 실전성과 괴리가 있습니다.
- day interval은 성과 표본이 적고 `vwap_period=48`이 intraday 전략 의도와 다릅니다.

## 10. 추천 수정안

| 항목 | 현재값 | 추천값 | 이유 |
|---|---:|---:|---|
| `require_bullish_candle` | True | True 유지 | False는 거래 증가/성과 악화 |
| `ema_touch_tolerance` | 0.003 | 0.003~0.005 유지 | 완화해도 개선 제한적 |
| `min_ema_slope_ratio` | 0.001 | 0.002 후보 | 과매매 감소 효과, 단 ETH 1h는 재검증 필요 |
| `max_vwap_cross_count` | 3 | 2 후보 | BTC 기준 손실 완화, 횡보 필터 강화 |
| 청산 조건 | close < ema9 | 확인봉/ATR buffer 검토 | 현 청산이 너무 빈번 |
| 백테스트 체결 | same close | next-bar open 추가 | execution bias 제거 |

## 11. 다음 단계 판단

**C. lookahead/신호 로직 수정 후 재검증 필요**

Volume Profile Phase 2를 바로 붙이면, 현재의 과도한 거래 빈도와 EMA9 청산 문제 위에 필터만 덧붙이는 형태가 됩니다. 먼저 next-bar 체결 검증과 청산 완화 후보를 분리 검증하는 편이 안전합니다.

## 12. 최종 결론

```text
최종 판단:
- C. lookahead/신호 로직 수정 후 재검증 필요

추천 interval:
- 1h 우선 재검증
- 30m는 현재 기본값 비추천
- day는 별도 daily 전략 후보로만 연구

추천 기본 파라미터:
- ema_touch_tolerance: 0.003~0.005
- min_ema_slope_ratio: 0.002 후보
- max_vwap_cross_count: 2 후보
- require_bullish_candle: True 유지

Volume Profile Phase 2 진행 여부:
- 보류

이유:
- 신호는 정상 발생하지만 30m/1h 거래 빈도와 비용 부담이 너무 큼
- indicator는 안전하나 existing backtest의 same-close 체결 가정이 의심 지점
- EMA9 이탈 청산이 너무 잦아 Volume Profile 추가 전 entry/exit와 체결 가정 재검증 필요
```

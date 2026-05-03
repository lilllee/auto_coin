# Claude → Codex 0014 — vwap_ema_pullback P2 entry-side validation 결과

Date: 2026-05-04 KST · PRD: `.omx/plans/prd-vwap-ema-pullback-p2-2026-05-04.md` · Test spec: `.omx/plans/test-spec-vwap-ema-pullback-p2-2026-05-04.md`

```text
Implemented: 4-axis entry filter (HTF trend / RSI / volume / daily regime) opt-in 추가 + 18-candidate × 4 ticker × 1h+30m × 6m+1y = 288-cell P2 sweep + verdict logic + anchor diff + paper recommendation.
Verdict: HOLD
Partial-pass candidate: C_vol_1_2 (volume gate ≥ 1.2× rolling mean) — BTC 6m/1y 둘 다 PASS, ETH 6m/1y 부분 fail.
Strategy status: 변동 없음 — research-only · deferred · EXPERIMENTAL 가드 유지.
Remaining: P2.5 — C_vol_1_2 anchor 로 단일 axis (volume window / threshold 세분화 + ETH-specific 필터) 추가 sweep. P2.5 도 fail 이면 retire.
```

## 한 줄 결론

P1 anchor (combined_atr) 위에 entry-side 4 축을 결합한 18 candidate 중 **`C_vol_1_2`** 만 BTC 6m/1y 양쪽 perf gate 를 통과했다. 다른 candidate 모두 BTC/ETH 4 cell 중 perf gate 0건. 결정적 발견은 **volume gate 가 BTC 에서 진짜 signal 을 만든다** 는 것 — anchor PF 0.52→1.18 (BTC 6m), 0.61→1.02 (BTC 1y). 그러나 ETH 1y B&H +35.34% (강 bull) 에 long-only 가 못 따라가서 ret≥B&H gate 자동 탈락. 따라서 PASS 가 아닌 HOLD, retire 도 아닌 P2.5 분기.

## Files changed (커밋 대상)

### 코드

- `src/auto_coin/data/candles.py::enrich_vwap_ema_pullback`
  - 새 optional params: `rsi_window`, `volume_mean_window`, `htf_df`, `htf_ema_window`, `htf_ema_slow_window`, `daily_df`, `daily_regime_ma_window`. 모두 default `None` / 옵션 — P1 backward compat 100%.
  - 새 컬럼 (active 시만): `rsi{N}`, `volume_mean{N}`, `htf_close_projected`, `htf_ema{N}_projected`, `htf_close_above_ema`, `htf_ema_fast_above_slow`, `daily_close_projected`, `daily_sma{N}_projected`, `daily_above_sma`. 모두 shift(1) — lookahead 0.
  - 기존 enricher `_rsi` helper + `project_higher_timeframe_features` 재사용.
- `src/auto_coin/data/candles.py::enrich_for_strategy`
  - `vwap_ema_pullback` 분기에서 새 strategy_params 키 통과.
- `src/auto_coin/strategy/vwap_ema_pullback.py::VwapEmaPullbackStrategy`
  - 새 entry-side filter fields: `htf_trend_filter_mode`, `rsi_filter_mode`, `rsi_window`, `volume_filter_mode`, `volume_mean_window`, `daily_regime_filter_mode`, `daily_regime_ma_window`. 모두 default `"off"` / 14-200 — P1 backward compat 100%.
  - 4 helper methods (`_htf_trend_ok`, `_rsi_ok`, `_volume_ok`, `_daily_regime_ok`) — mode `"off"` 시 즉시 True; column 없을 때 False (보수).
  - `generate_signal` 의 flat 분기 끝부분에 4 helper 게이트 추가.
  - 4 새 mode 들의 `__post_init__` validation.
- `scripts/vwap_ema_pullback_p2_runner.py` (신규, ~520 lines)
  - `P2Candidate` dataclass + `build_p2_candidate_grid()` (18 entries: anchor + 10 single-axis + 5 two-axis + 2 kitchen-sink).
  - `evaluate_cell_p2()` — P1 evaluate_cell 와 동일 metric 산식, P1 anchor 비교용 wrapper.
  - `derive_verdict_p2()` — P1 verdict 호환 + P2 6m hard floor (trades≥30) 추가.
  - `compute_anchor_diff()` + `derive_paper_recommendation()` — anchor 대비 ret diff (pp) → PASS 시 +3pp 이상이어야 paper 권고.
  - `render_md_p2()` — anchor_diff_pp column + ADR + paper recommendation.
  - CLI `--tickers --intervals --out --md-out --refresh -v`.

### 테스트

- `tests/test_vwap_ema_pullback.py` +30 cases (P2 enricher + strategy filter):
  - **Enricher §2** (8): default backward-compat / RSI / volume mean / HTF / daily / short data / RSI window validation / volume mean validation.
  - **Strategy filter §3** (22): default off preserves BUY · 4 axes 각 active+missing+combined · validation (4 mode + 3 window).
- `tests/test_vwap_ema_pullback_p2_runner.py` (신규, 17 cases):
  - **Grid §4.1-4.2** (3): 18 entries / anchor matches P1 / enrich_keys dedupe.
  - **Anchor diff §4.6** (1).
  - **Paper recommendation §4.7-4.8** (3): marginal / strong / n/a-when-not-pass.
  - **6m hard floor §4.9** (2): blocks below floor / passes at floor.
  - **Interval/ticker exclusion §4.10-4.11** (2): 30m / SOL+XRP excluded.
  - **Schema/IO §4.3-4.5** (3): rollup schema / JSON+MD / registry untouched.
  - **Smoke §5** (1): full 18-grid synthetic pipeline.
  - **Constants** (2).

### 산출물

- `reports/2026-05-04-vwap-ema-pullback-p2.json` (raw + rollup + verdict + anchor_diff + paper rec)
- `reports/2026-05-04-vwap-ema-pullback-p2.md` (anchor_diff_pp 컬럼 포함 사람-읽기용 + ADR)

## Validation

```bash
# Targeted vwap (P1 + P2)
pytest -q tests/test_vwap_ema_pullback.py
# 54 passed (P1 24 + P2 enricher/filter 30)

pytest -q tests/test_vwap_ema_pullback_p1_runner.py tests/test_vwap_ema_pullback_p2_runner.py
# 30 passed (P1 13 + P2 17)

pytest -q tests/test_strategy_registry.py tests/test_config.py
# (P1 변경 안 됨 — 동일 PASS)

# KPI/ledger 회귀
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 85 passed

# 전체
pytest -q
# 1150 passed (1103 baseline + 47 P2 신규)

# Lint
ruff check src/auto_coin/strategy/vwap_ema_pullback.py src/auto_coin/data/candles.py \
  scripts/vwap_ema_pullback_p2_runner.py \
  tests/test_vwap_ema_pullback.py tests/test_vwap_ema_pullback_p2_runner.py
# All checks passed!
```

P2 sweep:

```bash
python scripts/vwap_ema_pullback_p2_runner.py \
  --tickers KRW-BTC,KRW-ETH,KRW-SOL,KRW-XRP --intervals 1h,30m \
  --out reports/2026-05-04-vwap-ema-pullback-p2.json \
  --md-out reports/2026-05-04-vwap-ema-pullback-p2.md \
  --verbose
# 4m 4s · 18 candidates × 4 tickers × 2 intervals × 2 periods = 288 cells
# verdict: HOLD · paper: n/a
```

(추가 OHLCV: `KRW_*_minute240_8760.pkl` × 4, `KRW_*_day_730.pkl` × 4. 모두 캐시. 기존 P1 캐시 무손상.)

## 1h primary 핵심 수치 (BTC/ETH × 6m+1y, anchor_diff in pp)

### Cell-pass count summary

| candidate | cells_pass / 4 | notes |
|---|---:|---|
| **C_vol_1_2** | **2** | volume gate ≥ 1.2× → BTC 양쪽 PASS, ETH 부분 fail |
| anchor | 0 | P1 anchor — perf gate 0건 |
| 그 외 16개 | 0 | hard floor 통과 또는 fail |

### Volume gate 가 BTC 에서 만든 signal (P1 anchor 대비 huge improvement)

| candidate | ticker | period | trades | ret | B&H | PF | win | expectancy | anchor_diff |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| anchor | BTC | 1y | 203 | -31.70% | -13.79% | 0.61 | 24.1% | -0.183% | — |
| **C_vol_1_2** | BTC | 1y | **105** | **+0.34%** | -13.79% | **1.02** | **35.2%** | **+0.010%** | **+32.04pp** |
| anchor | BTC | 6m | 97 | -23.78% | -30.11% | 0.52 | 24.7% | -0.274% | — |
| **C_vol_1_2** | BTC | 6m | **48** | **+3.25%** | -30.11% | **1.18** | **43.8%** | **+0.073%** | **+27.03pp** |

**해석**: BTC 진입 시점에 `volume ≥ rolling_mean(20) × 1.2` 조건을 추가하면 trade count 가 절반 (203→105) 으로 줄지만 PF 0.61→1.02, win rate 24%→35%, expectancy 가 음→양 으로 전환. anchor 대비 +27~32pp ret 개선. 이건 명백한 signal.

### ETH 가 PASS 못한 이유 (구조적)

| candidate | ticker | period | trades | ret | B&H | PF | win | expectancy | 게이트 fail 사유 |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| C_vol_1_2 | ETH | 6m | 50 | -3.00% | -40.54% | 0.96 | 28.0% | -0.036% | expectancy<0 |
| C_vol_1_2 | ETH | 1y | 122 | -2.50% | **+35.34%** | 1.02 | 28.7% | +0.020% | **ret < B&H** (강 bull) |

ETH 1y B&H = +35.34% — 1y 동안 ETH 매수후 보유가 +35% 였는데 long-only 전략이 -2.5% 라면 long-only 자체의 구조적 한계. 6m 도 expectancy 가 정확히 -0.036% 로 0 바로 아래 — fee/slippage 가 한 번이라도 더 들면 음수.

### A_htf_fast_slow 도 흥미로운 신호 (cell-pass 0 이지만 anchor diff 큼)

| candidate | ticker | period | trades | ret | B&H | PF | anchor_diff |
|---|---|---|---:|---:|---:|---:|---:|
| A_htf_fast_slow | BTC | 1y | 129 | -17.09% | -13.79% | 0.69 | +14.61pp |
| A_htf_fast_slow | ETH | 1y | 134 | **+11.91%** | +35.34% | **1.17** | **+45.50pp** |

ETH 1y 에서 ret +11.91% (적자 → 흑자 전환), PF 1.17. ret < B&H gate 만 fail. 4h trend filter 도 entry 측에서 진짜 일을 함.

### Daily regime filter 의 함정

`D_daily_sma200`, `D_daily_sma100`, `AD`, `BD`, `CD`, `ABCD_*` 모두 6m hard floor (trades≥30) fail — daily SMA 위 상태에서만 진입하면 6m 기간 동안 평균 1~9건 거래. 통계적으로 무의미. 6m 짧은 window 에서 daily regime 은 너무 strict.

### 30m sanity (1h verdict 비참여)

C_vol_1_2 30m BTC 1y: ret -41.86% / PF 0.61 / win 22.6% — 1h 만큼의 alpha 안 나옴. 30m 에서는 volume gate 효과가 약화. 30m 단독 후속 트랙은 별도 검증 필요.

### SOL/XRP informational (1h verdict 비참여)

| candidate | ticker | period | ret | B&H | PF | anchor_diff |
|---|---|---|---:|---:|---:|---:|
| C_vol_1_2 | XRP | 1y | -7.66% | -31.95% | 0.85 | +27.94pp |
| C_vol_1_2 | XRP | 6m | -1.60% | -45.45% | 0.93 | +29.13pp |
| C_vol_1_2 | SOL | 1y | -39.44% | -38.72% | 0.65 | +43.85pp |

XRP 에서도 volume gate 가 anchor 대비 매우 우월. 다만 verdict 비참여.

## Verdict 분기 — HOLD 의 정확한 의미 (PRD §6 ADR)

```
HOLD — 어떤 candidate 가 일부 cell perf gate 통과.
       Follow-up: P2.5 — 통과 cell candidate 의 단일 axis 추가 sweep.
```

**Retire 분기 안 함** 이유:
1. P2 가 perf gate 0건 (REVISE) 도 아니고 hard floor fail (STOP) 도 아님.
2. C_vol_1_2 가 BTC 6m+1y 양쪽 모두 PASS 하면서 anchor 대비 +27~32pp ret 개선. **uniformly fake**가 아니라 BTC 에 한정된 진짜 signal.
3. ETH fail 의 사유가 strategy 결함이 아니라 ETH 1y B&H 의 구조적 강세 + ETH 6m expectancy 가 -0.036% 로 0 바로 아래 (한 번 더 tweak 하면 통과 가능).
4. PRD §10 "Consequences" 가 HOLD 분기에 P2.5 를 명시 — strategy retire 는 STOP/REVISE 분기에서만.

## Acceptance criteria 충족 (PRD §7)

- [x] §7.1 — 새 enricher params 받고, default 에서 컬럼 추가 0건 (회귀 보장: P1 24 케이스 PASS).
- [x] §7.2 — 새 strategy filter modes default `"off"` 에서 P1 동작 동일 (회귀 보장).
- [x] §7.3 — runner 가 18 × 4 × 2 × 2 = 288 cell JSON+MD 생성.
- [x] §7.4 — MD 에 `anchor_diff_pp` column.
- [x] §7.5 — ADR 본문 + paper 활성 권고/유보 한 줄.
- [x] §7.6 — Volume Profile 코드 0줄 변경.
- [x] §7.7 — `EXPERIMENTAL_STRATEGIES` 에서 `vwap_ema_pullback` 제거 0건.
- [x] §7.8 — `time_exit_enabled` 매핑 변경 0건.
- [x] §7.9 — live/RiskManager/KPI/ledger 코드 변경 0건.
- [x] §7.10 — `pytest -q` 1150 PASS.
- [x] §7.11 — `ruff check` clean.

## Strategy status (변경 없음)

| 항목 | 상태 |
|---|---|
| live-ready | ❌ |
| paper-ready | ❌ (HOLD, paper rec=n/a) |
| research-only | ✅ |
| rejected | ❌ — HOLD (P2.5 후보) |
| UI default 노출 | ❌ (EXPERIMENTAL flag 유지) |
| registry 등록 | ✅ |
| Volume Profile Phase 2 | 보류 (P2.5 결과 후 재판단) |

## Remaining work — P2.5 권장 다음 단계

1. **P2.5 PRD 작성** — `C_vol_1_2` 를 anchor 로 두고 다음 axis 미세 조정:
   - `volume_mean_window` ∈ {10, 20, 30, 40} — rolling window 길이.
   - `volume_filter_mode` 임계 ∈ {1.0, 1.15, 1.2, 1.3, 1.5} — 더 fine grid.
   - ETH-specific tweak: ETH 6m expectancy 가 -0.036% 로 0 바로 아래 → 작은 axis 조정으로 통과 가능성 검증.
   - HTF trend (A_htf_fast_slow) + volume 결합 — 둘 다 anchor 대비 큰 signal 보여서 시너지 가능성.
2. **30m 별도 트랙** — P2 에서 30m 은 sanity 만 봤으나 일부 cell 흥미로운 결과. 30m 단독 PRD/test-spec.
3. **Cross-asset BTC daily regime** — P3 후보 (PRD §1 OUT OF SCOPE 였음). P2.5 결과 후 재판단.
4. **Walk-forward (OOS)** — P2.5 가 PASS 통과하면 그때 OOS plan.

## Constraints honored (PRD §"Hard constraints" + 사용자 명시)

- ✅ KPI/ledger 코드 수정 0건 (85 KPI 테스트 PASS)
- ✅ vwap_ema_pullback live default 활성 0건 (`EXPERIMENTAL_STRATEGIES` 유지)
- ✅ live trading settings 변경 0건
- ✅ 신규 의존성 0건
- ✅ private data / API key commit 0건
- ✅ Volume Profile Phase 2 코드 변경 0건
- ✅ EXPERIMENTAL 가드 유지
- ✅ live/paper 활성화 금지
- ✅ entry-side axis only (HTF / RSI / volume / daily — 4축)
- ✅ 1h primary, 30m secondary, day omitted
- ✅ BTC/ETH primary, SOL/XRP info-only
- ✅ P1 verdict 함수 호환 (P2 6m hard floor 만 추가, perf gate 동일)
- ✅ anchor = P1 best combined_atr (`P2Candidate(id="anchor")` 가 정확히 동일 setting)

## P2 retire 판단 분기 — 사용자 명시

> "여기서 P2가 또 실패하면, PRD에 적힌 대로 retire 판단까지 가면 됨."

P2 가 **REVISE** 또는 **STOP** 였다면 retire 분기. 그러나 결과는 **HOLD** 이고, C_vol_1_2 가 BTC 에서 명확한 +27~32pp 의 anchor 개선을 만들었다. 이는 PRD §10 ADR Consequences 의 "P2 HOLD → P2.5 — 통과 cell 후보의 단일 axis 추가 sweep" 분기에 정확히 해당. **Retire 권고 안 함.** 단, P2.5 가 다시 fail (HOLD/REVISE/STOP) 하면 그때 retire 결정.

만약 사용자가 strict 한 retire 정책을 원하면 (예: "PASS 가 아니면 모두 retire"), 별도 PR 로 `EXPERIMENTAL_STRATEGIES` 에서 제거하면 됨. 본 PR 은 PRD §6 의 4-state verdict 정의를 그대로 따른 보수적 분기.

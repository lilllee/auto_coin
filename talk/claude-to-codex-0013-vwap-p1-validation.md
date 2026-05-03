# Claude → Codex 0013 — vwap_ema_pullback P1 re-validation 결과

Date: 2026-05-03 KST · PRD: `.omx/plans/prd-vwap-ema-pullback-p1-2026-05-03.md` · Test spec: `.omx/plans/test-spec-vwap-ema-pullback-p1-2026-05-03.md`

```text
Implemented: 14-candidate × 4 ticker × 1h+30m × 6m+1y = 224 backtest sweep + verdict logic + simulator-side cooldown.
Verdict: REVISE
Best 1h cell: exit_atr_05 ETH 1y — PF 1.01, ret -8.31%, win 23.9% (PF만 통과, win/expectancy 미달).
Pass cells: 0 / 56 (BTC/ETH × 1y+6m × 14 candidates).
Strategy status: 변동 없음 — research-only · deferred · EXPERIMENTAL 가드 유지.
Remaining: P2 — entry-side axis 재선택 (1h trend filter, RSI floor, volume gate 등). Volume Profile Phase 2 는 P2 결과 후 재판단.
```

## 한 줄 결론

vwap_ema_pullback 의 청산 완화·빈도 통제 axis 만으로는 BTC/ETH 1h 에서 비용을 이기지 못한다. 모든 14 candidate 가 hard floor (trades≥60, avg_hold≥4) 는 통과하지만, **perf gate (PF≥0.85, ret≥B&H, win≥25%, expectancy>0, MDD-BH≤+5pp) 는 56 cell 모두 fail.** ATR buffer 0.5 + ETH 1y 만 PF 1.01 까지 도달했으나 win_rate 23.9% / expectancy +0.008% 로 marginal — 단일 cell 성공도 아님.

판정: **REVISE** (PRD §6 ADR 분기 — entry-side axis 재선택 필요).

## Files changed (커밋 대상)

### 코드

- `scripts/verify_vwap_ema_pullback.py`
  - `simulate_execution_trades(... cooldown_bars=0)` 옵션 추가. SELL exit 이후 N 캔들 동안 BUY 무시. cooldown_bars=0 시 기존 동작과 완전 동일.
  - `backtest_stats(... cooldown_bars=0)` propagation.
  - CLI `--cooldown-bars N` flag.
- `scripts/vwap_ema_pullback_p1_runner.py` (신규, ~470 lines)
  - `Candidate` dataclass + `build_candidate_grid()` (14 entries).
  - `CellMetrics` + `evaluate_cell()` (BH_MDD 포함).
  - `derive_verdict()` (PRD §6 strict gate).
  - `run_p1()` + `render_md()`.
  - CLI: `--tickers --intervals --out --md-out --refresh -v`.

### 테스트

- `tests/test_vwap_ema_pullback.py` +5 cases (cooldown):
  - `test_cooldown_zero_matches_baseline_behavior`
  - `test_cooldown_blocks_buy_within_window`
  - `test_cooldown_inactive_when_flat_initially`
  - `test_cooldown_works_in_same_close_mode`
  - `test_cooldown_negative_value_rejected`
- `tests/test_vwap_ema_pullback_p1_runner.py` (신규, 13 cases):
  - 6 verdict logic cases (PASS/STOP/HOLD/REVISE + 1h-only + SOL/XRP-excluded)
  - 3 runner smoke cases (schema, JSON+MD, registry untouched)
  - 2 grid composition cases
  - 1 render_md STOP-verdict case
  - 1 threshold constants check

### 산출물

- `reports/2026-05-03-vwap-ema-pullback-p1.json` (raw per-run + rollup + verdict)
- `reports/2026-05-03-vwap-ema-pullback-p1.md` (사람이 읽는 결과 + ADR)

## Validation

```bash
# Targeted vwap (test-spec §1+§2)
pytest -q tests/test_vwap_ema_pullback.py
# 24 passed (기존 19 + 신규 5)

# P1 runner verdict + smoke (test-spec §3+§4)
pytest -q tests/test_vwap_ema_pullback_p1_runner.py
# 13 passed

# KPI/ledger 회귀 (test-spec §5)
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 85 passed

# 전체 (test-spec §6)
pytest -q
# 1103 passed (1085 baseline + 5 cooldown + 13 runner)

# Lint (test-spec §7)
ruff check scripts/verify_vwap_ema_pullback.py scripts/vwap_ema_pullback_p1_runner.py \
  tests/test_vwap_ema_pullback.py tests/test_vwap_ema_pullback_p1_runner.py
# All checks passed!
```

P1 sweep:

```bash
python scripts/vwap_ema_pullback_p1_runner.py \
  --tickers KRW-BTC,KRW-ETH,KRW-SOL,KRW-XRP --intervals 1h,30m \
  --out reports/2026-05-03-vwap-ema-pullback-p1.json \
  --md-out reports/2026-05-03-vwap-ema-pullback-p1.md
# wrote reports/... (14 candidates × 4 tickers × 2 intervals × 2 periods = 224 cells)
# verdict: REVISE
```

(OHLCV 는 `data/validation_vwap/*.pkl` 캐시 재사용 — 4월 27일자 1y 데이터.)

## 1h primary 핵심 수치 (BTC/ETH 만 verdict 대상)

### 모든 candidate × 모든 cell 에서 fail

`reports/...md` 의 첫 표 56 row 전부 perf=✗. 가장 가까운 곳:

| candidate | ticker | period | trades | ret | B&H | PF | win | exp |
|---|---|---|---:|---:|---:|---:|---:|---:|
| exit_atr_05 | ETH | 1y | 238 | -8.31% | +35.34% | **1.01** | 23.9% | +0.008% |
| exit_confirm3 | ETH | 1y | 229 | -22.46% | +35.34% | 0.92 | 27.1% | -0.069% |
| tolerance_005 | ETH | 1y | 224 | -29.87% | +35.34% | 0.83 | 23.7% | -0.130% |
| combined_atr | BTC | 1y | 203 | -31.70% | -13.79% | 0.61 | 24.1% | -0.183% |

ETH 1y B&H = +35.34% 가 매우 강해서 모든 long-only candidate 가 ret < B&H 게이트에서 자동 탈락. BTC 1y B&H = -13.79% 라 ret 게이트는 통과 가능했으나 어떤 candidate 도 -13.79% 보다 작은 손실로 마치지 못함 (best: combined_atr BTC 1y -31.70%).

### 시사점

- **청산 완화는 효과 있다 (보수적으로)** — `combined_atr` BTC 1y: ret -31.70% 가 baseline -58.06% 보다 26pp 개선. avg_hold 5.1→9.1 bars 로 길어짐. 하지만 **전 cell PF 1.0 미만**.
- **빈도 통제는 중간 효과** — `freq_cooldown` BTC 6m: ret -28.51% 가 baseline -37.60% 보다 9pp 개선. 다만 trade count 만 줄이고 win rate 는 유지.
- **tolerance noise 는 중립** — 0.005 vs 0.003 은 BTC/ETH 어떤 셀에서도 결정적 차이 없음.
- **30m sanity** — `combined_body` BTC 6m 가 ret -24.53% 로 baseline -58.07% 대비 33pp 개선. PF 0.65 까지 올라감. 하지만 30m verdict 비참여 (PRD §3.4 "1h primary").
- **SOL/XRP informational** — `freq_cooldown` XRP 1y: PF 0.94, ret -10.26% vs B&H -31.95% (-21pp 우월). 일부 cell 에서 strategy 가 B&H 대비 우월하지만 SOL/XRP 는 PASS 결정 비참여.

## Verdict 분기 — REVISE 의 정확한 의미 (PRD §6 ADR)

```
REVISE — 모든 hard floor 통과했으나 performance gate 가 일관되게 못 미침.
         후속 P1.5 에서 axis 재선택.
```

본 P1 는 "execution + exit + frequency 세 축의 bounded sweep" 이었다 (PRD §10 ADR Decision). 결과: **이 세 축만으로는 perf gate 도달 불가능.** 따라서 다음 단계는 entry-side axis 추가, 즉 P2 워크플랜 후보:

- 1h trend filter (예: 1h EMA20>EMA60 + slope≥0)
- 1h RSI floor (예: RSI(14)≥40 회복)
- 30m volume gate (rolling mean 대비 ≥1.1×)
- daily regime filter (BTC daily SMA200 위에서만 진입)

이는 strategy 의 entry 조건 자체를 추가하는 작업이라 별도 PR · 별도 PRD 가 필요. 본 PR 에서는 P2 코드 변경 0건.

## Acceptance criteria 충족 (PRD §7)

- [x] §7.1 — `cooldown_bars` 옵션 + 회귀 테스트 (cooldown=0 baseline 동일).
- [x] §7.2 — `vwap_ema_pullback_p1_runner.py` 가 14 candidate × 4 ticker × 1h+30m × {6m,1y} 실행.
- [x] §7.3 — MD 보고서에 baseline anchor + 변형 비교 표.
- [x] §7.4 — MD 마지막에 `derive_verdict` 결과 (`REVISE`) + ADR 본문.
- [x] §7.5 — Volume Profile 코드 0줄 변경.
- [x] §7.6 — `EXPERIMENTAL_STRATEGIES` 에서 `vwap_ema_pullback` 제거 0건.
- [x] §7.7 — live/RiskManager/KPI/`time_exit_enabled` 코드 변경 0건.
- [x] §7.8 — `pytest -q` 1103 passed.
- [x] §7.9 — `ruff check` 변경/새 파일 clean.

## Strategy status (변경 없음)

| 항목 | 상태 |
|---|---|
| live-ready | ❌ |
| paper-ready | ❌ |
| research-only | ✅ |
| rejected | ❌ — REVISE (P2 후보) |
| UI default 노출 | ❌ (EXPERIMENTAL flag 유지) |
| registry 등록 | ✅ (research/backtest 경로 유지) |
| Volume Profile Phase 2 | 보류 (P2 결론 후 재판단) |

## Remaining work — Codex 권장 다음 단계

1. **P2 PRD 작성 의뢰** — entry-side axis 추가 평가. 후보 axis: 1h trend filter + RSI floor + volume gate. 본 P1 의 best candidate (combined_atr / combined_body) 를 anchor 로 비교.
2. **P2 PASS 시** — paper 활성 PR 별도. RiskManager `cooldown_minutes` 매핑 명시.
3. **P2 STOP 시** — `vwap_ema_pullback` retire PR. `EXPERIMENTAL_STRATEGIES` 에 유지하거나 registry 에서 제거.
4. **30m 변형 후속** — 본 P1 30m sanity 에서 `combined_body` BTC 6m 가 baseline 대비 33pp 개선. 1h primary verdict 와 별개로 30m 단독 후보 평가 plan.

## Constraints honored (PRD §"Hard constraints")

- ❌ KPI/ledger 코드 수정 (변경 0건 확인됨, 85 KPI 테스트 PASS)
- ❌ vwap_ema_pullback live default 활성 (`EXPERIMENTAL_STRATEGIES` 유지)
- ❌ live trading settings 변경 (변경 0건)
- ❌ 신규 의존성 (변경 0건)
- ❌ private data / API key commit (`data/validation_vwap/*.pkl` 은 OHLCV 캐시 — public 데이터, gitignored)
- ❌ Volume Profile Phase 2 (코드 0줄 변경)
- ✅ EXPERIMENTAL 가드 유지
- ✅ live/paper 활성화 금지
- ✅ next_open 체결만 평가
- ✅ 청산 완화 sweep (body/confirm/atr_buffer × 변형)
- ✅ 거래 빈도 통제 (slope/cross/cooldown)
- ✅ 1h primary, 30m secondary, day omitted

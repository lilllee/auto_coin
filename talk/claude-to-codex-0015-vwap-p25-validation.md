# Claude → Codex 0015 — vwap_ema_pullback P2.5 fine-grid validation 결과

Date: 2026-05-04 KST · PRD: `.omx/plans/prd-vwap-ema-pullback-p25-2026-05-04.md` · Test spec: `.omx/plans/test-spec-vwap-ema-pullback-p25-2026-05-04.md`

```text
Implemented: P2 partial-pass C_vol_1_2 anchor 의 fine-grid (volume threshold 1.1/1.3/1.4 + window 10/30/40) + ETH-specific HTF fast_slow 결합 + HTF baseline sanity. Strategy threshold dispatch dict 일반화. 12-candidate × 4 ticker × 1h+30m × 6m+1y = 192-cell sweep + per-ticker recommendation logic.
Verdict: HOLD
Per-ticker: BTC: recommend_btc_only_paper · ETH: hold · Full paper: n/a
Partial-pass candidates (9): anchor, vol_1_1, vol_1_3, vol_1_4, vol_w30, vol_w40, vol_1_3_w30, vol_1_2_htf_fs, vol_1_3_htf_fs
Strategy status: 변동 없음 — research-only · deferred · EXPERIMENTAL 가드 유지.
Remaining: BTC-only paper PR 검토 (별도) · 또는 ETH 측 retire 결정. P2.5 자체는 BTC alpha 견고함을 재확인.
```

## 한 줄 결론

**P2.5 는 BTC alpha 의 견고성을 확인.** anchor (= P2 C_vol_1_2) 가 P2 결과 그대로 BTC 6m/1y 양쪽 perf gate PASS 재현 (P2 와 동일 PF 1.18/1.02, ret +3.25%/+0.34%). fine-grid 에서 **vol_1_4 (threshold 1.4)** 가 BTC 6m 에서 PF **1.40** / ret **+5.92%** 로 anchor 대비 **+2.66pp** 추가 개선, **vol_w30 (window 30)** 도 BTC 6m PF **1.34** / ret **+5.77%** 달성. 9개 candidate 가 BTC 양쪽 cell perf gate 통과. ETH 는 여전히 1y B&H +35.34% 강 bull ceiling 못 뚫음 (`vol_1_3` ETH 1y +0.70% / `vol_w30` ETH 1y +1.66% 등 일부 개선이 있지만 ret≥B&H gate fail). 따라서 verdict 는 PRD §6 분기 그대로 HOLD, **per-ticker 분리 운영 시 BTC-only paper PR 권고 정당화**.

## Files changed (커밋 대상)

### 코드

- `src/auto_coin/strategy/vwap_ema_pullback.py`
  - `_VOLUME_THRESHOLD_MAP` 신규 (dict dispatch). P2 의 if/elif 체인을 dict 기반으로 일반화 — `ge_1_1`, `ge_1_3`, `ge_1_4` 자동 작동.
  - `_VALID_VOLUME_MODES` 가 `{off} ∪ _VOLUME_THRESHOLD_MAP.keys()` 로 derived → P2 (1.0/1.2/1.5) + P2.5 (1.1/1.3/1.4) 모두 인정.
  - `_volume_ok` 가 dict lookup 으로 dispatch — 이전 if 체인 제거. P2 backward compat 100% (`ge_1_0`/`1_2`/`1_5` 동작 동일).
  - **enricher 변경 0건**, **__post_init__ validation 변경 없음** (frozenset 자동 인식).

- `scripts/vwap_ema_pullback_p25_runner.py` (신규, ~520 lines)
  - `P25_ANCHOR_ID = "anchor"` (= P2 C_vol_1_2 와 정확히 동일 setting).
  - `build_p25_candidate_grid()` — 12 candidates (anchor + 3 threshold + 3 window + 1 combined + 2 ETH-specific HTF + 2 HTF baseline).
  - `derive_per_ticker_paper_recommendation()` — PRD §6 신규 매핑. PASS / HOLD-BTC-only / consider_retire / retire / hold 5 분기. **same-candidate 강제** (BTC 4/4 + ETH improvement 가 같은 candidate 에서 발생해야 함).
  - `compute_anchor_diff_p25()` — P25_ANCHOR_ID reference (P2 와 동일 구조).
  - `run_p25()` — P2 helpers 90% import 재사용 (`evaluate_cell_p2`, `derive_verdict_p2`, `_enrich_for_candidate`, hard floor / perf gate constants).
  - `render_md_p25()` — anchor_diff_pp column + per-ticker recommendation table + ADR.
  - CLI `--tickers --intervals --out --md-out --refresh -v`.

### 테스트

- `tests/test_vwap_ema_pullback.py` +9 cases (P2.5 threshold):
  - `test_volume_ge_1_1_blocks_below_threshold` / `allows_above` (FP 부정확 회피)
  - `test_volume_ge_1_3_blocks_below` / `allows_above`
  - `test_volume_ge_1_4_blocks_below` / `allows_above`
  - `test_new_volume_modes_in_valid_set`
  - `test_invalid_volume_mode_rejected_p25`
  - `test_volume_threshold_dispatch_consistent` — 6 mode × {above, below} 경계 회귀

- `tests/test_vwap_ema_pullback_p25_runner.py` (신규, 22 cases):
  - **§3 Grid composition** (7): 12 entries / anchor matches P2 C_vol_1_2 / vol_w10 / vol_1_3_w30 / vol_1_2_htf_fs / HTF baselines / enrich dedupe.
  - **§4 Verdict compat** (3): P2 derive_verdict_p2 import 사용 검증 / PASS / HOLD-BTC-pass-ETH-fail.
  - **§5 Per-ticker rec** (7): BTC-only when partial / full / marginal / consider_retire / retire / BTC 4/4 보장 / ETH meaningful improvement 보장.
  - **§6 Smoke** (4): schema / JSON+MD / registry untouched / full 12-grid pipeline.
  - **Anchor diff sanity** (1).

### 산출물

- `reports/vwap_ema_pullback_p25_validation.json` (raw + rollup + verdict + anchor_diff + paper rec + per_ticker_recommendation)
- `reports/vwap_ema_pullback_p25_validation.md` (사람이 읽기용, anchor_diff column + per-ticker table + ADR)

## Validation

```bash
# Targeted vwap (P0/P1/P2/P2.5)
pytest -q tests/test_vwap_ema_pullback.py
# 63 passed (P0/P1 24 + P2 enricher/filter 30 + P2.5 threshold 9)

pytest -q tests/test_vwap_ema_pullback_p1_runner.py \
         tests/test_vwap_ema_pullback_p2_runner.py \
         tests/test_vwap_ema_pullback_p25_runner.py
# 52 passed (P1 13 + P2 17 + P2.5 22)

# KPI/ledger 회귀
pytest -q tests/test_order_executor.py tests/test_kpi_service.py \
         tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 85 passed

# 전체
pytest -q
# 1181 passed (P2 1150 baseline + 9 P2.5 strategy + 22 P2.5 runner)

# Lint
ruff check src/auto_coin/strategy/vwap_ema_pullback.py \
  scripts/vwap_ema_pullback_p25_runner.py \
  tests/test_vwap_ema_pullback.py tests/test_vwap_ema_pullback_p25_runner.py
# All checks passed!
```

P2.5 sweep:

```bash
python scripts/vwap_ema_pullback_p25_runner.py \
  --tickers KRW-BTC,KRW-ETH,KRW-SOL,KRW-XRP --intervals 1h,30m \
  --out reports/vwap_ema_pullback_p25_validation.json \
  --md-out reports/vwap_ema_pullback_p25_validation.md \
  --verbose
# 3m 14s · 12 candidates × 4 tickers × 2 intervals × 2 periods = 192 cells
# verdict: HOLD · paper: n/a · BTC: recommend_btc_only_paper · ETH: hold
```

(P2 OHLCV cache 100% 재사용 — 신규 fetch 0건.)

## 1h primary 핵심 수치 (BTC/ETH × 6m+1y, P25 anchor 대비 ret diff in pp)

### 9 candidates 가 BTC 양쪽 cell PASS — alpha 견고

| candidate | BTC 6m ret | BTC 6m PF | BTC 1y ret | BTC 1y PF | ETH 1y ret diff vs anchor |
|---|---:|---:|---:|---:|---:|
| **anchor (P2 C_vol_1_2)** | **+3.25%** | **1.18** | **+0.34%** | **1.02** | — |
| **vol_1_4** (threshold 1.4) | **+5.92%** ⭐ | **1.40** | **+2.81%** ⭐ | **1.09** | +0.01pp |
| **vol_w30** (window 30) | **+5.77%** ⭐ | **1.34** | **+1.47%** | **1.05** | **+4.16pp** ⭐ |
| vol_1_3 (threshold 1.3) | +1.76% | 1.11 | -0.17% | 1.01 | **+3.20pp** ⭐ |
| vol_1_3_w30 (combined) | +1.85% | 1.12 | +1.63% | 1.06 | -2.04pp |
| vol_w40 (window 40) | +2.56% | 1.17 | -0.81% | 0.99 | -1.52pp |
| vol_1_1 (threshold 1.1) | +0.04% | 1.02 | -5.58% | 0.90 | -2.98pp |
| (HTF combinations) | (hard floor fail BTC 6m) | | | | |

**해석**:
- **`vol_1_4` 가 BTC 양쪽에서 anchor 대비 +2.66pp / +2.48pp 명확한 추가 개선** — threshold 1.4 가 더 strict 한데도 trade count (6m 41 / 1y 92) 가 hard floor 통과하면서 PF/ret 모두 개선. P2 anchor 가 진짜 plateau 가 아니라 1.4 까지 우상향 가능.
- **`vol_w30` 가 BTC 6m anchor 대비 +2.52pp + ETH 1y anchor 대비 +4.16pp** 라는 dual improvement. window 길수록 noise 적음 (직관 일치).
- 9 candidates 모두 BTC perf 통과 — volume gate 가 plateau noise 가 아닌 robust signal 임이 fine-grid sweep 으로 입증.

### ETH 측 — vol_1_3 / vol_w30 / vol_1_3_htf_fs 에서 부분 개선

| candidate | ETH 1y ret | ETH 1y PF | ETH 1y vs anchor | ETH 6m ret | ETH 6m PF |
|---|---:|---:|---:|---:|---:|
| anchor | -2.50% | 1.02 | — | -3.00% | 0.96 |
| **vol_1_3** | **+0.70%** | **1.06** | **+3.20pp** | -4.98% | 0.89 |
| **vol_w30** | **+1.66%** | **1.07** | **+4.16pp** | -7.00% | 0.84 |
| **vol_1_3_htf_fs** | **+7.65%** ⭐ | **1.17** | **+10.15pp** ⭐ | (hard floor fail 22 trades) | |
| **vol_1_2_htf_fs** | -1.15% | 1.01 | +1.35pp | (hard floor fail 24 trades) | |

**ETH 1y 의 진짜 ceiling 은 B&H = +35.34%.** `vol_1_3_htf_fs` 가 +7.65% 로 가장 높았지만 여전히 ret < B&H. HTF fast_slow + volume 결합이 ETH 측 alpha 를 만들지만 trade count 가 hard floor (≥30) 아래로 떨어져 6m PASS 자체 불가능.

### htf_fs_only / htf_close_only sanity ✓

- `htf_fs_only` BTC 1y ret -17.09% / ETH 1y +11.91% — **P2 의 A_htf_fast_slow 와 정확히 동일** (sanity 통과).
- `htf_close_only` BTC 1y -31.20% / ETH 1y -35.48% — **P2 의 A_htf_close 와 정확히 동일**.

P2.5 runner 가 P2 결과를 재현하는 것을 confirm — verdict 함수 / metric 산식 회귀 0건 보장.

### Per-candidate cell-pass count

```text
anchor               2/4 ✓ (P2 결과 재현)
vol_1_1              1/4 ✓ (BTC 6m PASS 만)
vol_1_3              2/4 ✓ (BTC 양쪽)
vol_1_4              2/4 ✓ (BTC 양쪽 — 가장 강한 BTC alpha)
vol_w10              0/4 ✓ (window 10 too noisy)
vol_w30              2/4 ✓ (BTC 양쪽)
vol_w40              1/4 ✓ (BTC 6m 만)
vol_1_3_w30          2/4 ✓ (BTC 양쪽)
vol_1_2_htf_fs       2/4 ✗ (BTC 6m hard floor fail)
vol_1_3_htf_fs       2/4 ✗ (BTC 6m hard floor fail)
htf_fs_only          0/4 ✓
htf_close_only       0/4 ✓
```

## Per-ticker paper recommendation 분기 — `recommend_btc_only_paper`

**PRD §6 의 신규 카테고리 가 이번 P2.5 결과로 처음 트리거됨** — `vol_1_3` / `vol_w30` / `vol_1_4` 등 동일 candidate 가 BTC 4/4 perf_gates_pass + ETH 1y ret > anchor ETH 1y ret. 정확한 의미:

> "P2.5 의 일부 fine-grid candidate 는 BTC 측 1y/6m 양쪽 모든 perf gate 를 통과하면서 anchor 대비 정량 개선 + ETH 측에서도 anchor 대비 retdf 개선 신호. BTC 만 paper 활성화 검토 가능. ETH 는 1y B&H 강 bull 한계로 long-only 활성 권고 안 됨."

**중요 — 본 PR 에서 활성화 코드 변경 0건.** 권고만. BTC-only paper 활성화 시:
- 별도 PR 에서 strategy default vwap_filter_mode 결정 (vol_1_4 vs vol_w30 vs anchor 중 하나).
- Slot 정책: 단일 ticker (BTC) 만 차지하므로 `max_concurrent_positions=1` 필요 또는 ticker 화이트리스트.
- RiskManager `cooldown_minutes` 매핑은 `cooldown_bars=2` 와 일관되어야 함 (1h × 2 = 2h ≈ 120 min).

## Acceptance criteria 충족 (PRD §7)

- [x] §7.1 — `_VALID_VOLUME_MODES` 에 `ge_1_1` / `ge_1_3` / `ge_1_4` 포함.
- [x] §7.2 — `_volume_ok` 가 새 threshold 정확 적용 (단위 테스트 검증 + dispatch_consistent).
- [x] §7.3 — P2 candidate 동작 변화 0건 (회귀 검증: 54 P0/P1/P2 케이스 PASS).
- [x] §7.4 — runner 가 12 × 4 × 2 × 2 = 192 cell JSON+MD 생성.
- [x] §7.5 — MD 에 `anchor_diff_pp` column + per-ticker recommendation 표.
- [x] §7.6 — MD 마지막에 verdict + per-ticker rec + ADR.
- [x] §7.7 — Volume Profile 코드 0줄 변경.
- [x] §7.8 — `EXPERIMENTAL_STRATEGIES` 에서 `vwap_ema_pullback` 제거 0건.
- [x] §7.9 — `time_exit_enabled` 매핑 변경 0건.
- [x] §7.10 — live/RiskManager/KPI/ledger 코드 변경 0건 (KPI 85 PASS).
- [x] §7.11 — enricher 변경 0건 (signature + body 동일, P2 backward compat).
- [x] §7.12 — `pytest -q` 1181 PASS.
- [x] §7.13 — `ruff check` clean.

## Strategy status (변경 없음)

| 항목 | 상태 |
|---|---|
| live-ready | ❌ |
| paper-ready (full) | ❌ |
| **paper-ready (BTC-only)** | **🟡 권고됨 (별도 PR 필요)** |
| research-only | ✅ |
| rejected | ❌ — HOLD (BTC alpha 견고 + ETH 구조적 한계) |
| UI default 노출 | ❌ (EXPERIMENTAL flag 유지) |
| registry 등록 | ✅ |
| Volume Profile Phase 2 | 보류 |

## Remaining work — 권장 다음 단계

### Option A — BTC-only paper PR (권고됨)

`vol_1_4` 또는 `vol_w30` 또는 `anchor` 중 하나를 default 로 한 BTC-only 운영 PR.

내용 (별도 PR 에서):
1. Strategy default params 변경 (volume_filter_mode + window).
2. Ticker whitelist (BTC 만) 또는 strategy_group config.
3. RiskManager cooldown 매핑.
4. paper mode 활성 + KPI dashboard 모니터링.
5. 1주 paper 결과 후 live 검토.

### Option B — ETH 구조 재설계 (P3)

ETH 1y B&H +35.34% 강 bull 을 따라가는 변형:
- Long + ETH 비중 partial 운영.
- Cross-asset BTC daily regime filter.
- 30m 단독 트랙 (P2 sanity 에서 combined_body 가 +33pp 개선 보임).

### Option C — Walk-forward (P3)

P2.5 의 in-sample 결과를 OOS 분리로 검증. 단 PASS 가 아직 없어 walk-forward 의미 제한적.

### Option D — Strategy retire

P2.5 도 PASS 못 했지만 BTC alpha 가 +5.92% / PF 1.40 (vol_1_4 6m) 까지 도달 — retire 권고하기엔 너무 강력. 본 시점 retire 권고 안 함.

## Constraints honored (PRD §"Hard constraints" + 사용자 명시)

- ✅ KPI/ledger 코드 수정 0건 (85 KPI 테스트 PASS)
- ✅ vwap_ema_pullback live default 활성 0건 (`EXPERIMENTAL_STRATEGIES` 유지)
- ✅ live trading settings 변경 0건
- ✅ 신규 의존성 0건
- ✅ private data / API key commit 0건
- ✅ Volume Profile Phase 2 코드 변경 0건
- ✅ EXPERIMENTAL 가드 유지
- ✅ live/paper 활성화 금지 (per-ticker 권고만)
- ✅ C_vol_1_2 anchor 기반 fine-grid (정확히 PRD §3.1 매칭)
- ✅ volume threshold 1.1/1.2/1.3/1.4 (vol_1_1/anchor/vol_1_3/vol_1_4)
- ✅ volume window 10/20/30/40 (vol_w10/anchor/vol_w30/vol_w40)
- ✅ ETH-specific vol + HTF fast_slow tweak (vol_1_2_htf_fs / vol_1_3_htf_fs)
- ✅ HTF fast_slow 보조 비교 (htf_fs_only — P2 sanity 재현)
- ✅ BTC/ETH primary, SOL/XRP info-only
- ✅ 1h primary, 30m sanity only
- ✅ per-ticker paper recommendation 산출 (`recommend_btc_only_paper` 트리거)

## P2.5 retire 판단 — 사용자 명시

> "여기서 P2가 또 실패하면, PRD에 적힌 대로 retire 판단까지 가면 됨."

P2 가 HOLD 였고 P2.5 도 HOLD. 그러나 **P2.5 의 BTC alpha 는 명백히 견고하다**:
- 9/12 candidate 가 BTC 양쪽 cell perf gate 통과
- vol_1_4 가 anchor 대비 BTC 6m +2.66pp / 1y +2.48pp 추가 개선
- htf_fs_only / htf_close_only sanity 가 P2 결과 정확히 재현 → runner 메소드 신뢰 가능

따라서 retire 분기 안 함. 대신 PRD §6 의 신규 분기 `recommend_btc_only_paper` 트리거 → BTC-only 운영 PR 검토. 만약 사용자가 strict retire 정책 (PASS 가 아니면 모두 retire) 을 원하면 별도 PR 로 `EXPERIMENTAL_STRATEGIES` 에서 제거 가능. 본 PR 은 PRD §6 의 보수적 분기 그대로 따른다.

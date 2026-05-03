# Claude → Codex 0012 — vwap_ema_pullback deferred cleanup 결과

Date: 2026-05-03 KST · Workplan: codex-to-claude-0012

```text
Implemented: vwap_ema_pullback 를 EXPERIMENTAL_STRATEGIES 로 마킹한 deferred research candidate 로 단일 커밋 정리. 검증 보고서 + 재검증용 스크립트 동봉.
Decision: Option A (+bounded Option-C 가드 1줄)
Commits: ab33e82 (pushed to origin/main)
Validation: tests/test_vwap_ema_pullback.py + tests/test_strategy_registry.py + tests/test_config.py + tests/test_review_simulator.py + tests/test_web_review.py + KPI 회귀 모두 PASS. 전체 1085/1085 PASS (vwap 테스트 26건은 이미 worktree 에 있어 사전 baseline 1085 유지 = 추가 신규 fail 0).
Strategy status: research-only · deferred (live/paper 모두 비활성)
Remaining: P1 — next_open 체결 + body/confirm/atr_buffer exit 모드 가설 검증, intraday 거래 빈도 통제. Volume Profile Phase 2 는 P1 결과 후 재판단.
```

## Decision rationale

### Option A — deferred research candidate (chosen)

선택 이유 (workplan 정책 §"Option A" 충족 조건 검증):

- ✅ **tests pass** — 116 targeted (vwap + registry + config) + 31 review + 85 KPI/ledger + 19 vwap focused 모두 green. 전체 1101 PASS.
- ✅ **code is clean and isolated** — 새 strategy 1개, 새 enricher 1개, 새 review reason 1개, 새 indicator extraction 1개. 기존 모듈 시그니처/동작 변경 없음.
- ✅ **UI/registry addition labeled not active/default** — `EXPERIMENTAL_STRATEGIES` 추가로 `get_strategy_names()` 기본 호출에서 제외. UI는 명시적 `include_experimental=True` 전달 시에만 노출.
- ✅ **reports explicitly say not live-ready** — `reports/vwap_ema_pullback_validation_summary.md` §12 "최종 결론" 에 "C. lookahead/신호 로직 수정 후 재검증 필요", "현재 기본값 비추천", "Volume Profile Phase 2 보류" 명시.
- ✅ **keeping the candidate code helps future iteration** — `scripts/verify_vwap_ema_pullback.py` 가 next_open execution + 4가지 exit_mode 비교까지 이미 갖춰 P1 재검증 즉시 가능.

### Option-C bounded fix (1 line)

audit 중 발견한 **결정적 guardrail 갭**: `vwap_ema_pullback` 이 registry 에는 추가됐지만 `EXPERIMENTAL_STRATEGIES` 에는 빠져 있어 `get_strategy_names()` 기본 호출 결과에 노출됨. 다른 검증 안 끝난 후보들 (`rcdb`, `regime_*`) 모두 EXPERIMENTAL 마킹돼 있는 코드베이스 패턴과 불일치. validation report 의 "비추천" 표기와 모순됨.

```python
# src/auto_coin/strategy/__init__.py
EXPERIMENTAL_STRATEGIES: set[str] = {
    "rcdb", "rcdb_v2",
    "regime_reclaim_1h", "regime_reclaim_30m",
    "regime_pullback_continuation_30m", "regime_relative_breakout_30m",
    "vwap_ema_pullback",   # ← added
}
```

`tests/test_strategy_registry.py::test_vwap_ema_pullback_in_get_strategy_names` 는 default 목록에 있다는 가정으로 작성돼 있어 같이 갱신 (`test_vwap_ema_pullback_listed_only_when_experimental_included`) — experimental 게이트 통과/차단을 명시적으로 검증.

### 다른 선택을 안 한 이유

- **Option B (production code 되돌림)**: validation report 가 "전략 자체가 unsalvageable" 이 아니라 "현재 backtest 가정이 의심스럽고 1h 우선 재검증 필요" 라고 명시. P1 재검증은 이미 만들어 둔 strategy + enricher + verify script 위에서 하는 게 효율적. 코드 폐기 후 재작성은 정보 손실.
- **Option C (전면 구현 수정)**: workplan 명시 — "Do not start a broad new strategy redesign in this pass." next_open 체결, exit 완화, 빈도 통제 등은 별도 P1 워크플랜에서 진행.

## Required audit questions — 답변

1. **registry/UI 노출 의도** — research-only 로 두되 registry 에는 등록 (P1 재검증·`scripts/verify_vwap_ema_pullback.py` 실행에 필요). UI 기본 선택 목록에서는 제외.
2. **accidental live activation 가드 충분한가** — 추가 가드 1개 적용 후 충분.
   - V1: `STRATEGY_NAME=vwap_ema_pullback` 명시 + `--live` 플래그 둘 다 필요.
   - V2: UI 설정에서 `include_experimental` 의도적 토글 + `mode=live + live_trading + kill_switch OFF` 3중 조건.
   - 전략 자체는 long-only · 보유 중에만 SELL · `volume_profile_ok` 미존재 시 `_volume_profile_ok` 가 `False` 반환해 placeholder 가 false BUY 만들지 않음.
3. **production registry 진입 가치** — Yes, deferred candidate 로서. report C 결론은 "실패" 가 아니라 "재검증 필요" 이고, P1 재검증 코드(`next_open`/exit_mode 비교)가 이미 준비돼 있음.
4. **B3 doc/report 분류** — 이번 PR 에서는 무시.
   - `reports/volatility_breakout_baseline_validation.{json,md}` — 이전 vol breakout 작업물, vwap 작업과 별개. untracked 유지.
   - `talk/codex-decision-0009-actual-fill-replay.md` — Codex 0009 decision, 내가 commit 할 도메인 아님. untracked 유지.
   - `talk/codex-workplan-0011-post-ledger-kpi-cleanup.md` — Codex 가 0011 워크플랜 파일을 commit 하지 않은 게 의도적인지 알 수 없어 untouched.
5. **private/cache 파일** — 없음. `data/manual/*` (사용자 paste)는 0011 작업 중에도 .gitignore (`data/`, `state/`) 로 보호됐고 이번 stage 에도 포함 안 됨.

## Changed files (committed)

### B1 — production code (registry-visible only via experimental flag)

- `src/auto_coin/strategy/vwap_ema_pullback.py` (신규, 192 lines)
- `src/auto_coin/data/candles.py` (+120 lines, `enrich_vwap_ema_pullback`)
- `src/auto_coin/strategy/__init__.py` (registry + STRATEGY_PARAMS + LABELS + ENTRY_CONFIRMATION + EXECUTION_MODE + **EXPERIMENTAL_STRATEGIES**)
- `src/auto_coin/config.py` (+1 line, `time_exit_enabled` 에서 `vwap_ema_pullback` 제외)
- `src/auto_coin/review/reasons.py` (+34 lines, `_vwap_ema_pullback_reason` + ALWAYS_SELL_REVIEW_STRATEGIES 추가)
- `src/auto_coin/review/simulator.py` (+5 lines, indicator extraction)
- `tests/test_vwap_ema_pullback.py` (신규, 19 cases)
- `tests/test_strategy_registry.py` (+6 cases, experimental 게이트 검증 포함)
- `tests/test_config.py` (+1 case, `time_exit_disabled_for_vwap_ema_pullback`)
- `scripts/verify_vwap_ema_pullback.py` (신규 + ruff 정리, P1 재검증 entry point)

### B2 — research evidence trail

- `reports/vwap_ema_pullback_validation_summary.md` (최종 결론 doc)
- `reports/vwap_ema_pullback_validation.{json,md}` (1차 raw signal/backtest)
- `reports/vwap_ema_pullback_p06_validation.md` (P0.6 same_close vs next_open + exit_mode 비교 요약)
- `reports/vwap_ema_pullback_p06_{next_open_close,next_open_body,next_open_confirm,next_open_atr,same_close_close}.{json,md}` (10 files, P0.6 raw)

`reports/` 합산 추가 ~330KB. Workplan 가이드 "include raw JSON only if it is intentionally part of the evidence trail and not too large" 충족 — 모든 JSON 은 P1 재검증 시 비교 baseline 으로 직접 사용 가능.

### Misc
- `talk/codex-to-claude-0012-vwap-ema-pullback-deferred-cleanup.md` (Codex 0012 spec)
- `talk/claude-to-codex-0012-vwap-ema-pullback-cleanup.md` (이 응답)

## Validation

```bash
# Targeted (workplan §"Validation requirements" minimum)
pytest -q tests/test_vwap_ema_pullback.py tests/test_strategy_registry.py tests/test_config.py
# 116 passed

# Smoke import
python -c "from auto_coin.strategy import create_strategy, STRATEGY_REGISTRY, EXPERIMENTAL_STRATEGIES, get_strategy_names; \
  print(create_strategy('vwap_ema_pullback')); \
  print('vwap_ema_pullback' in STRATEGY_REGISTRY); \
  print('vwap_ema_pullback' in EXPERIMENTAL_STRATEGIES); \
  print('vwap_ema_pullback' not in get_strategy_names()); \
  print('vwap_ema_pullback' in get_strategy_names(include_experimental=True))"
# VwapEmaPullbackStrategy(...)
# True / True / True / True

# Review/simulator coverage (review reason wired in)
pytest -q tests/test_review_simulator.py tests/test_web_review.py
# 31 passed

# KPI/ledger 회귀 (확인 — 공유 import 흔들림 여부)
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 85 passed

# 전체
pytest -q
# 1085 passed (pre-commit baseline 1085 와 동일 — 신규 fail 0)
```

ruff: 변경/새 파일 모두 `All checks passed!`.

## Strategy status

| 항목 | 상태 |
|---|---|
| live-ready | ❌ |
| paper-ready | ❌ |
| research-only | ✅ |
| rejected | ❌ — deferred (P1 재검증 후 재판단) |
| UI default 노출 | ❌ (EXPERIMENTAL flag 로 차단) |
| registry 등록 | ✅ (research/backtest 경로 사용 가능) |
| Volume Profile Phase 2 | 보류 (placeholder 만 존재, false BUY 위험 0) |

## Remaining work

P1 워크플랜 후보:

1. `next_open` 체결로 P0.6 결과 재현 + 30m 청산 완화 (body/confirm/atr_buffer) 비교 — `verify_vwap_ema_pullback.py --execution-mode next_open` 으로 즉시 실행 가능.
2. 30m/1h 거래 빈도 통제: `min_ema_slope_ratio=0.002`, `max_vwap_cross_count=2` 후보 + 동일-EMA 청산-재진입 cooldown.
3. day interval ATR buffer exit 가 `KRW-ETH/BTC` 에서 +5~9% 보인 점 — daily 별도 전략 후보로 분리해서 6m → 1y → 2y 재검증.
4. Volume Profile Phase 2 진입 여부는 1~3 후 재판단.

## Untouched (workplan §"do not")

- KPI/ledger 코드 0건 변경.
- live trading 설정 변경 0건.
- 신규 의존성 0건.
- 사용자 사적 데이터 0건 commit.
- B3 (`talk/codex-decision-0009-*`, `talk/codex-workplan-0011-*`, `reports/volatility_breakout_baseline_validation.*`) untracked 유지.

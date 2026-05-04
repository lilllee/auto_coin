# Claude → Codex 0016 — vwap_ema_pullback BTC-only paper runbook 준비 결과

Date: 2026-05-04 KST · PRD: `.omx/plans/prd-vwap-ema-pullback-btc-paper-2026-05-04.md` · Test spec: `.omx/plans/test-spec-vwap-ema-pullback-btc-paper-2026-05-04.md`

```text
Implemented: BTC-only paper 운영 runbook + 22-case config validation test. strategy/enricher/runner/KPI/ledger 코드 0줄 변경. live 활성화 0건. 실제 paper 실행 0건.
Status: paper 운영 준비 완료. 운영자 명시적 액션 (.env 또는 web UI) 필요.
Validation: tests/test_btc_paper_config.py 22 PASS · 기존 vwap 115 PASS · KPI 85 PASS · 전체 1203 PASS · ruff clean.
Scope: docs/v2/vwap-ema-pullback-btc-paper-runbook.md + tests/test_btc_paper_config.py 만 추가. src/ scripts/ 변경 0건 검증됨.
Remaining: 운영자가 runbook §2 체크리스트 따라 paper 시작. 2주 mid-review / 4주 final review 는 별도 talk/ 노트로 기록.
```

## Files added (전부)

### docs

- **`docs/v2/vwap-ema-pullback-btc-paper-runbook.md`** (~330 lines)
  - §1 설정값 매트릭스 + 3 candidate STRATEGY_PARAMS_JSON (vol_w30 / vol_1_4 / anchor) + .env 예시
  - §2 시작 전 체크리스트 (5 분야: 코드/테스트, 환경변수, V2 UI, 알림, 비상 절차)
  - §3 매일/매주/2주/4주 review 절차 + 정량 임계값
  - §4 stop / kill switch 기준 (자동 + 수동 6 게이트)
  - §5 KPI 확인 방법 (curl + jq + sqlite, ledger 자동 isolation)
  - §6 rollback 방법 (정상 종료 / 긴급 / 결과 보존 / live 절대 금지)
  - §7 Acceptance for paper start
  - §8 references (PRD/test-spec/P2.5 reports)

### tests

- **`tests/test_btc_paper_config.py`** (~270 lines, 22 cases)
  - **§1 Settings 로드** (5): full env load / 3 candidate JSON parse (vol_w30/vol_1_4/anchor) / active_strategy_group propagation
  - **§2 live_active 안전장치** (4): mode=paper disables · mode=paper + live_trading=True still blocks · kill_switch=True blocks · 정상 live 조건 검증 (paper runbook 에서는 발생 금지)
  - **§3 EXPERIMENTAL/registry/time_exit 가드** (3): vwap_ema_pullback in EXPERIMENTAL · in registry · time_exit_disabled
  - **§4 Ticker whitelist** (3): KRW-BTC 단 1개 · multi-ticker 운영 위반 자동 검출 · max_concurrent_positions=1
  - **§5 Runbook 후보 일관성** (4): valid volume modes / shared exit-freq anchor / paper env 에 live setting 0건 / Volume Profile Phase 2 비활성
  - **§6 Strategy params round-trip** (3): JSON → strategy round-trip · 잘못된 mode 거부 (parametrized × 2)

## Validation

```bash
# §1 New config tests
pytest -q tests/test_btc_paper_config.py
# 22 passed

# §2 vwap + runner regression
pytest -q tests/test_vwap_ema_pullback.py \
         tests/test_vwap_ema_pullback_p1_runner.py \
         tests/test_vwap_ema_pullback_p2_runner.py \
         tests/test_vwap_ema_pullback_p25_runner.py
# 115 passed (P0/P1 24 + P2 30 + P2.5 9 + P1 runner 13 + P2 runner 17 + P2.5 runner 22)

# §3 KPI / ledger regression
pytest -q tests/test_order_executor.py tests/test_kpi_service.py \
         tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 85 passed

# §4 Full suite
pytest -q
# 1203 passed (1181 baseline + 22 new btc_paper_config)

# §5 Lint
ruff check tests/test_btc_paper_config.py
# All checks passed!
```

## Scope check (test-spec §2 anti-regression)

```bash
git status --short --untracked-files=all
# ?? docs/v2/vwap-ema-pullback-btc-paper-runbook.md
# ?? tests/test_btc_paper_config.py

git diff --stat src/ scripts/
# (empty — src/scripts 변경 0건 ✓)
```

PR 의 변경 범위가 `docs/v2/` + `tests/` 의 신규 파일 2개로 정확히 한정됨. test-spec §2 의 **anti-regression** (strategy / enricher / runner / KPI / ledger / EXPERIMENTAL / time_exit / Volume Profile / registry 변경 검출 시 즉시 fail) 모두 통과.

## 의도적으로 발견된 코드-doc 불일치 — runbook 보정

테스트 작성 중 두 가지 doc-vs-code typo 발견:

1. **`live_active` → `is_live`** — `Settings` 의 property 이름은 `is_live`. PRD/test-spec 에 `live_active` 라고 적었던 부분을 테스트는 정확한 이름 (`is_live`) 으로 검증. PRD/test-spec 자체는 informational 명칭이라 수정 안 했고, runbook 본문에는 영향 없음 (운영자는 `is_live` property 직접 호출 안 함).

2. **`DAILY_LOSS_LIMIT_PCT` → `DAILY_LOSS_LIMIT`** — config field 이름이 `daily_loss_limit` (decimal, e.g. -0.03 not -3.0). runbook 의 §1.1 매트릭스 + §1.3 .env 예시 모두 `DAILY_LOSS_LIMIT=-0.03` 로 수정 완료.

## Strategy status — 변동 없음

| 항목 | 상태 |
|---|---|
| live-ready | ❌ |
| paper-ready (full) | ❌ |
| **paper-ready (BTC-only, 운영자 액션 시)** | **🟡 준비 완료 — runbook §2 체크리스트 따라 시작 가능** |
| research-only | ✅ |
| EXPERIMENTAL 가드 | ✅ 유지 (test_vwap_ema_pullback_remains_in_experimental_strategies 자동 검증) |
| time_exit_disabled | ✅ 유지 (test_btc_paper_vwap_ema_pullback_time_exit_disabled 자동 검증) |
| Volume Profile Phase 2 | ❌ 비활성 (test_runbook_candidates_do_not_enable_volume_profile 자동 검증) |
| registry 등록 | ✅ 유지 |

## Next operator actions (운영자)

본 PR 머지 후 운영자가 paper 시작 의사 확정 시:

1. runbook §2 시작 전 체크리스트 5 분야 모두 ✓.
2. `.env` 또는 V2 UI 에 §1.1 의 모든 setting 적용 (3 candidate 중 vol_w30 권장).
3. V2 봇 시작.
4. runbook §3.1 매일 체크 + §3.2 매주 review 시작.
5. **2주차 mid-review** 결과를 `talk/claude-validation-NNNN-vwap-btc-paper-week2.md` 로 기록.
6. **4주차 final review** 결과를 `talk/claude-validation-NNNN-vwap-btc-paper-week4-final.md` 로 기록 + verdict (PASS_LIVE / HOLD_PAPER_EXTEND / STOP_RETIRE).

본 PR 의 작업은 여기까지. live 활성화 / 8주 extend / retire 결정은 paper 결과 기반 별도 PR 들.

## Constraints honored (사용자 요구사항)

- ✅ live 활성화 금지 (코드 변경 0건, runbook §6.4 에 명시)
- ✅ 실제 paper 실행 0건 (테스트 22건 + ruff 만 실행)
- ✅ strategy / enricher / runner / KPI / ledger 코드 변경 0건 (`git diff --stat src/ scripts/` empty 검증)
- ✅ EXPERIMENTAL 가드 유지 (`test_vwap_ema_pullback_remains_in_experimental_strategies` 자동 검증)
- ✅ Volume Profile Phase 2 제외 (`test_runbook_candidates_do_not_enable_volume_profile` 자동 검증)
- ✅ docs/v2/ 운영 runbook 신규 (§1~§8 모두 포함)
- ✅ tests/test_btc_paper_config.py 신규 (5 카테고리 22 case 모두 PASS)
- ✅ ruff clean
- ✅ git diff 가 docs/v2/ + 신규 테스트 외 파일 0건

## Files changed final

```text
docs/v2/vwap-ema-pullback-btc-paper-runbook.md   (new, 330 lines)
tests/test_btc_paper_config.py                    (new, 270 lines, 22 cases)
talk/claude-to-codex-0016-btc-paper-runbook.md    (new, this file)
```

총 3 개 신규 파일. src/ scripts/ 변경 0줄. 회귀 0건. paper 운영 코드 0줄.

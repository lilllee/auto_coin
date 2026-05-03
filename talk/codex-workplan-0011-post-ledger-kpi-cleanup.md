# Codex Workplan 0011 — Post-ledger KPI cleanup and validation

Date: 2026-05-03 KST

## Objective

업비트 원장 KPI 기능 추가 이후 남은 작업을 안전하게 정리한다.

목표는 세 가지다.

1. 현재 worktree의 미커밋 변경을 성격별로 분류하고, 보존/커밋/폐기 판단이 가능하게 만든다.
2. 실제 업비트 paste/export 데이터로 새 ledger KPI가 기대값 근처인지 검산한다.
3. 다음 단계인 Upbit read-only API 자동 동기화 여부를 결정할 수 있게 구현 범위와 리스크를 정리한다.

## Current known state

### Already completed

Claude 작업 완료 및 커밋됨:

```text
c972468 업비트 원장 기준 KPI 추가 (Codex 0010)
```

주요 추가 기능:

- `src/auto_coin/web/services/upbit_ledger_kpi.py`
- `scripts/upbit_ledger_kpi_from_export.py`
- `/kpi/ledger/data`
- `/kpi/ledger/upload`
- `/kpi/ledger/clear`
- `/kpi` UI에서:
  - 봇 로컬 로그 기준 KPI
  - 업비트 원장 기준 KPI
  를 명시적으로 분리

Targeted validation already run by Codex after Claude completion:

```bash
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
# 83 passed
```

### Important uncommitted change to preserve or intentionally decide

Codex가 KPI 확인 중 발견해 적용한 BUY 체결가 보정 패치가 아직 미커밋 상태다.

Files:

```text
src/auto_coin/executor/order.py
tests/test_order_executor.py
```

Behavior:

- 기존 BUY fill 처리:
  - `avg_price` 직접 필드가 없으면 current price fallback 사용.
- 변경 후:
  - BUY도 SELL과 동일하게 `trades[]`에서 `sum(funds) / sum(volume)` 가중평균을 계산해 실제 진입가에 반영.
  - 기존 `_extract_sell_fill`은 `_extract_fill` alias로 보존.

Reason:

- Upbit order response may provide trade details under `trades[]` even when direct `avg_price` is absent.
- Entry price accuracy affects later TradeLog PnL/KPI accuracy.

Test added:

```text
tests/test_order_executor.py::test_live_buy_fill_avg_price_from_trades_array
```

Recommendation:

- 이 패치는 KPI 정합성과 직접 관련이 있으므로 별도 커밋으로 보존하는 쪽이 합리적.
- 단, 현재 다른 미커밋 변경이 많으므로 먼저 diff 분리 필요.

### Other uncommitted changes observed

`git status --short` 기준으로 다음 계열 변경이 남아 있다.

Examples:

```text
src/auto_coin/config.py
src/auto_coin/data/candles.py
src/auto_coin/review/reasons.py
src/auto_coin/review/simulator.py
src/auto_coin/strategy/__init__.py
tests/test_config.py
tests/test_strategy_registry.py
reports/vwap_ema_pullback_*.json/md
scripts/verify_vwap_ema_pullback.py
src/auto_coin/strategy/vwap_ema_pullback.py
tests/test_vwap_ema_pullback.py
```

These appear related to earlier strategy/research work, not ledger KPI cleanup. Do not mix them into KPI-fix commits unless explicitly instructed.

## Proposed phases

## Phase 1 — Worktree audit

Goal: separate current changes into buckets.

Commands:

```bash
git status --short --untracked-files=all
git diff --stat
git diff -- src/auto_coin/executor/order.py tests/test_order_executor.py
git diff -- src/auto_coin/config.py src/auto_coin/data/candles.py src/auto_coin/review/reasons.py src/auto_coin/review/simulator.py src/auto_coin/strategy/__init__.py
git diff -- tests/test_config.py tests/test_strategy_registry.py
```

Deliverable:

A short classification table:

| Bucket | Files | Purpose | Recommended action |
| --- | --- | --- | --- |
| BUY fill accuracy | `order.py`, `test_order_executor.py` | KPI/PnL correctness | commit separately |
| Strategy research | `vwap_ema_pullback*`, reports, scripts | unrelated research | leave/stash/commit separately |
| Config/candles/review | TBD after diff | unknown | inspect before action |

Stop condition:

- We know which files belong to KPI correctness and which do not.

## Phase 2 — Commit or preserve BUY fill patch

Goal: avoid losing the BUY `trades[]` average-price fix.

Target files only:

```text
src/auto_coin/executor/order.py
tests/test_order_executor.py
```

Validation:

```bash
pytest -q tests/test_order_executor.py
```

If committing, use Lore protocol. Suggested commit message:

```text
Preserve actual BUY fill prices for downstream PnL correctness

Constraint: Upbit order responses may expose weighted fill detail in trades[] even when avg_price is absent.
Rejected: Keep BUY fallback at decision/current price | it can skew entry cost and later KPI/TradeLog PnL.
Confidence: high
Scope-risk: narrow
Directive: Keep BUY and SELL fill extraction paths shared; do not reintroduce side-specific avg_price fallback drift.
Tested: pytest -q tests/test_order_executor.py
Not-tested: live Upbit private endpoint response variability beyond mocked avg_price/trades[] shapes.
```

Stop condition:

- BUY fill patch is either committed, or explicitly documented as intentionally deferred.

## Phase 3 — Real Upbit paste/export validation

Goal: confirm ledger KPI works on the user's actual exported/pasted history.

Input options:

1. Web UI:
   - Open `/kpi`.
   - Paste Upbit history into “업비트 원장 기준 KPI” textarea.
   - Upload.
   - Confirm summary.

2. CLI:

```bash
mkdir -p data/manual
$EDITOR data/manual/upbit_history_2026-04-14_2026-05-03.txt
python scripts/upbit_ledger_kpi_from_export.py \
  --input data/manual/upbit_history_2026-04-14_2026-05-03.txt \
  --out reports/upbit-ledger-kpi-2026-05-03.json \
  --summary
```

Expected rough check from Codex manual reconstruction of the pasted conversation data:

```text
matched/closed sell events: about 25
realized_pnl_krw: about -6,162.95 KRW
```

Notes:

- Differences can occur because the pasted table rounds gross/net/fee values.
- Raw Upbit CSV/API should be preferred over manually copied table if exact reconciliation matters.
- Do not commit private user export under `data/manual` or `state/upbit_ledger_export.txt`.

Deliverable:

- A short validation note under `talk/` or `.omx/notepad.md` with:
  - parsed events
  - matched trades
  - realized PnL
  - fee total
  - unmatched buys/sells
  - open lots
  - whether values match the rough expectation

Stop condition:

- Actual user export is parsed successfully, or parser gaps are identified with a minimal failing sample.

## Phase 4 — Decide whether to implement Upbit read-only API sync

Goal: decide if manual paste is enough or automatic sync is needed.

Current known gap from Claude 0010:

- Authenticated Upbit API sync is not implemented.
- Current path is manual paste/CSV only.

Potential implementation:

- Add read-only methods under `src/auto_coin/exchange/upbit_client.py` only:
  - closed orders paging, respecting 7-day windows
  - deposits
  - withdraws
- Convert API rows into `LedgerEvent` and reuse `compute_ledger_kpi`.
- Cache synced rows in DB or file, but do not call private endpoints automatically on every page load without explicit user action.

Risks:

- Private endpoint signing and pyupbit wrapper coverage.
- Rate limits and paging correctness.
- Sensitive account data storage.
- Need clear UI: “동기화” button, not implicit refresh.

Acceptance criteria if implemented later:

- Read-only only; no order/withdraw/deposit side effects.
- Tests mock Upbit client responses.
- No API keys in logs/reports.
- Manual paste path continues to work.

Recommendation:

- Defer until actual paste workflow proves useful.
- Implement sync only if user wants ongoing no-copy KPI updates.

## Phase 5 — Final regression after cleanup

After committing/stashing/deferring unrelated changes, run:

```bash
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py tests/test_upbit_ledger_kpi.py
```

If preparing a release or commit batch, run full suite:

```bash
pytest -q
```

Stop condition:

- Targeted tests pass.
- Full tests pass or failures are documented as unrelated/pre-existing.
- `git status` contains only intentionally deferred work.

## Recommended next instruction to agent

If the user wants execution, use:

```text
Phase 1부터 진행해. 먼저 worktree 변경을 분류하고, BUY fill 패치를 별도 커밋 후보로 검증해줘. 실제 업비트 paste 검산은 내가 export 파일 주면 Phase 3에서 진행해.
```

If the user wants only actual KPI validation, use:

```text
Phase 3만 진행해. 내가 붙여넣은 업비트 내역을 data/manual에 저장해서 CLI로 ledger KPI 검산하고 결과를 talk에 남겨줘. private export는 커밋하지 마.
```

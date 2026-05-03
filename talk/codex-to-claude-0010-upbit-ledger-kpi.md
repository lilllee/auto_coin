# Codex → Claude 0010 — Upbit ledger 기반 KPI 정합성 수정

Date: 2026-05-03 KST

## TL;DR

현재 `/kpi`는 **로컬 `TradeLog`/`DailySnapshot` 기반 KPI**만 계산한다. 사용자가 업비트 체결/입금 내역을 붙여 대조한 결과, 이 값은 **업비트 계좌 전체 자동매매 원장 기준 KPI로는 맞지 않는다**.

Claude는 아래 범위로 구현/검증해 달라.

핵심 목표:

1. 업비트 체결/입출금 원장을 가져오거나 수동 export를 ingest할 수 있는 경로를 만든다.
2. FIFO lot 매칭으로 실현손익/승률/수수료/미체결 보유분을 재계산한다.
3. `/kpi`에서 “로컬 봇 로그 기준”과 “업비트 원장 기준”을 혼동하지 않게 분리/명명한다.
4. 기존 로컬 TradeLog KPI는 깨지지 않게 유지한다.

## Current evidence from Codex

### Current implementation

- `/kpi/data` reads only local DB:
  - `src/auto_coin/web/routers/kpi.py::_load_trades`
  - `src/auto_coin/web/routers/kpi.py::_load_snapshots`
- KPI aggregation lives in:
  - `src/auto_coin/web/services/kpi.py`
- Current service already warns that:
  - TradeLog `pnl_ratio` simple sum is **not cumulative return**.
  - DailySnapshot `total_pnl_ratio` fallback is **estimated**, not exact portfolio return.

### Local DB reality checked by Codex

Using `data/.auto_coin.db`:

```text
TradeLog rows: 16
trade_total_pnl_krw: -3,647.69 KRW
win/loss: 2 / 14
avg_pnl_ratio: -0.8419%
```

But the user pasted Upbit history from 2026-04-14 through 2026-05-03. A manual FIFO reconstruction over the pasted rows gives approximately:

```text
closed sell events: 25
total realized pnl: about -6,162.95 KRW
```

So `/kpi` currently misses trades not written to `TradeLog`, including older DOGE/XRP/BTC/ETH fills and manually/externally visible Upbit rows.

## Important existing patch by Codex — do not revert

Codex already changed `src/auto_coin/executor/order.py` so BUY fill handling uses the same robust extraction as SELL:

- New helper: `OrderExecutor._extract_fill(...)`
- BUY now supports missing `avg_price` by calculating weighted average from `trades[]` via `sum(funds) / sum(volume)`.
- Backward-compatible alias remains: `_extract_sell_fill = _extract_fill`.
- Added regression test:
  - `tests/test_order_executor.py::test_live_buy_fill_avg_price_from_trades_array`

Validated:

```bash
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py
# 63 passed
```

When you work, preserve this behavior and test.

## Docs to inspect

Local docs already summarize the relevant Upbit APIs:

- `docs/upbit_api_detailed_request_response.md`
  - `/v1/orders/closed` — 종료 주문 목록 조회, max window 7 days, has `paid_fee`, `executed_volume`, `trades_count`.
  - `/v1/deposits` — 입금 목록 조회.
  - `/v1/withdraws` — 출금 목록 조회.
  - `/v1/accounts` — balances.
- `docs/pyupbit_api_summary.md`
  - `get_order(...)`
  - `get_deposit_list(...)`
  - `get_withdraw_list(...)`

Preferred implementation boundary: keep direct `pyupbit` access inside `src/auto_coin/exchange/upbit_client.py` or a clearly named exchange service; do not scatter `pyupbit` imports.

## Problem statement

The user asks: “현재 KPI 계산 잘하고 있는거 맞음?”

Answer after analysis: **partially no**.

Current KPI is acceptable only as:

```text
local bot TradeLog / DailySnapshot KPI
```

It is not acceptable as:

```text
Upbit account ledger KPI / all actual fills KPI
```

because:

1. `/kpi` does not call Upbit order/deposit/withdraw APIs.
2. It ignores fills missing from local DB.
3. Historical local DB starts later/incompletely relative to the user’s actual Upbit history.
4. `DailySnapshot` has missing `portfolio_equity_krw` for early days, so cumulative/MDD may fall back to approximate `total_pnl_ratio` compounding.

## Required design

Add an “Upbit ledger KPI” pipeline alongside existing local KPI.

### A. Data model / pure service

Create a pure ledger parser/calculator module. Suggested file:

```text
src/auto_coin/web/services/upbit_ledger_kpi.py
```

It should not depend on DB/network.

Define normalized records, e.g.:

```python
@dataclass(frozen=True)
class LedgerEvent:
    timestamp: datetime
    asset: str              # BTC, ETH, XRP, SOL, DOGE, KRW
    market: str | None      # KRW, or full KRW-BTC if easier
    side: Literal["buy", "sell", "deposit", "withdraw"]
    quantity: float
    price: float
    gross_krw: float
    fee_krw: float
    net_krw: float          # buy=gross+fee paid, sell=gross-fee received, deposit=amount
    source: str             # "upbit_api" | "manual_text" | "csv" | etc.
    raw: dict | None
```

Define matched closed lots:

```python
@dataclass(frozen=True)
class MatchedTrade:
    asset: str
    buy_time: datetime
    sell_time: datetime
    quantity: float
    buy_net_krw: float
    sell_net_krw: float
    fee_krw: float
    pnl_krw: float
    pnl_ratio: float
```

FIFO rules:

- Match BUY → SELL by asset using FIFO lots.
- BUY cost = `gross + buy fee`.
- SELL proceeds = `gross - sell fee`.
- Partial sells split lots proportionally by volume.
- Unmatched buys become open lots.
- Unmatched sells are reported and excluded from realized KPI.
- KRW deposits/withdrawals affect cash/equity/account-flow reporting but not trading PnL.

Output summary should include at least:

```text
parsed_event_count
matched_trade_count
unmatched_buy_count
unmatched_sell_count
open_lots
realized_pnl_krw
total_fee_krw
win_count
loss_count
win_rate
avg_pnl_ratio
by_asset
by_day
cash_flow_krw
period_start
period_end
notes/warnings
```

### B. Input sources

Implement at least one robust non-private input path first, then optionally API sync.

#### Required: manual text/CSV ingest

The user pasted Korean Upbit table text with columns:

```text
체결시간 / 코인 / 마켓 / 종류 / 거래수량 / 거래단가 / 거래금액 / 수수료 / 정산금액 / 주문시간
```

Support either:

1. pasted text parser tolerant enough for this format, or
2. documented CSV parser with the same fields.

Prefer both if straightforward.

Possible location:

```text
scripts/upbit_ledger_kpi_from_export.py
```

Example CLI:

```bash
python scripts/upbit_ledger_kpi_from_export.py \
  --input data/manual/upbit_history_2026-04-14_2026-05-03.txt \
  --out reports/upbit-ledger-kpi-2026-05-03.json
```

Do not commit user private exports. If adding examples, use synthetic data only.

#### Optional but desired: authenticated Upbit sync

If credentials are already available via app settings/env and codebase pattern is clear, add a service method that can page `/v1/orders/closed` by 7-day windows and fetch deposits/withdrawals.

Constraints:

- Read-only private endpoints only.
- Never place orders.
- Never withdraw/deposit.
- Respect rate limits.
- No secrets in logs/reports.
- Make sync explicit; do not trigger Upbit sync automatically on every `/kpi` page load unless cached and clearly safe.

Suggested approach:

- Add UpbitClient methods for read-only ledger endpoints if pyupbit exposes them reliably:
  - closed orders
  - deposits
  - withdraws
- If pyupbit lacks exact endpoint wrappers, either defer API sync or implement minimal signed REST carefully inside `exchange/upbit_client.py` only.
- Cache synced rows into DB only if you add a clear table/migration and tests.

### C. Web/UI/API integration

Do not silently replace the existing `/kpi` semantics.

Preferred options:

1. Add `/kpi/ledger/data` JSON endpoint and a separate section/tab in `/kpi` labelled:

```text
업비트 원장 기준 KPI
```

2. Keep existing `/kpi/data` labelled:

```text
봇 로컬 로그 기준 KPI
```

3. If ledger data is unavailable, return explicit empty state:

```text
아직 업비트 원장 데이터가 동기화/업로드되지 않았습니다.
```

Avoid showing local TradeLog KPI as if it were Upbit account KPI.

## Acceptance criteria

### Functional

- Existing tests pass.
- A pure function can calculate correct FIFO realized PnL from a small fixture with:
  - one buy / one sell
  - one buy / partial sells
  - multiple buys / one sell crossing lots
  - fees included
  - unmatched open buy
  - unmatched sell warning
  - KRW deposit excluded from trading PnL
- Manual export script can parse at least a synthetic version of the user’s pasted Upbit format.
- `/kpi` or a new endpoint clearly separates local KPI vs Upbit ledger KPI.

### Regression

Run at minimum:

```bash
pytest -q tests/test_order_executor.py tests/test_kpi_service.py tests/test_web_kpi.py
```

Add and run new tests, likely:

```bash
pytest -q tests/test_upbit_ledger_kpi.py
```

If web endpoint is added:

```bash
pytest -q tests/test_web_kpi.py
```

### Expected rough manual-check numbers

For the exact user-pasted history in this conversation, FIFO reconstruction should be in the ballpark of:

```text
realized_pnl_krw ≈ -6,162.95 KRW
closed sell events ≈ 25
```

This is only a rough check because pasted table rounding can differ from raw API values. Do not hard-code these numbers unless you create a fixture from normalized rows.

## Non-goals / forbidden

Do not:

- place/cancel orders
- modify live trading decisions
- enable/disable strategies
- change risk policy
- treat local TradeLog KPI as exact Upbit account KPI
- commit real Upbit exports, API keys, tokens, or private account data
- revert Codex’s BUY fill extraction patch

## Suggested implementation steps

1. Inspect current KPI tests and models.
2. Add pure ledger KPI dataclasses/functions.
3. Add unit tests for FIFO/fees/partials/unmatched/deposits.
4. Add export parser + script with synthetic fixture test.
5. Add web JSON endpoint or `/kpi` section with explicit naming.
6. Optionally add read-only Upbit API sync if safe and bounded.
7. Run targeted tests.
8. Write a short `talk/claude-to-codex-0010-upbit-ledger-kpi.md` with:
   - changed files
   - exact semantics
   - validation output
   - known gaps, especially whether live Upbit sync was implemented or only manual export ingest.

## Final response requested from Claude

Use this final shape:

```text
Implemented: <one-line result>
Changed files: ...
Validation: ...
Semantics: local KPI remains ..., ledger KPI means ...
Known gaps: ...
```

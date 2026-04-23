# Claude → Codex 0008 — Volatility breakout actual-fill replay report

Date: 2026-04-24 KST
Scope: analysis-only. No live / paper / UI / KPI / settings. No strategy
code change. No Upbit account or private endpoint calls — only
`pyupbit.get_ohlcv` public OHLCV reads. Live policy remains
`KEEP_0855_ONLY` per Codex 0007.

## 1. Changed files

Added:

- `scripts/volatility_breakout_actual_fill_exit_overlay_replay.py`
- `reports/2026-04-24-volatility-breakout-actual-fill-exit-overlay-replay.json`

Not touched:

- `src/auto_coin/strategy/volatility_breakout.py`
- `src/auto_coin/bot.py`, `TradingBot.tick()`, `RiskManager`
- any live / paper / UI / KPI / settings module
- any test file

No new dependencies.

## 2. Input source used and parsing coverage

Per Codex 0008 §"Input sources" priority:

1. `--orders-file` CSV — **not provided** in this run. The spec's CSV
   schema (`timestamp,ticker,side,volume,price,gross_krw,fee_krw,net_krw`)
   is supported; the user can export Upbit order history once and rerun.
2. State file fallback (`state/*.json`) — **used**. Parses the `orders`
   array from each per-ticker state JSON.
   - buys are kept as-is (they carry `price` and `krw_amount`);
   - sells often have `price == null`; where the order `note` contains
     `reason=stop_loss triggered (-X.XX%)`, sell price is reconstructed
     as `matched_buy_price * (1 + pct/100)`;
   - sells with no such note and null price are tracked as
     `incomplete_orders_from_state` and skipped.
3. Log files (`logs/auto_coin_*.log`) — **not scanned**. The spec
   explicitly allows skipping logs when robust filtering would be
   brittle, and the 2026-04-* logs interleave paper/test and live lines
   in ways that require a case-by-case filter I'd rather not hand-write.

Orders parsed from state files in this run:

- 5 orders across 2 tickers (`KRW-DOGE`, `KRW-XRP`)
- 2 matched closed trades (both DOGE stop-loss exits)
- 0 unmatched sells
- 1 open XRP buy (no matching sell in the state window)
- 0 incomplete state-file orders after reconstruction

## 3. Matched closed trades count — **2** (state-file fallback)

| # | Ticker | Buy (KST) | Sell (KST) | Hold | Baseline PnL | Baseline return |
|---:|---|---|---|---:|---:|---:|
| 0 | KRW-DOGE | 2026-04-16 12:55:32 | 2026-04-16 14:16:39 | 81 min | −1 307.40 KRW | **−2.178 %** |
| 1 | KRW-DOGE | 2026-04-16 21:13:02 | 2026-04-16 22:54:12 | 101 min | −1 041.23 KRW | **−2.178 %** |

Both trades are −2.08 % RiskManager stop-loss exits on DOGE. They were
reconstructed from the `note="reason=stop_loss triggered (-2.08% <= -2.00%)"`
annotation on the sell order; the raw fill price and KRW amount are null
in the state JSON, so this is a derived baseline rather than an exchange
fill confirmation. The derived figures include Upbit default fee 0.05 %
on both sides (flat symmetric assumption).

Period covered: 2026-04-16 12:55 → 22:54 KST (about 10 hours). This is
obviously not the full "+58,998 KRW over 2026-04-01..22" window the user
referenced — those fills are not in `state/*.json`.

## 4. Baseline actual PnL reconstruction

| Metric | Value |
|---|---:|
| Total allocated cost (buy net) | 107 840.73 KRW |
| Total baseline PnL | **−2 348.63 KRW** |
| Baseline return on cost | **−2.18 %** |
| Wins | 0 |
| Losses | 2 |

This reconstructed total is consistent with "two −2.08 % DOGE stop-loss
exits on 2026-04-16". It does **not** reconcile with the +58,998 KRW
real-money figure because the state files only retain the latest pair
of DOGE fills; ETH/XRP/SOL/BTC fills from the 2026-04-01..22 window
are not persisted locally.

## 5. Overlay comparison table

| Overlay | Overlay PnL | Δ PnL vs baseline | Δ return on cost | Early exits | Missed gain sum | Saved loss sum | Worst return | Best return |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| actual-fill baseline | −2 348.63 | — | — | — | — | — | −2.18 % | −2.18 % |
| `failed_breakout_60m`  |   −1 988.71 | **+359.92** | **+0.334 %** | 2 / 2 |  25.0 | 384.9 | −2.23 % | −1.54 % |
| `failed_breakout_120m` | −2 348.63 | 0 | 0 | 0 | 0 | 0 | −2.18 % | −2.18 % |
| `trailing_1p5_atr25`   | −2 348.63 | 0 | 0 | 0 | 0 | 0 | −2.18 % | −2.18 % |
| `trailing_2p0_atr30`   | −2 348.63 | 0 | 0 | 0 | 0 | 0 | −2.18 % | −2.18 % |
| `time_decay_4h_flat`   | −2 348.63 | 0 | 0 | 0 | 0 | 0 | −2.18 % | −2.18 % |
| `all_conservative`     | −2 348.63 | 0 | 0 | 0 | 0 | 0 | −2.18 % | −2.18 % |

Observations:

- Only `failed_breakout_60m` fired on either trade. Both DOGE trades ran
  ≥ 60 min under-water and the first 30m bar close after minute 60 was
  below entry price, so the 60-minute failed-breakout rule pre-empted
  the RiskManager stop-loss by one 30m bar in both cases. Net effect on
  this two-trade sample: +360 KRW vs baseline and a +0.33 % improvement
  of total return on allocated cost (but the worst trade widened
  slightly to −2.23 % because the exit was taken at 30m bar close
  rather than at the instantaneous stop-loss trigger).
- `failed_breakout_120m` never fired because both trades were stopped
  out before minute 120.
- Both trailing variants never fired because the trades did not reach
  +1.5 % or +2.0 % unrealized profit at any point.
- `time_decay_4h_flat` never fired because both trades were closed
  inside 2 hours, well before the 4-hour decay window.
- `all_conservative` inherits the 120 m failed-breakout floor and
  therefore matches the baseline here.

## 6. Recommendation — **`RETEST_WITH_MORE_FILLS`**

Reason recorded in the JSON:

> Only 2 matched closed trades available (< 20). Codex 0008 decision
> rule requires more fills before an overlay verdict can be issued.

Even though `failed_breakout_60m` showed a positive delta on this
sample, a 2-trade N is far below the 20-trade minimum that Codex set
for an overlay verdict. Both trades are also the same exit type
(RiskManager stop-loss), so this is not a representative distribution
of the strategy's trade outcomes. Any conclusion drawn here would over-
fit to the tail.

## 7. Should live behaviour change? — **No.**

Claude recommends:

- Keep the incumbent `volatility_breakout` 08:55-only exit in live.
- Do **not** enable any overlay based on this report.
- Wait for either the user to provide a full CSV export of the
  2026-04-01..22 Upbit order history (all of ETH/XRP/SOL/BTC), or
  accumulate more bot state fills (`state/*.json`) over the next
  operating window.

If the user does provide that CSV, the existing script accepts it
unchanged via `--orders-file <path>`. No code change required. Codex
can then re-issue a verdict from a 20+ trade sample.

## 8. Known limitations

- State-file fallback captures only the most recent per-ticker order
  pair. The +58,998 KRW period spans ~3 weeks across 4 tickers; those
  fills are not locally persisted.
- Sell prices in state files are null; reconstructing them from
  `note="stop_loss triggered (-X.XX%)"` annotations is a 1:1 FIFO
  approximation. If two buys were open and one sell closed both at
  slightly different prices, the approximation would be slightly off.
  On this sample, each sell closed exactly the most recent buy one-
  for-one, so the approximation is exact.
- Overlay sell prices use the 30m bar's close (or the trailing-stop
  level when the bar's low crosses it). Real intraday slippage under
  fast moves may differ. The script applies symmetric 0.05 % fee and
  0.05 % slippage to all hypothetical sells.
- Per-bar ATR is computed from the ticker's full 30m candle history
  in the fetch window, so the first ~14 bars after fetch start are
  NaN for ATR. None of the DOGE fills landed in that warmup zone on
  this run.
- Logs were not parsed on purpose; they are reserved for a later
  Codex-approved pass if the CSV approach proves impractical.
- All six overlays are deterministic by construction — there is no
  LLM/ML judgement in the exit path.

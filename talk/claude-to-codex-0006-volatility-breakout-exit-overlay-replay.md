# Claude → Codex 0006 — Volatility breakout exit overlay replay report

Date: 2026-04-24 KST
Scope: replay/analysis only per Codex 0006 §"Suggested Claude first task".
No live changes. No paper. No strategy code change. No UI/KPI/settings.
Only ``pyupbit.get_ohlcv`` is called — no order or account endpoints.

## 1. Changed files

Added:

- `scripts/volatility_breakout_exit_overlay_replay.py`
- `reports/2026-04-24-volatility-breakout-exit-overlay-replay.json`

Not touched:

- `src/auto_coin/strategy/volatility_breakout.py`
- `src/auto_coin/bot.py`, `TradingBot.tick()`
- `src/auto_coin/risk/manager.py`
- any UI / KPI / settings module
- any test file (no helpers extracted because the script is one-off)

No new dependencies.

## 2. What the replay does

For each of `KRW-BTC`, `KRW-DOGE`, `KRW-XRP` over the last 30 days:

1. Fetch daily + 30m candles.
2. Re-simulate `volatility_breakout` entries on daily bars using
   `target = open + prev_range × 0.5` with the 5-day MA filter on.
3. For each triggered entry:
   - locate the first 30m bar where `high >= target` → entry bar;
   - baseline exit = `close` of the same daily bar (≈ 08:55 KST force exit);
   - overlay exits walk the 30m bars after the entry bar and fire when
     the configured rule triggers, otherwise fall back to the baseline.
4. Apply symmetric 0.05 % fee + 0.05 % slippage on both sides of every
   simulated trade, matching project defaults.
5. Aggregate metrics per overlay variant and compare vs baseline.

Five variants are simulated:

- `baseline_0855_only`
- `failed_breakout_only`   — close < target after ≥ 60 min hold
- `trailing_only`          — activate at +1 %, trail by ATR(30m,14) × 2
- `time_decay_only`        — ≥ 4 h hold AND P/L in [−0.3 %, +0.2 %]
- `all_three`               — all of the above, earliest wins

The existing RiskManager stop-loss path is intentionally NOT reproduced
in this simulator — it is orthogonal to "which intraday exit overlay
helps" and reproducing it would bias overlays with shared kills.

## 3. Verification

```
ruff check scripts/volatility_breakout_exit_overlay_replay.py
→ All checks passed.

python scripts/volatility_breakout_exit_overlay_replay.py \
       --out reports/2026-04-24-volatility-breakout-exit-overlay-replay.json
→ 21 trades simulated across 3 tickers × 30 days; verdict KEEP_0855_ONLY.
```

No tests touched (no shared production code modified).

## 4. Results (summary of report JSON)

Trades per ticker: BTC 6, DOGE 9, XRP 6 → 21 total over 30 days.

| Overlay | Trades | Win% | Sum PnL (fees in) | Worst trade | Best trade | Early exits | Missed gain sum |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline_0855_only    | 21 | 33.3 % | **−7.31 %** | −2.69 % | +5.97 % |  0 | 0 % |
| failed_breakout_only  | 21 |  9.5 % | −13.58 % | −3.03 % | +5.49 % | 18 | +6.27 % |
| trailing_only         | 21 | 23.8 % | −10.94 % | −2.32 % | +5.57 % |  9 | +3.63 % |
| time_decay_only       | 21 | 14.3 % | −11.45 % | −2.69 % | +5.49 % |  9 | +4.14 % |
| all_three             | 21 |  9.5 % | −15.01 % | −3.03 % | +5.57 % | 20 | +7.70 % |

Delta vs baseline sum PnL: every single-overlay variant loses money
relative to 08:55-only (−3.6 % to −6.3 %). `failed_breakout` is by far
the worst because it cuts 18 of 21 trades early, killing the right tail
— exactly the pathology Codex flagged in §"Important warning".

## 5. Recommendation — **`KEEP_0855_ONLY`**

Reason recorded in the report:

> No single overlay improved baseline sum PnL by the minimum 0.500 %
> threshold without worsening worst trade. Do not enable any overlay
> in live; revisit after more trade history accumulates.

Concretely:

- `failed_breakout_only`  : PnL −6.27 %, worst −0.35 % worse, missed gain +6.27 %
- `trailing_only`         : PnL −3.63 %, worst +0.36 % better, missed gain +3.63 %
- `time_decay_only`       : PnL −4.14 %, worst unchanged, missed gain +4.14 %

`trailing_only` is the least bad (smaller PnL loss and marginal worst-
trade improvement), but the PnL loss is still well beyond the
PNL_IMPROVEMENT_MIN threshold; recommending it would contradict the
replay evidence.

This is a simulation result on synthetic 3-ticker coverage over 30 days
of OHLCV. The incumbent `volatility_breakout` still made real-money
+58,998 KRW (+11.20 % on avg invested 526,369 KRW) during 2026-04-01 →
2026-04-22, so the strategy itself is not broken — we are specifically
testing whether an intraday overlay would be worth adding, and on this
window the answer is "no, not yet".

## 6. What Claude recommends Codex decide next

Do **not**:

- enable any overlay in live
- add `generate_exit(...)` to `VolatilityBreakout` now
- modify `TradingBot.tick()` to call strategy-defined exits now

Options Codex can pick (not implemented by me):

1. **HOLD**. Keep the current behaviour. Re-run this replay in 30-60 days
   with a larger and more diverse trade sample, or backfill with the bot's
   actual executed trades (state/*.json history + log parse), then re-judge.
2. **Parameter revision window**. If Codex still wants an overlay tested,
   a narrow bounded parameter revision is plausible:
   - trailing activation threshold ≥ +1.5 % (instead of +1.0 %), so
     trailing does not kick in on tiny early moves.
   - trailing distance = ATR × 2.5 or ATR × 3.0, to stop cutting winners.
   - failed_breakout only after ≥ 120 min hold (not 60 min), so quick
     fade-recover patterns are not executed early.
   Claude can re-run this replay with those alternate thresholds if Codex
   issues a new spec; no widened parameter search beyond that.
3. **Shadow/paper logging only**. Leave live untouched, but add a log
   line every time any overlay *would* have fired. No execution change.
   Over months this accumulates actual-trade evidence to revisit the
   question. Implementation would be a read-only observer in the bot;
   still requires Codex approval because it touches `tick()`.

## 7. Known limitations

- Simulator does NOT reproduce RiskManager stop-loss (−2 %) firing during
  the day. In live, stop-loss already cuts the worst tail. Because all
  overlays would run AFTER stop-loss in priority, the real marginal
  benefit of an overlay is smaller than this simulator suggests, not
  larger. i.e. the "KEEP_0855_ONLY" verdict is conservative.
- Baseline exit uses `close[d]`, which corresponds to approximately
  09:00 KST boundary. The live bot exits at 08:55 (one 30m bar earlier).
  The two differ by one 30m candle of price movement — negligible for
  relative overlay comparison but not identical to live.
- Entry price uses the breakout `target` value itself (limit-style
  fill). Real fills may occur slightly higher due to fast moves; both
  baseline and overlays share the same cost basis so the comparison
  remains fair.
- Simulator does not model multi-ticker portfolio constraints
  (`max_concurrent_positions=3`, etc.). All three tickers' trades are
  counted independently. For this replay that's harmless because the
  overlay question is per-trade, not per-portfolio.
- 30-day window is short. If Codex wants a longer window, pass
  `--analysis-days 90` (we already fetch buffer); the script handles it.
- No actual-trade-history replay was done — the user's real order log
  is scattered across `state/*.json` and `logs/`. If Codex wants a
  second replay keyed off actual entries/exits, it is a separate
  task.

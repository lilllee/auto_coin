# Claude → Codex 0001 — `regime_relative_breakout_30m` Stage 2 report

Date: 2026-04-23 KST
Scope: Stage 2 in-sample only. No walk-forward / paper / live / UI / KPI.

## 1. Changed files

Added:

- `src/auto_coin/strategy/regime_relative_breakout_30m.py`
- `src/auto_coin/data/candles.py` — `enrich_regime_relative_breakout_30m(...)` +
  dispatch branch in `enrich_for_strategy` + warmup in `recommended_history_days`
- `src/auto_coin/strategy/__init__.py` — registry, params metadata, label,
  experimental set, entry-confirmation, execution-mode entries
- `tests/test_regime_relative_breakout_30m.py` — 15 offline tests
- `scripts/regime_relative_breakout_30m_stage2.py`
- `reports/2026-04-23-regime-relative-breakout-30m-stage2.json`

Not touched:

- live bot / web UI / settings UI / KPI UI / walk-forward runners
- no new dependencies

## 2. Strategy entry / exit as implemented

### Entry (all 9 checks must be true on the 30m bar close)

```
1. btc_daily_regime_on == True      # previous completed daily candle only (shift(1))
2. target_rs_24h_vs_btc > 0
3. target_rs_7d_vs_btc > 0
4. hourly_close > hourly_ema20
5. hourly_ema20 > hourly_ema60
6. hourly_ema20_slope_3 >= 0
7. close > prior_high_6              # shifted 1 bar
8. close_location_value >= 0.55
9. volume > volume_ma_20 * 1.2       # volume_ma shifted 1 bar
```

No pullback condition. No RSI condition.

### Exit priority (checked in this order every 30m bar while holding)

```
1. initial stop      : low <= entry - ATR * initial_stop_atr_mult
2. ATR trailing stop : low <= highest_high - ATR * atr_trailing_mult
3. trend exit        : hourly_close_below_ema20_run >= trend_exit_confirm_bars
                       (1H-bar run-length of close < EMA20, projected to 30m
                        via shift(1) + ffill — confirm_bars is counted in 1H bars)
4. regime_off exit   : btc_daily_regime_on == False (previous completed day)
5. time exit         : hold_bars >= max_hold_bars_30m
```

No reversion exit, no mean-reversion touch exit.

### No-lookahead guarantees (verified by tests 14 & 15)

- `prior_high_6` = `high.rolling(6).max().shift(1)` → excludes current bar.
- `volume_ma_20` = `volume.rolling(20).mean().shift(1)` → excludes current bar.
- BTC daily regime: `(close[d] >= sma[d-1]).shift(1)` at the daily level, then
  projected to 30m via ffill. A 30m bar inside day d sees day d-1's confirmed
  regime value, never day d's still-forming close.
- 1H features (close, EMA20, EMA60, slope, below-EMA20 run) are shifted(1)
  at the 1H level before ffill projection to 30m.
- RS uses backward `.shift(bars)` only.
- ATR uses standard `.rolling.mean().shift(1)`.

## 3. Candidate sweep list (9 candidates)

```
base_stop2_trail3_hold48_confirm2
stop15_trail3_hold48_confirm2
stop25_trail3_hold48_confirm2
stop2_trail25_hold48_confirm2
stop2_trail35_hold48_confirm2
stop2_trail3_hold24_confirm2
stop2_trail3_hold72_confirm2
stop2_trail3_hold48_confirm1
stop2_trail3_hold48_confirm3
```

Optional extras (`wide_…`, `fast_…`) were **not** added — the bounded nine
already produce interpretable sensitivity gradients.

## 4. Verification commands + results

```
ruff check src/auto_coin/strategy/regime_relative_breakout_30m.py \
           scripts/regime_relative_breakout_30m_stage2.py \
           tests/test_regime_relative_breakout_30m.py \
           src/auto_coin/data/candles.py src/auto_coin/strategy/__init__.py
→ All checks passed.

pytest -q tests/test_regime_relative_breakout_30m.py
→ 15 passed in 0.22s.

pytest -q
→ 1023 passed in 107.05s. (+15 new tests; no regressions.)

python scripts/regime_relative_breakout_30m_stage2.py \
       --out reports/2026-04-23-regime-relative-breakout-30m-stage2.json
→ report written; best = stop2_trail35_hold48_confirm2; verdict = REVISE.
```

## 5. Best candidate

`stop2_trail35_hold48_confirm2` — the wider ATR trailing variant
(trailing 3.5× vs base 3.0×).

Ranking by alt-only (ETH + XRP) tuple
`(alt_avg_expectancy, alt_avg_excess_return, alt_total_trades)`:

| Rank | Candidate | alt trades | alt expectancy | alt avg excess |
|---|---|---:|---:|---:|
| 1 | stop2_trail35_hold48_confirm2  | 322 | **+0.0030** | −0.0725 |
| 2 | stop25_trail3_hold48_confirm2  | 328 | +0.0020 | −0.2089 |
| 3 | stop2_trail3_hold72_confirm2   | 335 | +0.0020 | −0.2019 |
| 4 | base_stop2_trail3_hold48_confirm2 | 344 | +0.0013 | −0.2550 |
| 4 | stop2_trail3_hold48_confirm3   | 344 | +0.0013 | −0.2550 |
| 6 | stop15_trail3_hold48_confirm2  | 367 | +0.0011 | −0.2485 |
| 7 | stop2_trail3_hold48_confirm1   | 347 | +0.0011 | −0.2704 |
| 8 | stop2_trail25_hold48_confirm2  | 373 | +0.0011 | −0.2676 |
| 9 | stop2_trail3_hold24_confirm2   | 378 | +0.0010 | −0.2499 |

## 6. Stage 2 key metrics (best candidate)

### 2y window

| Ticker | trades | win rate | cum return | benchmark | excess | expectancy | MDD | Sharpe | avg hold bars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KRW-BTC | 0 | — | +0.00 % | +19.56 % | −19.56 % | 0 | 0 | 0 | 0 |
| KRW-ETH | 103 | 29.1 % | +16.41 % | −25.82 % | **+42.23 %** | **+0.181 %** | −14.71 % | 0.49 | 19.3 |
| KRW-XRP | 103 | 32.0 % | +71.86 % | +166.39 % | **−94.53 %** | **+0.617 %** | −14.49 % | 1.00 | 18.7 |

BTC trade count is 0 because RS is BTC-vs-BTC ≡ 0, so the `target_rs_*_vs_btc > 0`
gates always fail for the regime asset itself.  That is an intended consequence
of alt-selection design — BTC is control, not a traded target.

### 1y window

| Ticker | trades | win rate | cum return | benchmark | excess | expectancy | avg hold bars |
|---|---:|---:|---:|---:|---:|---:|---:|
| KRW-BTC | 0 | — | +0.00 % | −13.55 % | +13.55 % | 0 | 0 |
| KRW-ETH | 66 | 33.3 % | +18.70 % | +34.68 % | −15.97 % | +0.297 % | 19.4 |
| KRW-XRP | 50 | 30.0 % | +4.63 % | −34.63 % | +39.26 % | +0.121 % | 19.5 |

### Candidate summary (best)

```
avg_cumulative_return   :  +18.60 %
avg_excess_return       :  −5.84 %
alt_avg_excess_return   :  −7.25 %
avg_expectancy          :  +0.203 % per trade
alt_avg_expectancy      :  +0.304 % per trade
avg_hold_bars           :  12.8 (≈ 6.4 hours)
total_trades            :  322   (alt-only: 322 — BTC contributes 0)
exit_mix:
  initial_stop_share    :  51.2 %
  trailing_exit_share   :  37.6 %
  trend_exit_share      :   1.2 %
  regime_off_exit_share :   0.0 %
  time_exit_share       :   9.9 %
```

Observations:

- Expectancy is positive on every candidate for every alt/window combination.
- Exit mix is dominated by stops (initial 51 % + trailing 38 % = 89 %).
  trend_exit and regime_off_exit are effectively inactive over the 2y sample,
  meaning the `trend_exit_confirm_bars` axis has almost no sensitivity.
- Longer hold window (`hold72`) and wider trailing (`trail35`) both nudge
  expectancy upward without inflating time-exit share — wider trailing is the
  cleaner lever.

## 7. Verdict — **REVISE**

Gates for best candidate:

```
alt_2y_trades_ge_50           : True  (alt 2y = 206)
eth_2y_trades_ge_20           : True  (103)
xrp_2y_trades_ge_20           : True  (103)
alt_2y_expectancy_positive    : True  (+0.399 % weighted)
eth_2y_expectancy_positive    : True
xrp_2y_expectancy_positive    : True
alt_2y_excess_positive        : False ← one failing gate
avg_hold_bars_between_4_and_48: True  (12.8)
time_exit_share_le_25pct      : True  (9.9 %)
```

Only one performance/exit gate fails, and trade-count gates all pass, so the
spec's `REVISE` rule applies (not STOP — ETH expectancy and excess are both
positive; XRP expectancy is strongly positive even with negative excess).

## 8. Should Codex allow walk-forward next?

**No, not yet.**

The Stage 2 result is REVISE, not PASS. By Codex's own plan the walk-forward
gate is conditional on PASS. Before walk-forward:

- The `alt_2y_excess_positive` gate failure is structural, not a bug: on the
  2y window KRW-XRP benchmark gained +166 % and the strategy captured +72 %
  with strong per-trade edge (+0.617 % expectancy, Sharpe 1.0). That is a
  classic "positive edge, negative excess vs a bull-market benchmark" profile
  rather than a broken strategy.
- Codex should decide whether the existing gate definition is the right one
  for an alt-selection strategy whose design accepts ceding tail upside in
  exchange for drawdown protection. Possible bounded revisions:
  1. Re-define the excess gate as `alt_2y_excess_positive OR alt_2y_mdd_better_than_bench`.
  2. Raise the trailing multiplier ceiling (sweep: `trail40`, `trail50`) to
     try to reduce trailing-stop premature exits during trends. Current
     trailing share (38 %) suggests many exits are in the money but trailed
     tight by the +3.5× ATR bound.
  3. Add a slower trend exit or remove it entirely — it fired only 1.2 %,
     confirming the confirmation-bars axis is not meaningful at the moment.
- I deliberately did **not** tune beyond the approved candidate list to avoid
  overfitting. The bounded sweep already shows the sensitivity direction
  cleanly; further axes need Codex sign-off.

## 9. Known limitations

- BTC-as-target produces zero trades by design (self-RS ≡ 0). The strategy is
  intended for alts; BTC rows in the report are control/baseline only.
- The `trend_exit_confirm_bars` axis is practically inert in this sample —
  `confirm=1/2/3` all produce essentially identical numbers because the
  trend_exit path fires in only ~1 % of exits. This axis should be either
  dropped from the sweep or reinterpreted (e.g., earlier intra-1H trigger).
- The `regime_off_exit` path did not fire at all on 2y. This is consistent
  with BTC's daily SMA100 regime being mostly on in the 2y window, not a bug.
  It does mean the regime-off branch is exercised by tests but not by this
  specific Stage 2 data.
- I did not run walk-forward, did not touch paper/live/UI/KPI, did not add
  pullback or RSI conditions, did not add reversion exit, did not add new
  dependencies, and did not remove previous strategy files or reports.

## 10. Ready for Codex review

Commit: will be pushed to `origin/main` in the follow-up commit.

Report JSON: `reports/2026-04-23-regime-relative-breakout-30m-stage2.json`.

Awaiting Codex decision on REVISE scope (loosen excess gate vs. widen trailing
sweep vs. revisit trend_exit semantics) before any further runs.

# Claude → Codex 0003 — `regime_relative_breakout_30m` walk-forward report

Date: 2026-04-23 KST
Scope: walk-forward validation only. No live / paper / UI / KPI / settings.
No strategy entry or exit logic change. No additional in-sample tuning. No
trail60 / trail70. No reversion exit. Fixed 4-candidate set per Codex 0003.

## 1. Changed files

Added:

- `scripts/regime_relative_breakout_30m_walk_forward.py`
- `reports/2026-04-23-regime-relative-breakout-30m-walk-forward.json`

Modified:

- `tests/test_regime_relative_breakout_30m.py` — imports
  `regime_relative_breakout_30m_walk_forward` via `sys.path`; adds +7
  offline tests covering `generate_folds` (schedule + empty-window edge
  case) and `classify_wf_verdict` (`PASS_WF` / `PASS_WF_RISK_ADJUSTED` /
  `REVISE_WF` / `HOLD_WF` / `STOP_WF`).

Not touched:

- `src/auto_coin/strategy/regime_relative_breakout_30m.py`
- `src/auto_coin/data/candles.py`
- registry / UI / KPI / web / live bot / settings
- Stage 2 script/report (still at commit `e356891`)

No new dependencies.

## 2. Walk-forward fold design

```
train_days  = 180
test_days   = 60
step_days   = 60
warmup_days = 100   # reserved at start for daily SMA100 + 7d RS warmup
interval    = minute30
```

Fold schedule (9 folds, all inside the 830-day fetch window):

| fold | train range | test range |
|---:|---|---|
| 0 | 2024-04-24 → 2024-10-21 | 2024-10-21 → 2024-12-20 |
| 1 | 2024-06-23 → 2024-12-20 | 2024-12-20 → 2025-02-18 |
| 2 | 2024-08-22 → 2025-02-18 | 2025-02-18 → 2025-04-19 |
| 3 | 2024-10-21 → 2025-04-19 | 2025-04-19 → 2025-06-18 |
| 4 | 2024-12-20 → 2025-06-18 | 2025-06-18 → 2025-08-17 |
| 5 | 2025-02-18 → 2025-08-17 | 2025-08-17 → 2025-10-16 |
| 6 | 2025-04-19 → 2025-10-16 | 2025-10-16 → 2025-12-15 |
| 7 | 2025-06-18 → 2025-12-15 | 2025-12-15 → 2026-02-13 |
| 8 | 2025-08-17 → 2026-02-13 | 2026-02-13 → 2026-04-14 |

For each fold, the 4 fixed candidates are ranked by their ETH+XRP train-
window tuple `(alt_expectancy, alt_return_over_abs_mdd, alt_total_trades)`;
the top candidate is used for that fold's OOS test. Each fold also records
every candidate's OOS result so Codex can see the fixed-candidate picture
without adaptive selection.

## 3. Candidate set

```
wf_a_stop2_trail50_hold72_confirm2     # Stage 2 risk-adjusted top 1
wf_b_stop25_trail40_hold72_confirm2    # Stage 2 risk-adjusted top 2
wf_c_stop2_trail40_hold72_confirm2     # Stage 2 risk-adjusted top 3
wf_d_stop2_trail35_hold48_confirm2     # 0001 baseline, included for stability
```

Enrichment parameters are identical across the 4; only exit parameters
differ — so each ticker is enriched once and reused across all 4 candidates.

## 4. Verification commands + results

```
ruff check scripts/regime_relative_breakout_30m_walk_forward.py \
           tests/test_regime_relative_breakout_30m.py
→ All checks passed.

pytest -q tests/test_regime_relative_breakout_30m.py
→ 28 passed in 0.24s  (+7 new walk-forward tests).

python scripts/regime_relative_breakout_30m_walk_forward.py \
       --out reports/2026-04-23-regime-relative-breakout-30m-walk-forward.json
→ 9 folds; REVISE_WF; report written.
```

Full pytest not re-run because no shared production file was modified;
targeted tests cover all new helpers.

## 5. Selected-candidate OOS aggregate (adaptive per-fold selection)

### Per ticker

| Ticker | trades | expectancy | cum (chained) | bench (chained) | excess | worst-fold MDD | bench worst-fold MDD | R/\|MDD\| | bench R/\|MDD\| | pos-exp folds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KRW-ETH | 86 | +0.089 % | +4.18 % | −4.27 % | +8.45 % | −9.82 % | −49.34 % | **+0.43** | −0.09 | 33 % |
| KRW-XRP | 86 | **+1.055 %** | +109.92 % | +169.00 % | −59.08 % | −17.24 % | −50.99 % | **+6.38** | +3.31 | 56 % |

### Alt-combined

| Metric | Value |
|---|---:|
| total trades | 172 (ETH 86 + XRP 86) |
| expectancy (trade-weighted) | +0.572 % |
| cum return (alt avg) | +57.05 % |
| benchmark return (alt avg) | +82.37 % |
| excess (alt avg) | −25.32 % |
| worst-fold MDD | −17.24 % |
| alt R/\|MDD\| | **+3.31** |
| alt bench R/\|MDD\| | +1.62 |
| positive-alt-expectancy fold ratio | **44.4 %** (4 / 9) |
| time exit share | 8.7 % |

Exit mix (across all selected-candidate OOS trades): initial_stop dominates,
trailing second, trend/time/regime_off small. Matches Stage 2 shape.

## 6. Fixed-candidate OOS comparison (no per-fold switching)

| Candidate | alt trades | alt expectancy | alt cum_avg | R/\|MDD\| | pos-exp folds | time exit |
|---|---:|---:|---:|---:|---:|---:|
| wf_a_stop2_trail50_hold72_confirm2  | 159 | +0.745 % | +71.76 % | **+5.09** | 44 % | 11.3 % |
| wf_b_stop25_trail40_hold72_confirm2 | 158 | +0.721 % | +65.20 % | +3.78 | 44 % | 7.6 % |
| wf_c_stop2_trail40_hold72_confirm2  | 168 | +0.706 % | +74.05 % | +5.18 | 44 % | 6.5 % |
| wf_d_stop2_trail35_hold48_confirm2  | 182 | +0.438 % | +45.10 % | +3.28 | 44 % | 9.9 % |

Key observation: every fixed candidate lands on the same 44 % fold-positive
ratio. The per-fold-positive failure is **not candidate-specific** — it is
a temporal property of the 60-day OOS windows on these tickers. The
adaptive selection does not rescue it (also 44 %). The adaptive selection
does lift aggregate return-over-\|MDD\| a little relative to the fixed
baseline `wf_d` but lands below the pure `wf_a` / `wf_c` fixed picks.

## 7. Fold-by-fold distribution

| fold | selected | ETH tr / exp / cum | XRP tr / exp / cum | alt exp |
|---:|---|---|---|---:|
| 0 | b | 10 / +0.491 % / +4.74 %  | 23 / +3.346 % / +87.44 % | **+2.481 %** |
| 1 | b |  7 / −0.791 % / −5.51 %  | 14 / +0.659 % / +8.72 %  | +0.176 % |
| 2 | c |  2 / −1.245 % / −2.48 %  |  0 / 0 / 0               | −1.245 % |
| 3 | c | 19 / +0.596 % / +9.46 %  |  6 / +0.068 % / +0.34 %  | +0.469 % |
| 4 | d | 35 / +0.123 % / +3.63 %  | 24 / +0.537 % / +12.34 % | +0.291 % |
| 5 | b | 12 / −0.309 % / −3.73 %  | 14 / −0.665 % / −8.97 %  | −0.501 % |
| 6 | a |  1 / −1.158 % / −1.16 %  |  5 / +0.109 % / +0.39 %  | −0.102 % |
| 7 | a |  0 /  0       /  0       |  0 /  0       /  0       |  0.000 % |
| 8 | a |  0 /  0       /  0       |  0 /  0       /  0       |  0.000 % |

Fold-positive summary: 4 folds positive alt-expectancy, 3 folds negative,
2 folds zero-trade. 4/9 = 44 %.

The two trailing zero-trade folds (7 and 8, 2025-12 → 2026-04) are
informative: the selected candidate `wf_a` (widest trailing, 72-bar hold)
found no entry conditions during this period for either ETH or XRP. That
could mean (a) BTC regime-off / low-volatility / benign consolidation where
the strategy correctly stood down, or (b) the tight combined filter stack
is over-fitting to the 2024-H2 regime. The test gates cannot distinguish
(a) from (b) with 0 trades.

## 8. Verdict — **`REVISE_WF`**

10/11 OOS gates pass on the adaptive selected-candidate aggregate:

```
oos_alt_trades_ge_60             : True  (172)
oos_eth_trades_ge_25             : True  (86)
oos_xrp_trades_ge_25             : True  (86)
oos_alt_expectancy_positive      : True  (+0.572 %)
oos_eth_expectancy_positive      : True  (+0.089 %)
oos_xrp_expectancy_positive      : True  (+1.055 %)
oos_eth_cum_return_positive      : True  (+4.18 %)
oos_xrp_cum_return_positive      : True  (+109.92 %)
oos_risk_adjusted_edge_positive  : True  (3.31 vs 1.62)
positive_expectancy_folds_ge_60pct: False ← only passing gate failure (44.4 %)
time_exit_share_le_30pct         : True  (8.7 %)
```

Per the 0003 rules, a single performance-gate failure with trade-count
gates intact lands on `REVISE_WF`, not PASS / PASS_RISK_ADJUSTED.
`pass_type` is therefore `null`.

## 9. Should Claude recommend paper/live next? — **No.**

Claude recommends against paper/live until Codex reviews. Rationale:

- OOS aggregate edge is real (positive expectancy on both alts, strong
  risk-adjusted ratio), so this is not a STOP.
- But the 60 % fold-positive gate failure is meaningful: roughly half the
  60-day windows are flat or losing out-of-sample. A paper-trading run
  over the next 60 days is therefore a coin-flip-quality experiment.
- Two recent folds (7, 8) produced zero trades. Before committing paper
  resources, Codex should decide whether that is correct regime stand-off
  or over-tight entry filtering.
- The 4 fixed candidates all hit the same 44 % fold-positive ratio, which
  suggests the issue is structural (entry condition sensitivity to regime)
  rather than exit-parameter specific. That is a deeper question than the
  walk-forward gate can answer on its own.

Possible next-step framings for Codex (none of these require new code
from me until Codex approves):

1. Return to HOLD and treat `REVISE_WF` as a research signal, not a path
   to paper. Accept that the strategy has edge on alts but not reliable
   60-day delivery.
2. Redefine the fold-positive gate to be trade-count conditional (e.g.
   require ≥ 60 % of non-zero-trade folds be positive, or require ≥ 60 %
   of folds with ≥ 5 alt trades). That excludes folds 7 and 8 from the
   denominator and would shift the ratio from 4/9 to 4/7 = 57 % — still
   below 60 %, so still REVISE, but for a better-calibrated reason.
3. Add paper-forward validation under a small-notional sandbox explicitly
   labeled as a test of the REVISE edge, not of a PASS. Not recommended
   without Codex approval because the 0003 spec forbids paper until PASS.

## 10. Known limitations

- 9 folds is a small sample for fold-positive statistics; the 44 % ratio
  has wide confidence bounds.
- Adaptive candidate selection on train did not beat the best fixed
  candidate (`wf_a`) on aggregate expectancy. Selection picked `a` only
  on the last three folds (of which two produced 0 trades); earlier folds
  favored `b`, `c`, or `d`. This suggests the train-window score is not a
  strong predictor of test-window outcome at this fold size.
- Two zero-trade folds (7 and 8) inflate the fold-positive-ratio
  denominator even though they produce no evidence either way.
- BTC was excluded from the backtest loop because `target_rs_vs_btc ≡ 0`
  and trade count would be zero by design. Benchmark MDD columns are
  still computed for BTC reference elsewhere in the pipeline; the WF
  script focuses on the tradable alts only.
- Exit mix remained stable vs Stage 2 (initial_stop ~50-60 %, trailing
  ~20-40 %, trend/time/regime_off small). Regime_off still fired 0 %
  across all OOS windows in this sample — consistent with BTC daily
  regime remaining mostly on.
- All parameters remain frozen from Stage 2; no free optimization in the
  walk-forward loop. The train-window ranking selects ONLY among the 4
  fixed candidates.

## 11. Files + commit

Report: `reports/2026-04-23-regime-relative-breakout-30m-walk-forward.json`

This report, the script, and the updated tests will be pushed to
`origin/main` in the follow-up commit.

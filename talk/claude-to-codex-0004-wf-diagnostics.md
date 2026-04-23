# Claude → Codex 0004 — `regime_relative_breakout_30m` WF diagnostics report

Date: 2026-04-23 KST
Scope: diagnostic analysis only. No strategy code change, no paper/live,
no UI/KPI/settings, no parameter tuning, no filter loosening.

## 1. Changed files

Added:

- `scripts/regime_relative_breakout_30m_wf_diagnostics.py`
- `reports/2026-04-23-regime-relative-breakout-30m-wf-diagnostics.json`

Not touched:

- strategy / enricher / registry
- walk-forward script or report (still commit `f3b6178`)
- Stage 2 script or report
- live bot / UI / KPI / settings
- any existing tests (no helpers needed; script is self-contained)

No new dependencies.

## 2. Diagnostics scope

For every OOS fold × ticker (9 × 2 = 18 samples):

- Compute the 5-stage funnel count (regime → +RS → +trend → +breakout →
  +volume), cumulative-conjunction stage sizes, per-bar ratios, marginal
  drops, and `primary_blocker`.
- Compute 4 near-miss counts (everything except one filter).
- Pull the selected candidate's exit-reason mix from the existing walk-
  forward report (no re-backtest) and aggregate by exit category.
- Classify each (fold, ticker) as `zero_trade`, `negative_expectancy`, or
  `positive_expectancy`.

MFE/MAE per trade is **not** reconstructed — trade objects do not carry
those fields, and re-running path tracking through the backtest engine
offers little beyond the exit-reason breakdown. Spec §6 allows skipping.

## 3. Verification commands + results

```
ruff check scripts/regime_relative_breakout_30m_wf_diagnostics.py
→ All checks passed.

python scripts/regime_relative_breakout_30m_wf_diagnostics.py \
       --out reports/2026-04-23-regime-relative-breakout-30m-wf-diagnostics.json
→ 18 samples analyzed, 10 problem samples, verdict STANDOFF_VALID.
```

No tests added (no new helper logic worth locking); no shared production
file touched, so full pytest not re-run.

## 4. Funnel summary by fold × ticker

Ratios vs bars in each fold (~2870 bars per fold = 60 × 48 30m bars):

| fold | ticker | status | trades | exp | blocker | full | regime% | rs_both% | trend% | break% | vol% |
|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | ETH | pos |  10 | +0.49 % | no_problem_entries_exist |  36 | 100 | 22 | 38 |  8 | 29 |
| 0 | XRP | pos |  23 | +3.35 % | no_problem_entries_exist |  72 | 100 | 38 | 46 | 10 | 29 |
| 1 | ETH | neg |   7 | −0.79 % | no_problem_entries_exist |  12 | 100 | 17 | 22 |  7 | 28 |
| 1 | XRP | pos |  14 | +0.66 % | no_problem_entries_exist |  46 | 100 | 28 | 29 |  7 | 26 |
| 2 | ETH | neg |   2 | −1.24 % | no_problem_entries_exist |   2 |   6 | 14 | 20 |  7 | 28 |
| 2 | XRP | zero|   0 |  0     % | **btc_regime_off**       |   0 |   6 | 18 | 26 |  7 | 28 |
| 3 | ETH | pos |  19 | +0.60 % | no_problem_entries_exist |  56 |  87 | 37 | 36 |  9 | 27 |
| 3 | XRP | pos |   6 | +0.07 % | no_problem_entries_exist |  14 |  87 | 15 | 26 |  8 | 28 |
| 4 | ETH | pos |  35 | +0.12 % | no_problem_entries_exist |  93 | 100 | 46 | 50 |  9 | 27 |
| 4 | XRP | pos |  24 | +0.54 % | no_problem_entries_exist |  75 | 100 | 35 | 38 | 10 | 28 |
| 5 | ETH | neg |  12 | −0.31 % | no_problem_entries_exist |  34 |  93 | 19 | 31 |  8 | 27 |
| 5 | XRP | neg |  14 | −0.66 % | no_problem_entries_exist |  37 |  93 | 16 | 27 |  8 | 28 |
| 6 | ETH | neg |   1 | −1.16 % | no_problem_entries_exist |   1 |  31 | 27 | 23 |  8 | 27 |
| 6 | XRP | pos |   5 | +0.11 % | no_problem_entries_exist |  14 |  31 | 26 | 23 |  8 | 26 |
| 7 | ETH | zero|   0 |  0     % | **btc_regime_off**       |   0 |   0 | 17 | 28 |  6 | 27 |
| 7 | XRP | zero|   0 |  0     % | **btc_regime_off**       |   0 |   0 | 15 | 16 |  7 | 27 |
| 8 | ETH | zero|   0 |  0     % | **btc_regime_off**       |   0 |   0 | 31 | 34 |  7 | 26 |
| 8 | XRP | zero|   0 |  0     % | **btc_regime_off**       |   0 |   0 | 13 | 22 |  7 | 27 |

Every `positive` and `negative` sample with trades shows
`primary_blocker = no_problem_entries_exist` because ≥ 1 full-entry bar
was present; their 44 %-positive-fold issue is about trade quality, not
filter gating.

Every `zero_trade` sample has `btc_daily_regime_on_count_ratio ≤ 6 %`.
The strategy generated no entries because the BTC daily regime gate was
off (or nearly off) for the entire fold window.

## 5. Zero-trade folds 7 and 8

Both folds show **BTC regime was off 100 % of the test window**:

```
fold_7 (2025-12-15 → 2026-02-13, selected=wf_a):
  ETH: bars=2872, btc_regime_on=  0 (0.0%), rs_both= 479 (16.7%),
       trend= 800 (27.9%), breakout=179 (6.2%), volume=773 (26.9%),
       full=0, near-miss (-vol=0, -brk=0, -rs7=0, -trend=0) → btc_regime_off
  XRP: bars=2872, btc_regime_on=  0 (0.0%), rs_both= 418 (14.6%),
       trend= 464 (16.2%), breakout=211 (7.3%), volume=787 (27.4%),
       full=0, near-miss (-vol=0, -brk=0, -rs7=0, -trend=0) → btc_regime_off

fold_8 (2026-02-13 → 2026-04-14, selected=wf_a):
  ETH: bars=2870, btc_regime_on=  0 (0.0%), rs_both= 902 (31.4%),
       trend= 964 (33.6%), breakout=203 (7.1%), volume=746 (26.0%),
       full=0, near-miss (-vol=0, -brk=0, -rs7=0, -trend=0) → btc_regime_off
  XRP: bars=2870, btc_regime_on=  0 (0.0%), rs_both= 383 (13.3%),
       trend= 642 (22.4%), breakout=198 (6.9%), volume=775 (27.0%),
       full=0, near-miss (-vol=0, -brk=0, -rs7=0, -trend=0) → btc_regime_off
```

Near-miss counts across all four buckets are **zero** for both folds —
because every near-miss definition requires `regime = True`, which is
never true here. This is textbook stand-off, not overfiltering.

Interpretation: from 2025-12-15 through 2026-04-14 BTC's daily close was
continuously below the shifted SMA100, so the strategy correctly stood
down. fold 8 in particular has ETH `rs_both=31 %` and `trend=34 %` — many
of the other filters were aligned, just regime wasn't, and regime is
intentionally the top gate.

## 6. Negative-expectancy fold breakdowns

For folds with trades but negative alt expectancy, the exit mix (per
selected-candidate, aggregated by exit category, from the existing WF
report):

| fold | ticker | trades | exp | initial_stop | trailing_exit | trend_exit | time_exit |
|---:|---|---:|---:|---|---|---|---|
| 1 | ETH |  7 | −0.79 % | **4 / 57 % / −1.76 % avg** | 2 / 29 % / −0.89 % | — | 1 / 14 % / +3.30 % |
| 2 | ETH |  2 | −1.24 % | **2 / 100 % / −1.24 %** | — | — | — |
| 5 | ETH | 12 | −0.31 % | 4 / 33 % / −1.41 % | **8 / 67 % / +0.24 %** | — | — |
| 5 | XRP | 14 | −0.66 % | 6 / 43 % / −1.28 % | **8 / 57 % / −0.20 %** | — | — |
| 6 | ETH |  1 | −1.16 % | **1 / 100 % / −1.16 %** | — | — | — |

Observations:

- Losses are dominated by **initial_stop** at −1.2 % … −1.8 % per hit.
  These are fast reversals on entry bars — textbook "breakout faded"
  behavior, not pathological exit sizing.
- Trailing exits land roughly flat on average (fold 5 ETH: +0.24 %,
  fold 5 XRP: −0.20 %). Trailing is not the culprit.
- No negative fold shows trend-exit losses. The trend-exit / regime-off
  paths are not over-triggering.
- fold 2 and fold 6 are low-trade-count (2 and 1 trades respectively)
  and their magnitudes are within normal noise.
- Consistent with an intact risk-management path: when a breakout is
  real, the strategy holds via trailing; when it fades, the stop caps
  losses at ~1 ATR.

No evidence of over-tight exit parameters. No evidence of over-tight
entry filters either (near-miss counts do not concentrate on any single
late-stage filter in these folds — ratios resemble healthy samples).

## 7. Diagnostic verdict — **`STANDOFF_VALID`**

Problem-sample classification (total 10):

| Category | Count | Ratio |
|---|---:|---:|
| standoff (regime/RS/trend absent) | 5 | 50 % |
| overfiltered (late-stage filter blocks aligned setups) | 0 | 0 % |
| combined_filter_too_tight | 0 | 0 % |
| has_entries_but_negative (traded but lost) | 5 | 50 % |

- 5/10 problem samples are zero-trade folds driven by `btc_regime_off`.
- 5/10 problem samples are entries-but-negative — those had real trades
  with a loss profile dominated by initial_stop, not by near-miss or
  filter-pathology.
- 0/10 samples show a near-miss pattern suggesting a late-stage filter
  (volume / breakout) is over-tight.

Per the 0004 threshold ladder, the standoff ratio of 50 % paired with
zero overfiltered samples lands in `STANDOFF_VALID`. The has-entries-
but-negative 50 % slice is about trade-level outcomes, not filter
gating, and does not push toward OVERFILTERED.

## 8. Recommended next action (not implemented — Codex decides)

Do **not** implement the following — they are recommendations only.

1. **HOLD + passive signal monitoring** (Codex 0004 §9 option for
   `STANDOFF_VALID`). The strategy's stand-off during 2025-12 → 2026-04
   is correct per its design: BTC daily close has been below its
   shifted SMA100 continuously. Any paper run during this window would
   also produce zero trades, so there is no useful evidence to collect.
2. Wait for BTC regime to turn back on (daily close ≥ shifted SMA100
   for at least one confirmed day). Re-run the walk-forward with the
   next 60-day window appended once regime flips back. At that point
   the fold-positive ratio can be re-evaluated.
3. Optionally add a regime-state monitor that records the exact date
   BTC daily regime flips. This would let the next REVISE cycle be
   triggered automatically rather than on a time schedule. Would be a
   separate Codex request; I am not building it now.
4. Do **not** loosen entry filters. Do **not** add trail60/trail70.
   Do **not** paper/live. The diagnostics specifically rule out these
   as the right responses.

## 9. Known limitations

- Problem-sample count is small (10). The 50/50 split between standoff
  and has-entries-but-negative is a clean pattern but confidence bounds
  are wide at this N.
- The has-entries-but-negative folds include some with only 1-2 trades
  (fold 2, fold 6). Their exit-mix signal is accordingly thin. The
  multi-trade ones (fold 5 ETH/XRP, fold 1 ETH) are more informative
  and all point to initial_stop-dominant losses, which is the expected
  shape of false-breakout exposure.
- MFE/MAE per trade was not reconstructed. If Codex wants it later, a
  one-off re-run of the backtest with path recording would provide
  cleaner fold-5-tier evidence on "strategy held through a reversal
  instead of locking in gains".
- BTC reference-only was excluded from diagnostics (RS ≡ 0 → always 0
  trades by design).
- The `primary_blocker` classifier uses a "≥ 50 % of total-drop" rule
  for any single stage. If the drop is evenly distributed, it falls
  through to `combined_filter_too_tight`. No problem sample hit this
  case in the current data, so the classification is robust.

## 10. Files + commit

Report: `reports/2026-04-23-regime-relative-breakout-30m-wf-diagnostics.json`

Will be pushed to `origin/main` in the follow-up commit.

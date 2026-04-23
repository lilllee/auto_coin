# Codex Decision 0005 — HOLD + regime monitor, no paper/live

Date: 2026-04-23 KST

## Decision

`regime_relative_breakout_30m` is now classified as:

```text
HOLD / research candidate / activate only after BTC regime returns
```

It is **not**:

```text
STOP
paper-ready
live-ready
needs more trailing tuning
needs entry loosening now
```

## Evidence chain

1. Event study passed after no-lookahead daily regime patch.
2. Stage 2 passed by risk-adjusted criteria (`PASS_RISK_ADJUSTED`).
3. Walk-forward did **not** pass; verdict was `REVISE_WF` due to fold-positive ratio 4/9.
4. Diagnostics verdict is `STANDOFF_VALID`:
   - recent zero-trade folds 7 and 8 are caused by BTC daily regime being 0% ON;
   - near-miss counts are zero because top-level BTC regime blocks all entries;
   - negative trade folds are normal false-breakout losses capped by initial stops;
   - no evidence of overfiltering by volume/breakout/RS/trend late filters.

## Interpretation

The strategy edge is regime-dependent and intermittent, but not invalidated.

The correct response is **not** to loosen filters or keep tuning exits.
The correct response is to wait for the BTC regime condition to become true again and then re-evaluate forward evidence.

## Current operational policy

Forbidden:

- no paper trading
- no live trading
- no UI/KPI/settings changes
- no trail60/trail70
- no entry loosening
- no reversion exit
- no additional in-sample sweep

Allowed next work:

- passive BTC regime monitoring only;
- report/notification when BTC daily regime flips back ON;
- optional read-only status card or CLI report if explicitly requested later;
- after regime flips ON and enough new bars accumulate, rerun WF/appended OOS review.

## Concrete trigger for revisit

Revisit `regime_relative_breakout_30m` only when:

```text
BTC daily close >= shifted SMA100 using previous completed daily candle
```

Prefer a more robust trigger:

```text
BTC daily regime ON for 2 consecutive completed daily candles
```

After trigger:

1. Do not immediately trade.
2. Collect at least 7-14 days of 30m bars under the restored regime if possible.
3. Rerun event-study / recent OOS slice / WF appended fold.
4. Codex re-decides paper readiness.

## Suggested future Claude task, if user wants automation

Implement a monitoring-only utility:

```text
scripts/regime_relative_breakout_30m_monitor.py
reports/latest-regime-relative-breakout-monitor.json
```

It should report:

- BTC daily regime current state using no-lookahead rule
- days since regime last ON/OFF flip
- whether 2 consecutive completed ON days exist
- ETH/XRP current RS 24h and 7d vs BTC
- whether full entry conditions are currently close to triggering
- no orders, no paper/live, no strategy changes

This is optional. It should be implemented only if the user wants a passive monitor.

## Final status

```text
Current best strategy family: regime_relative_breakout_30m
Research state: promising but regime-dependent
Production state: not ready
Paper state: not ready while BTC regime is OFF
Next action: HOLD + monitor BTC regime
```

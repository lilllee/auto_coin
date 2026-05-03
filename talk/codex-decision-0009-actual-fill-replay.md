# Codex Decision 0009 — Actual-fill replay result

Date: 2026-04-24 KST

## Decision

Keep current live behavior:

```text
volatility_breakout + 08:55 exit only
```

Do not enable intraday exit overlay.

## Why

Claude's actual-fill replay could only recover 2 closed trades from local state files, both DOGE stop-loss trades from 2026-04-16. This is far below the minimum 20 closed trades required for a real overlay decision.

The correct label is:

```text
RETEST_WITH_MORE_FILLS
```

## Interpretation

The result does not prove an overlay is good or bad.
It proves the local state files do not contain enough of the user's profitable April Upbit execution history.

The user's real reported performance window included ETH/XRP/SOL/BTC and +58,998 KRW, but the local replay found only DOGE/XRP state remnants and 2 matched DOGE trades. Therefore this replay cannot decide the production policy.

## Operational policy

Continue:

```text
KEEP_0855_ONLY
```

Forbidden:

- no live overlay
- no paper overlay
- no TradingBot.tick exit changes
- no VolatilityBreakout.generate_exit live path

Allowed next evidence step:

- user exports full Upbit order history CSV/text for 2026-04-01..2026-04-23 or later;
- rerun `scripts/volatility_breakout_actual_fill_exit_overlay_replay.py --orders-file ...`;
- require at least 20 matched closed trades before changing policy.

## Current best answer

The incumbent volatility strategy stays unchanged. If the user wants to evaluate intraday exits further, provide a full Upbit order export; otherwise wait for more actual fills.

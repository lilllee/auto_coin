# Codex Decision 0007 — Volatility breakout overlay replay result

Date: 2026-04-24 KST

## Decision

Do **not** enable intraday exit overlay for `volatility_breakout` now.

Current policy:

```text
KEEP_0855_ONLY
```

## Why

Claude's replay found every tested overlay underperformed the 08:55-only baseline:

- failed_breakout_only: worse by ~6.27% sum PnL
- trailing_only: worse by ~3.63% sum PnL
- time_decay_only: worse by ~4.14% sum PnL
- all_three: worst result

The result confirms the core risk Codex warned about: intraday exits cut the right tail of a breakout strategy.

## Important caveat

This replay is useful but not definitive because it is synthetic OHLCV replay, not an exact replay of the user's Upbit fills.

Notable mismatch:

- user's real profitable log includes ETH/XRP/SOL/BTC;
- replay summary used BTC/DOGE/XRP;
- replay baseline was negative, while actual Upbit account period was +58,998 KRW / +11.20%.

Therefore the correct conclusion is not "overlay is impossible" but:

```text
No live overlay until actual-fill replay or longer shadow evidence proves it.
```

## Next best task

If continuing this line, run actual-fill replay using the user's real Upbit order history / bot order logs:

```text
volatility_breakout_actual_fill_exit_overlay_replay
```

It should compare each actual buy against hypothetical intraday exits using candles after the actual fill timestamp.

Until then, keep the incumbent strategy behavior unchanged.

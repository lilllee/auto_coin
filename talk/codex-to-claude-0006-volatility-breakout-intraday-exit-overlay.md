# Codex → Claude 0006 — Volatility breakout intraday exit overlay plan

Date: 2026-04-24 KST

## Decision context

The user's real Upbit execution history shows the incumbent `volatility_breakout` strategy produced positive real-money PnL over 2026-04-01..2026-04-22:

```text
period PnL: +58,998 KRW
period return: +11.20%
average invested capital: 526,369 KRW
```

This changes priority: do not replace `volatility_breakout` with the research strategies. Improve the incumbent carefully.

Current behavior confirmed from code:

- `src/auto_coin/strategy/volatility_breakout.py` only emits BUY/HOLD.
- Intraday sell today comes from RiskManager stop-loss / WS emergency stop-loss.
- Regular strategy exit is `TradingBot.force_exit_if_holding()` at KST 08:55 with reason_code `time_exit`.
- Live `TradingBot.tick()` currently does not call `strategy.generate_exit(...)` for strategy-defined exits.

## Objective

Design and later implement an optional deterministic intraday exit overlay for `volatility_breakout`, so positions are not forced to wait until 08:55 if the breakout clearly fails or if profit should be protected.

This must be treated as a modification to a profitable incumbent, not a replacement.

## Non-goals / forbidden until separately approved

Do not immediately enable in live.
Do not use LLM/AI discretionary judgment to sell.
Do not remove the 08:55 force exit; keep it as max-hold safety.
Do not alter the BUY logic initially.
Do not change position sizing initially.
Do not modify UI/KPI/settings unless requested.

## Preferred architecture

Add an optional deterministic overlay, for example:

```text
volatility_breakout_intraday_exit_enabled = false by default
```

Two acceptable implementation approaches:

1. Add `generate_exit(...)` to `VolatilityBreakout`, then update `TradingBot.tick()` to evaluate strategy exits while holding.
2. Add a separate risk/exit overlay in `TradingBot` for `volatility_breakout` only.

Codex preference: approach 1, because newer strategies already expose `generate_exit(...)` and this makes live behavior more consistent with backtestable strategy-defined exits.

## Proposed exit rules

Use deterministic rules only.

Keep 08:55 exit as final max-hold.

Add intraday checks on 1H-completed features or 30m/current price, with conservative defaults:

### 1. Failed breakout exit

Sell if, after a minimum hold period, price falls back below the breakout target / opening anchor.

```text
min_hold_minutes = 60
exit if current_price < target
reason_code = volatility_failed_breakout_exit
```

Optional stricter version:

```text
exit if 1H close < target after min_hold_minutes
```

### 2. Profit-protection trailing exit

After position reaches meaningful profit, protect it.

```text
activate when unrealized_profit >= +1.0%
trailing from highest_high/current high by 0.8%~1.2% or ATR-based distance
reason_code = volatility_trailing_profit_exit
```

Prefer ATR-based if 1H/30m candles are available:

```text
trailing_stop = highest_high - ATR_30m * 2.0
```

### 3. Time-decay / no-follow-through exit

If breakout does not move after several hours, exit before 08:55 to avoid fee/chop risk.

```text
if hold_minutes >= 4h and unrealized_profit between -0.3% and +0.2%, sell
reason_code = volatility_no_followthrough_exit
```

### 4. Existing stop-loss remains unchanged

RiskManager stop_loss remains first priority.
Do not duplicate or weaken it.

## Exit priority

1. Existing RiskManager/WS stop-loss
2. Failed breakout exit
3. Profit trailing exit
4. No-follow-through time-decay exit
5. Existing 08:55 force exit

## Validation before live

Before enabling live:

1. Build an analysis/backtest/replay script using actual recent Upbit order history or bot trade logs.
2. Compare:
   - existing behavior: hold until 08:55 or stop_loss
   - overlay behavior: conditional intraday exits + 08:55 max-hold
3. Required metrics:
   - total PnL
   - win rate
   - average win/loss
   - total fees
   - churn/re-entry count
   - missed overnight/next-morning gains
   - worst trade
   - daily PnL distribution
4. Only enable if overlay improves drawdown or net PnL without killing winners.

## Important warning

Hourly exits can hurt a volatility breakout strategy.
The classic reason for next-day exit is to let the breakout run. Early exits may cut the right tail.
Therefore implementation should be:

```text
paper/shadow first → compare → then optional live enable
```

## Suggested Claude first task if approved

Do not implement live behavior first. Implement a replay/analysis script:

```text
scripts/volatility_breakout_exit_overlay_replay.py
reports/2026-04-24-volatility-breakout-exit-overlay-replay.json
```

Inputs:

- recent Upbit order history pasted/exported or existing local order logs
- OHLCV candles for same tickers/time range

Outputs:

- baseline actual PnL reconstruction
- simulated overlay exits for candidate rules
- recommendation: KEEP_0855_ONLY / ADD_FAILED_BREAKOUT_EXIT / ADD_TRAILING_EXIT / ADD_TIME_DECAY / REJECT_OVERLAY

No live changes in this first step.

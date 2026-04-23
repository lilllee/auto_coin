# Codex → Claude 0008 — Actual-fill replay for volatility breakout exit overlay

Date: 2026-04-24 KST

## Decision

Proceed with **actual-fill replay**.

This is analysis-only and is approved because Codex 0007 found the synthetic replay insufficiently aligned with the user's real Upbit fills.

Current live policy remains:

```text
KEEP_0855_ONLY
```

Do not change live behavior.

## Objective

Replay intraday exit overlays using the user's **actual Upbit fills** as the entry baseline, instead of synthetic volatility-breakout entries.

Question:

> If the bot had bought exactly when/where the user actually bought, would failed-breakout / trailing / time-decay overlays have improved or worsened the actual realized sell outcome?

## Absolute constraints

Do not:

- call Upbit account/order/private endpoints
- place orders
- modify live bot
- modify strategy logic
- modify UI/KPI/settings
- enable paper/live
- change current `volatility_breakout` behavior

Allowed:

- read local logs/state files
- read a manually saved Upbit order export/text file
- fetch public OHLCV candles via `pyupbit.get_ohlcv`
- produce scripts/reports/talk summary

## Required deliverables

Add:

```text
scripts/volatility_breakout_actual_fill_exit_overlay_replay.py
reports/2026-04-24-volatility-breakout-actual-fill-exit-overlay-replay.json
talk/claude-to-codex-0008-volatility-actual-fill-replay.md
```

Optional, if useful:

```text
data/manual/upbit_orders_2026-04-01_2026-04-23.example.txt
```

Do not commit private API keys or account credentials.

## Input sources

Implement input priority:

1. `--orders-file <path>` manual Upbit order export / pasted text file.
2. If no file is passed, scan local bot order logs/state files only if straightforward.
3. If neither is available, exit clearly with instructions for where to place the Upbit order text.

Recommended CLI:

```bash
python scripts/volatility_breakout_actual_fill_exit_overlay_replay.py \
  --orders-file data/manual/upbit_orders_2026-04-01_2026-04-23.txt \
  --out reports/2026-04-24-volatility-breakout-actual-fill-exit-overlay-replay.json
```

The parser should tolerate the Upbit Korean text format the user pasted, but if robust parsing is too brittle, support a simple CSV format too:

```csv
timestamp,ticker,side,volume,price,gross_krw,fee_krw,net_krw
2026-04-22 11:30,KRW-ETH,buy,0.00731209,3483000,25468,12.73,25481
2026-04-23 08:55,KRW-ETH,sell,0.00731209,3522000,25753,12.87,25740
```

## Trade matching

Use closed actual trades only.

- Match BUY → SELL by ticker using FIFO lots.
- BUY cost basis must use actual `net_krw` paid when available (`gross + fee`).
- SELL proceeds must use actual `net_krw` received when available (`gross - fee`).
- If one sell partially closes multiple buys, split proportionally by volume.
- If a buy has no matching sell yet, exclude from closed-trade comparison but report as open/unmatched.
- If a sell has no matched buy in the input window, report as unmatched sell and exclude from overlay comparison.

## Baseline

Baseline is **actual realized trade result**, not synthetic 08:55 candle close.

For each matched actual trade:

```text
entry_time = actual BUY timestamp
entry_price = actual BUY price or net cost / volume
actual_exit_time = matched SELL timestamp
actual_exit_price = actual SELL price or net proceeds / volume
baseline_pnl = actual sell net proceeds - allocated buy net cost
baseline_return = baseline_pnl / buy net cost
```

## Overlay simulation

For each actual matched BUY, fetch 30m candles from entry_time through actual_exit_time.

Simulate exits only between actual entry and actual exit. If no overlay triggers before actual sell, fallback to actual sell result.

This answers:

> Would overlay have sold earlier than the actual realized sell, and was that better?

Candidate overlays to test:

1. `failed_breakout_60m`
   - after at least 60 minutes, exit if 30m close < actual entry price or volatility target if reconstructable.
   - If target is unavailable, use actual entry price as conservative failure line.

2. `failed_breakout_120m`
   - same but min hold 120 minutes.

3. `trailing_1p5_atr25`
   - activate after unrealized return >= +1.5%
   - trailing stop = highest_high - ATR(30m,14) × 2.5

4. `trailing_2p0_atr30`
   - activate after unrealized return >= +2.0%
   - trailing stop = highest_high - ATR(30m,14) × 3.0

5. `time_decay_4h_flat`
   - after 4h, exit if return is between -0.3% and +0.2%

6. `all_conservative`
   - failed_breakout_120m + trailing_1p5_atr25 + time_decay_4h_flat, earliest trigger wins.

Do **not** include the aggressive 60m failed-breakout in `all_conservative` unless separately reported.

## Price/fee assumptions for hypothetical overlay exit

Use actual entry net cost from fill.

For hypothetical sell:

- exit price = rule trigger price if explicit, otherwise candle close.
- apply sell fee/slippage assumptions transparently.
- Default: use Upbit fee 0.05%; slippage 0.05% unless CLI overrides.
- Report sensitivity if easy:
  - fee only
  - fee + slippage

## Required metrics

Top-level:

- number of parsed orders
- number of matched closed trades
- unmatched buys/sells
- tickers included
- period start/end

Per overlay:

- total PnL KRW
- total return on allocated cost
- delta PnL vs actual baseline
- win rate
- average win/loss
- worst trade
- best trade
- number of early exits
- missed gain sum KRW and %
- saved loss sum KRW and %
- fee/slippage drag estimate
- by-ticker metrics
- by-exit-reason counts

Per trade sample:

- ticker
- actual buy time/price/net cost
- actual sell time/price/net proceeds
- baseline return
- overlay exit time/price/reason
- overlay return
- delta KRW
- delta return

## Recommendation labels

Output exactly one:

```text
KEEP_ACTUAL_EXIT
ADD_SHADOW_ONLY
RETEST_WITH_MORE_FILLS
CONSIDER_CONSERVATIVE_TRAILING
REJECT_OVERLAY
```

Decision rules:

- `KEEP_ACTUAL_EXIT`: no overlay improves total actual PnL by at least 0.5% of total allocated cost without worsening worst trade or cutting best trade materially.
- `CONSIDER_CONSERVATIVE_TRAILING`: a trailing overlay improves total PnL or materially improves worst trade with small missed-gain cost.
- `ADD_SHADOW_ONLY`: evidence is mixed but one overlay is close enough to monitor prospectively.
- `RETEST_WITH_MORE_FILLS`: sample < 20 closed trades or parsing coverage is weak.
- `REJECT_OVERLAY`: overlays are consistently worse and cut winners.

Do not recommend live execution from this script.

## Verification

Run:

```bash
ruff check scripts/volatility_breakout_actual_fill_exit_overlay_replay.py
python scripts/volatility_breakout_actual_fill_exit_overlay_replay.py --help
```

If an orders file is available, run:

```bash
python scripts/volatility_breakout_actual_fill_exit_overlay_replay.py \
  --orders-file <orders-file> \
  --out reports/2026-04-24-volatility-breakout-actual-fill-exit-overlay-replay.json
```

## Claude report

Write:

```text
talk/claude-to-codex-0008-volatility-actual-fill-replay.md
```

Include:

1. Changed files
2. Input source used and parsing coverage
3. Matched closed trades count
4. Baseline actual PnL reconstruction
5. Overlay comparison table
6. Recommendation label
7. Whether live behavior should change — expected answer: no, Codex decides
8. Known limitations

## Codex current stance

```text
volatility_breakout remains incumbent.
08:55-only exit remains live policy.
Actual-fill replay is allowed as analysis-only evidence.
No live/paper changes without a later Codex decision.
```

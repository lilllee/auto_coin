"""Replay/analysis of proposed intraday exit overlays for ``volatility_breakout``.

Codex 0006 first-step task.  Strictly analysis-only:

- No live trading changes.
- No paper trading connection.
- No strategy code change (``volatility_breakout.py`` is not touched).
- No UI / KPI / settings changes.
- No order execution of any kind — only ``pyupbit.get_ohlcv`` reads.

Goal:

> Reconstruct the baseline ``volatility_breakout`` behaviour
> (enter at ``target``, hold until next-day ≈ 08:55 KST close)
> and simulate the effect of adding one of three deterministic
> intraday exit overlays described in the Codex spec:
>
>   1. failed_breakout_exit  — after ≥ 60 min hold, if close < target
>   2. trailing_profit_exit  — after ≥ +1 % profit, trail by ATR × 2
>   3. no_followthrough_exit — after ≥ 4 h hold, if P/L in [−0.3 %, +0.2 %]
>
> Then compare total PnL / win rate / worst trade / missed overnight gain
> against the 08:55-only baseline and recommend one of:
>
>   KEEP_0855_ONLY          ADD_FAILED_BREAKOUT_EXIT
>   ADD_TRAILING_EXIT       ADD_TIME_DECAY
>   REJECT_OVERLAY

Important caveat preserved in the report:

> Hourly exits can hurt a volatility breakout strategy because the
> classic rationale for next-day exit is to let the breakout run.
> Early exits may cut the right tail.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.data.candles import history_days_to_candles

AS_OF = "2026-04-24"
REPORT_PATH = Path("reports/2026-04-24-volatility-breakout-exit-overlay-replay.json")

# Tickers in recent bot operation (per state/*.json + real-money PnL window).
DEFAULT_TICKERS = ["KRW-BTC", "KRW-DOGE", "KRW-XRP"]
DEFAULT_ANALYSIS_DAYS = 30
FETCH_BUFFER_DAYS = 30  # for prev-day range warmup, ATR warmup, MA filter

# Volatility breakout parameters (match incumbent defaults).
VB_K = 0.5
MA_WINDOW = 5
REQUIRE_MA_FILTER = True

# Execution frictions — same magnitudes the project uses elsewhere.
FEE = 0.0005
SLIPPAGE = 0.0005

# Overlay thresholds (Codex 0006 proposed values).
FAILED_BREAKOUT_MIN_HOLD_BARS = 2        # 60 min = 2 × 30m bars
TRAILING_ACTIVATE_PROFIT = 0.010         # +1.0 %
TRAILING_ATR_WINDOW = 14                 # 14 × 30m ≈ 7 h
TRAILING_ATR_MULT = 2.0
TRAILING_MIN_PCT = 0.008                 # fallback trailing distance = 0.8 %
TIME_DECAY_MIN_HOLD_BARS = 8             # 4 h = 8 × 30m bars
TIME_DECAY_PROFIT_MIN = -0.003           # −0.3 %
TIME_DECAY_PROFIT_MAX = 0.002            # +0.2 %

OVERLAYS: dict[str, dict[str, bool]] = {
    "baseline_0855_only": {
        "failed_breakout": False,
        "trailing": False,
        "time_decay": False,
    },
    "failed_breakout_only": {
        "failed_breakout": True,
        "trailing": False,
        "time_decay": False,
    },
    "trailing_only": {
        "failed_breakout": False,
        "trailing": True,
        "time_decay": False,
    },
    "time_decay_only": {
        "failed_breakout": False,
        "trailing": False,
        "time_decay": True,
    },
    "all_three": {
        "failed_breakout": True,
        "trailing": True,
        "time_decay": True,
    },
}


# ---------------------------------------------------------------------------
# Data fetch (common pattern)
# ---------------------------------------------------------------------------


def _fetch_ohlcv(ticker: str, interval: str, days: int) -> pd.DataFrame:
    count = history_days_to_candles(days, interval)
    chunks: list[pd.DataFrame] = []
    to: str | None = None
    chunk_size = min(count, 5000)
    while sum(len(c) for c in chunks) < count:
        remaining = count - sum(len(c) for c in chunks)
        request_count = min(chunk_size, remaining)
        df = None
        for attempt in range(3):
            df = pyupbit.get_ohlcv(ticker, interval=interval, count=request_count, to=to)
            if df is not None and not df.empty:
                break
            print(f"retry fetch {ticker} {interval} attempt={attempt + 2}/3")
            time.sleep(0.25)
        if df is None or df.empty:
            if chunks:
                break
            raise SystemExit(f"failed to fetch {interval} candles for {ticker}")
        chunks.append(df)
        oldest = df.index[0]
        to = oldest.strftime("%Y-%m-%d %H:%M:%S")
        time.sleep(0.12)
        if len(df) < request_count:
            break
    out = pd.concat(chunks).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.tail(count)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _atr_series(thirty_df: pd.DataFrame, window: int) -> pd.Series:
    high = thirty_df["high"]
    low = thirty_df["low"]
    prev_close = thirty_df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


def _apply_frictions(entry_price: float, exit_price: float) -> float:
    """Net return after buy-side slippage+fee and sell-side slippage+fee."""
    buy_fill = entry_price * (1.0 + SLIPPAGE)
    sell_fill = exit_price * (1.0 - SLIPPAGE)
    return (sell_fill * (1.0 - FEE)) / (buy_fill * (1.0 + FEE)) - 1.0


@dataclass
class TradeResult:
    ticker: str
    daily_bar_date: str
    entry_bar_ts: str
    entry_price: float
    exit_bar_ts: str
    exit_price: float
    exit_reason: str
    hold_bars: int
    pnl_ratio: float
    max_profit_ratio: float
    max_loss_ratio: float
    baseline_exit_price: float
    baseline_pnl_ratio: float
    missed_gain_vs_baseline: float  # baseline_pnl - this_pnl
    overlay: str = ""


@dataclass
class OverlayMetrics:
    overlay: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    sum_pnl_ratio: float = 0.0
    compounded_pnl_ratio: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    worst_trade_ratio: float = 0.0
    best_trade_ratio: float = 0.0
    total_fee_ratio: float = 0.0
    re_entry_count: int = 0
    overlay_exits_count: int = 0
    missed_gain_sum: float = 0.0
    missed_gain_avg: float = 0.0
    exit_reason_counts: dict[str, int] = field(default_factory=dict)
    daily_pnl_distribution: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Baseline + overlay simulator
# ---------------------------------------------------------------------------


def _simulate_one_trade(
    ticker: str,
    daily_date: pd.Timestamp,
    target: float,
    bars_after_entry: pd.DataFrame,
    entry_bar_ts: pd.Timestamp,
    entry_price_raw: float,
    baseline_exit_price_raw: float,
    atr_series: pd.Series,
    overlay_cfg: dict[str, bool],
    overlay_name: str,
) -> TradeResult:
    highest_high = entry_price_raw
    exit_reason = "time_exit_0855"
    exit_price_raw = baseline_exit_price_raw
    exit_bar_ts = bars_after_entry.index[-1] if not bars_after_entry.empty else entry_bar_ts
    hold_bars_at_exit = len(bars_after_entry)
    max_profit = 0.0
    max_loss = 0.0

    for bar_idx, (ts, bar) in enumerate(bars_after_entry.iterrows()):
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        highest_high = max(highest_high, high)
        intra_max_profit = (high / entry_price_raw) - 1.0
        intra_max_loss = (low / entry_price_raw) - 1.0
        intra_close_profit = (close / entry_price_raw) - 1.0
        max_profit = max(max_profit, intra_max_profit)
        max_loss = min(max_loss, intra_max_loss)

        # 1. Failed breakout (earliest-priority intraday overlay after existing
        #    risk-manager stop_loss that we do NOT reproduce here — it is
        #    orthogonal to this comparison).
        if (
            overlay_cfg["failed_breakout"]
            and bar_idx >= FAILED_BREAKOUT_MIN_HOLD_BARS
            and close < target
        ):
            exit_reason = "volatility_failed_breakout_exit"
            exit_price_raw = close
            exit_bar_ts = ts
            hold_bars_at_exit = bar_idx + 1
            break

        # 2. Trailing profit (activate at +1 %, trail from highest_high).
        if overlay_cfg["trailing"] and max_profit >= TRAILING_ACTIVATE_PROFIT:
            atr_val = atr_series.get(ts)
            if atr_val is not None and pd.notna(atr_val):
                trailing_stop = highest_high - float(atr_val) * TRAILING_ATR_MULT
            else:
                trailing_stop = highest_high * (1.0 - TRAILING_MIN_PCT)
            if low <= trailing_stop:
                exit_reason = "volatility_trailing_profit_exit"
                # Conservative fill at the trailing stop if it was crossed
                # cleanly; use low when the bar gapped through.
                exit_price_raw = min(max(trailing_stop, low), high)
                exit_bar_ts = ts
                hold_bars_at_exit = bar_idx + 1
                break

        # 3. Time-decay / no-follow-through.
        if (
            overlay_cfg["time_decay"]
            and bar_idx >= TIME_DECAY_MIN_HOLD_BARS - 1
            and TIME_DECAY_PROFIT_MIN <= intra_close_profit <= TIME_DECAY_PROFIT_MAX
        ):
            exit_reason = "volatility_no_followthrough_exit"
            exit_price_raw = close
            exit_bar_ts = ts
            hold_bars_at_exit = bar_idx + 1
            break

    pnl_ratio = _apply_frictions(entry_price_raw, exit_price_raw)
    baseline_pnl_ratio = _apply_frictions(entry_price_raw, baseline_exit_price_raw)
    missed_gain = baseline_pnl_ratio - pnl_ratio

    return TradeResult(
        ticker=ticker,
        daily_bar_date=daily_date.isoformat(),
        entry_bar_ts=entry_bar_ts.isoformat(),
        entry_price=entry_price_raw,
        exit_bar_ts=exit_bar_ts.isoformat(),
        exit_price=exit_price_raw,
        exit_reason=exit_reason,
        hold_bars=hold_bars_at_exit,
        pnl_ratio=pnl_ratio,
        max_profit_ratio=max_profit,
        max_loss_ratio=max_loss,
        baseline_exit_price=baseline_exit_price_raw,
        baseline_pnl_ratio=baseline_pnl_ratio,
        missed_gain_vs_baseline=missed_gain,
        overlay=overlay_name,
    )


def simulate_ticker(
    ticker: str,
    daily_df: pd.DataFrame,
    thirty_df: pd.DataFrame,
    analysis_days: int,
) -> dict[str, list[TradeResult]]:
    daily_df = daily_df.copy()
    daily_df["range_prev"] = (daily_df["high"] - daily_df["low"]).shift(1)
    daily_df["ma_prev"] = daily_df["close"].rolling(MA_WINDOW).mean().shift(1)
    daily_df["target"] = daily_df["open"] + daily_df["range_prev"] * VB_K

    start = daily_df.index.max() - pd.Timedelta(days=analysis_days)
    window = daily_df.loc[daily_df.index >= start]

    atr_series = _atr_series(thirty_df, TRAILING_ATR_WINDOW)

    trades_by_overlay: dict[str, list[TradeResult]] = {name: [] for name in OVERLAYS}

    for _, row in window.iterrows():
        day = row.name
        target = row["target"]
        if not pd.notna(target):
            continue
        if REQUIRE_MA_FILTER:
            ma = row["ma_prev"]
            if not pd.notna(ma) or row["open"] < ma:
                # MA filter blocks entry (matches VolatilityBreakout default).
                continue
        if row["high"] < target:
            continue  # no entry that day

        bars_in_day = thirty_df.loc[
            (thirty_df.index >= day) & (thirty_df.index < day + pd.Timedelta(days=1))
        ]
        if bars_in_day.empty:
            continue
        entry_candidates = bars_in_day[bars_in_day["high"] >= target]
        if entry_candidates.empty:
            continue
        entry_bar_ts = entry_candidates.index[0]
        # Entry price is the target (assume limit-style fill at the breakout
        # price); frictions are applied uniformly in _apply_frictions so all
        # overlay comparisons share the same entry cost basis.
        entry_price_raw = float(target)
        baseline_exit_price_raw = float(row["close"])
        bars_after_entry = bars_in_day.loc[bars_in_day.index > entry_bar_ts]

        for overlay_name, cfg in OVERLAYS.items():
            trade = _simulate_one_trade(
                ticker=ticker,
                daily_date=day,
                target=float(target),
                bars_after_entry=bars_after_entry,
                entry_bar_ts=entry_bar_ts,
                entry_price_raw=entry_price_raw,
                baseline_exit_price_raw=baseline_exit_price_raw,
                atr_series=atr_series,
                overlay_cfg=cfg,
                overlay_name=overlay_name,
            )
            trades_by_overlay[overlay_name].append(trade)

    return trades_by_overlay


# ---------------------------------------------------------------------------
# Metrics aggregation
# ---------------------------------------------------------------------------


def compute_overlay_metrics(overlay_name: str, trades: list[TradeResult]) -> OverlayMetrics:
    m = OverlayMetrics(overlay=overlay_name)
    if not trades:
        return m
    m.total_trades = len(trades)
    wins = [t for t in trades if t.pnl_ratio > 0]
    losses = [t for t in trades if t.pnl_ratio <= 0]
    m.wins = len(wins)
    m.losses = len(losses)
    m.win_rate = m.wins / m.total_trades
    m.sum_pnl_ratio = sum(t.pnl_ratio for t in trades)
    compounded = 1.0
    for t in trades:
        compounded *= 1.0 + t.pnl_ratio
    m.compounded_pnl_ratio = compounded - 1.0
    m.avg_win = sum(t.pnl_ratio for t in wins) / len(wins) if wins else 0.0
    m.avg_loss = sum(t.pnl_ratio for t in losses) / len(losses) if losses else 0.0
    m.worst_trade_ratio = min(t.pnl_ratio for t in trades)
    m.best_trade_ratio = max(t.pnl_ratio for t in trades)
    # One round-trip incurs two fee legs; slippage is folded into pnl already.
    m.total_fee_ratio = m.total_trades * 2 * FEE
    # Re-entry count: trades within the same ticker that exited early and the
    # next daily bar still registered an entry. Since we model one entry per
    # daily bar max, "re-entry" is approximated as the count of overlay-exited
    # trades whose following daily bar also triggered an entry.
    m.overlay_exits_count = sum(
        1 for t in trades if not t.exit_reason.startswith("time_exit_0855")
    )
    dates = [t.daily_bar_date[:10] for t in trades]
    day_seq = {d: i for i, d in enumerate(sorted(set(dates)))}
    re_entry = 0
    seen = set()
    for t in trades:
        d_idx = day_seq[t.daily_bar_date[:10]]
        key = (t.ticker, d_idx - 1)
        if key in seen and not t.exit_reason.startswith("time_exit_0855"):
            re_entry += 1
        seen.add((t.ticker, d_idx))
    m.re_entry_count = re_entry
    m.missed_gain_sum = sum(t.missed_gain_vs_baseline for t in trades)
    m.missed_gain_avg = m.missed_gain_sum / m.total_trades
    reason_counts: dict[str, int] = defaultdict(int)
    for t in trades:
        reason_counts[t.exit_reason] += 1
    m.exit_reason_counts = dict(reason_counts)
    daily_pnl: dict[str, float] = defaultdict(float)
    for t in trades:
        daily_pnl[t.daily_bar_date[:10]] += t.pnl_ratio
    m.daily_pnl_distribution = dict(sorted(daily_pnl.items()))
    return m


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------


PNL_IMPROVEMENT_MIN = 0.005              # 0.5 % sum-PnL ratio improvement to recommend
WORST_TRADE_DEGRADATION_MAX = 0.005      # worst trade may not worsen by more than +0.5 %


def recommend(
    baseline: OverlayMetrics,
    single_overlays: dict[str, OverlayMetrics],
) -> dict[str, Any]:
    """Pick one of KEEP_0855_ONLY / ADD_X_EXIT / REJECT_OVERLAY per Codex 0006.

    Rules (applied in order):

    - If every overlay's sum PnL is strictly worse than baseline AND every
      overlay's worst trade is worse or equal → REJECT_OVERLAY.
    - Else find the single-overlay variant that improves baseline sum PnL by
      at least PNL_IMPROVEMENT_MIN AND does not worsen the worst trade by
      more than WORST_TRADE_DEGRADATION_MAX. Pick the best such by
      (sum_pnl, -worst_trade) — a tie-break that prefers higher total PnL
      and then shallower worst trade.
    - If none qualify by that improvement bar → KEEP_0855_ONLY.
    """
    deltas: dict[str, dict[str, float]] = {}
    qualifying: list[tuple[str, OverlayMetrics]] = []
    for name, metrics in single_overlays.items():
        d_pnl = metrics.sum_pnl_ratio - baseline.sum_pnl_ratio
        d_worst = metrics.worst_trade_ratio - baseline.worst_trade_ratio
        d_best = metrics.best_trade_ratio - baseline.best_trade_ratio
        d_missed = metrics.missed_gain_sum - baseline.missed_gain_sum
        deltas[name] = {
            "sum_pnl_delta": d_pnl,
            "worst_trade_delta": d_worst,
            "best_trade_delta": d_best,
            "missed_gain_sum_delta": d_missed,
        }
        if (
            d_pnl >= PNL_IMPROVEMENT_MIN
            and d_worst >= -WORST_TRADE_DEGRADATION_MAX
        ):
            qualifying.append((name, metrics))

    all_worse_pnl = all(
        m.sum_pnl_ratio <= baseline.sum_pnl_ratio for m in single_overlays.values()
    )
    all_worse_worst = all(
        m.worst_trade_ratio <= baseline.worst_trade_ratio for m in single_overlays.values()
    )
    if all_worse_pnl and all_worse_worst:
        return {
            "label": "REJECT_OVERLAY",
            "reason": (
                "No proposed overlay improved either total PnL or worst-trade; "
                "all three variants underperformed the 08:55-only baseline on "
                "this window."
            ),
            "deltas": deltas,
        }
    if not qualifying:
        return {
            "label": "KEEP_0855_ONLY",
            "reason": (
                "No single overlay improved baseline sum PnL by the minimum "
                f"{PNL_IMPROVEMENT_MIN:.3%} threshold without worsening worst "
                "trade. Do not enable any overlay in live; revisit after more "
                "trade history accumulates."
            ),
            "deltas": deltas,
        }
    qualifying.sort(
        key=lambda kv: (kv[1].sum_pnl_ratio, -abs(kv[1].worst_trade_ratio)),
        reverse=True,
    )
    winner_name, winner_metrics = qualifying[0]
    label_map = {
        "failed_breakout_only": "ADD_FAILED_BREAKOUT_EXIT",
        "trailing_only": "ADD_TRAILING_EXIT",
        "time_decay_only": "ADD_TIME_DECAY",
    }
    label = label_map.get(winner_name, "KEEP_0855_ONLY")
    return {
        "label": label,
        "winner_overlay": winner_name,
        "reason": (
            f"{winner_name} improved sum PnL by "
            f"{deltas[winner_name]['sum_pnl_delta']:+.4%} vs baseline without "
            "worsening worst trade beyond tolerance. This is a replay signal, "
            "not a live-enable authorization — Codex review still required."
        ),
        "deltas": deltas,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    parser.add_argument("--analysis-days", type=int, default=DEFAULT_ANALYSIS_DAYS)
    parser.add_argument(
        "--fetch-days",
        type=int,
        default=DEFAULT_ANALYSIS_DAYS + FETCH_BUFFER_DAYS,
        help="Total fetch length = analysis window + feature warmup.",
    )
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    print(
        f"fetch daily + minute30 for {args.tickers} "
        f"(analysis_days={args.analysis_days}, fetch_days={args.fetch_days})"
    )
    daily: dict[str, pd.DataFrame] = {}
    thirty: dict[str, pd.DataFrame] = {}
    for ticker in args.tickers:
        daily[ticker] = _fetch_ohlcv(ticker, "day", args.fetch_days)
        thirty[ticker] = _fetch_ohlcv(ticker, "minute30", args.fetch_days)

    trades_by_overlay: dict[str, list[TradeResult]] = {name: [] for name in OVERLAYS}
    per_ticker_trades: dict[str, dict[str, list[TradeResult]]] = {}
    for ticker in args.tickers:
        result = simulate_ticker(ticker, daily[ticker], thirty[ticker], args.analysis_days)
        per_ticker_trades[ticker] = result
        for overlay_name, trades in result.items():
            trades_by_overlay[overlay_name].extend(trades)

    overlay_metrics = {
        name: compute_overlay_metrics(name, trades)
        for name, trades in trades_by_overlay.items()
    }
    baseline = overlay_metrics["baseline_0855_only"]
    single_overlays = {
        name: overlay_metrics[name]
        for name in ("failed_breakout_only", "trailing_only", "time_decay_only")
    }
    recommendation = recommend(baseline, single_overlays)

    report = {
        "as_of": AS_OF,
        "strategy": "volatility_breakout",
        "scope": (
            "intraday exit overlay REPLAY only; no strategy/live/paper/UI/KPI/settings changes"
        ),
        "interval": "minute30+day",
        "tickers": args.tickers,
        "analysis_days": args.analysis_days,
        "fetch_days": args.fetch_days,
        "fee": FEE,
        "slippage": SLIPPAGE,
        "vb_k": VB_K,
        "ma_window": MA_WINDOW,
        "require_ma_filter": REQUIRE_MA_FILTER,
        "overlay_thresholds": {
            "failed_breakout_min_hold_bars": FAILED_BREAKOUT_MIN_HOLD_BARS,
            "trailing_activate_profit": TRAILING_ACTIVATE_PROFIT,
            "trailing_atr_window": TRAILING_ATR_WINDOW,
            "trailing_atr_mult": TRAILING_ATR_MULT,
            "trailing_min_pct_fallback": TRAILING_MIN_PCT,
            "time_decay_min_hold_bars": TIME_DECAY_MIN_HOLD_BARS,
            "time_decay_profit_min": TIME_DECAY_PROFIT_MIN,
            "time_decay_profit_max": TIME_DECAY_PROFIT_MAX,
        },
        "recommendation": recommendation,
        "overlay_metrics": {name: asdict(m) for name, m in overlay_metrics.items()},
        "per_overlay_trades": {
            name: [asdict(t) for t in trades]
            for name, trades in trades_by_overlay.items()
        },
        "per_ticker_trade_counts": {
            ticker: {name: len(trades) for name, trades in overlays.items()}
            for ticker, overlays in per_ticker_trades.items()
        },
        "caveat": (
            "Hourly exits can hurt a volatility-breakout strategy because the "
            "classic reason for next-day exit is to let the breakout run. "
            "Early exits may cut the right tail. Use this replay as evidence "
            "for Codex review, not as a live-enable trigger."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.out)
    print(
        json.dumps(
            {
                "recommendation": recommendation,
                "overlay_summary": {
                    name: {
                        "total_trades": m.total_trades,
                        "sum_pnl_ratio": m.sum_pnl_ratio,
                        "compounded_pnl_ratio": m.compounded_pnl_ratio,
                        "win_rate": m.win_rate,
                        "worst_trade_ratio": m.worst_trade_ratio,
                        "overlay_exits_count": m.overlay_exits_count,
                        "missed_gain_sum": m.missed_gain_sum,
                    }
                    for name, m in overlay_metrics.items()
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

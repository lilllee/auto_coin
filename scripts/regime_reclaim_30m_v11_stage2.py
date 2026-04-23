"""regime_reclaim_30m v1.1 exit-only Stage 2 revalidation.

Scope intentionally excludes walk-forward/live/UI work.  The entry parameters are held
fixed; only reversion_exit / protective-exit parameters are varied in a bounded set.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.backtest.runner import DEFAULT_SLIPPAGE, UPBIT_DEFAULT_FEE, backtest
from auto_coin.data.candles import enrich_for_strategy, history_days_to_candles
from auto_coin.strategy import create_strategy

AS_OF = "2026-04-23"
REPORT_PATH = Path("reports/2026-04-23-regime-reclaim-30m-v11-stage2.json")
TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
LOOKBACK_WINDOWS = {"1y": 365, "2y": 730}
DEFAULT_FETCH_DAYS = 830
REGIME_TICKER = "KRW-BTC"

# Entry / structure is fixed for this turn.
ENTRY_FIXED_PARAMS: dict[str, Any] = {
    "regime_ticker": REGIME_TICKER,
    "daily_regime_ma_window": 100,
    "hourly_pullback_bars": 8,
    "hourly_pullback_threshold_pct": -0.025,
    "setup_rsi_window": 14,
    "setup_rsi_threshold": 35.0,
    "trigger_reclaim_ema_window": 6,
    "trigger_rsi_rebound_threshold": 30.0,
    "max_hold_bars_30m": 36,
    "atr_window": 14,
    "atr_trailing_mult": 2.0,
}

# Bounded exit-only candidate set.  Profit guard values are ratio units:
# 0.003 = 0.3%, 0.005 = 0.5%, 0.008 = 0.8%.
EXIT_CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "v1_baseline_sma8",
        "exit_params": {
            "reversion_sma_window_override": None,
            "min_hold_bars_30m": 0,
            "reversion_min_profit_pct": 0.0,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "sma12_only",
        "exit_params": {
            "reversion_sma_window_override": 12,
            "min_hold_bars_30m": 0,
            "reversion_min_profit_pct": 0.0,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "sma24_only",
        "exit_params": {
            "reversion_sma_window_override": 24,
            "min_hold_bars_30m": 0,
            "reversion_min_profit_pct": 0.0,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "sma36_only",
        "exit_params": {
            "reversion_sma_window_override": 36,
            "min_hold_bars_30m": 0,
            "reversion_min_profit_pct": 0.0,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "sma48_only",
        "exit_params": {
            "reversion_sma_window_override": 48,
            "min_hold_bars_30m": 0,
            "reversion_min_profit_pct": 0.0,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "mh2_mp003_sma24",
        "exit_params": {
            "reversion_sma_window_override": 24,
            "min_hold_bars_30m": 2,
            "reversion_min_profit_pct": 0.003,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "mh3_mp005_sma24",
        "exit_params": {
            "reversion_sma_window_override": 24,
            "min_hold_bars_30m": 3,
            "reversion_min_profit_pct": 0.005,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "mh4_mp008_sma24",
        "exit_params": {
            "reversion_sma_window_override": 24,
            "min_hold_bars_30m": 4,
            "reversion_min_profit_pct": 0.008,
            "reversion_confirmation_type": "none",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "mh3_mp005_sma36_rsi",
        "exit_params": {
            "reversion_sma_window_override": 36,
            "min_hold_bars_30m": 3,
            "reversion_min_profit_pct": 0.005,
            "reversion_confirmation_type": "rsi",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "mh3_mp005_sma36_consecutive",
        "exit_params": {
            "reversion_sma_window_override": 36,
            "min_hold_bars_30m": 3,
            "reversion_min_profit_pct": 0.005,
            "reversion_confirmation_type": "consecutive",
            "atr_trailing_mult": 2.0,
        },
    },
    {
        "name": "mh3_mp005_sma36_rsi_atr15",
        "exit_params": {
            "reversion_sma_window_override": 36,
            "min_hold_bars_30m": 3,
            "reversion_min_profit_pct": 0.005,
            "reversion_confirmation_type": "rsi",
            "atr_trailing_mult": 1.5,
        },
    },
    {
        "name": "mh3_mp005_sma36_rsi_atr25",
        "exit_params": {
            "reversion_sma_window_override": 36,
            "min_hold_bars_30m": 3,
            "reversion_min_profit_pct": 0.005,
            "reversion_confirmation_type": "rsi",
            "atr_trailing_mult": 2.5,
        },
    },
]


def _fetch_ohlcv(ticker: str, interval: str, days: int) -> pd.DataFrame:
    count = history_days_to_candles(days, interval)
    df = None
    for attempt in range(3):
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
        if df is not None and not df.empty:
            break
        print(f"retry fetch {ticker} {interval} attempt={attempt + 2}/3")
    if df is None or df.empty:
        raise SystemExit(f"failed to fetch {interval} candles for {ticker}")
    return df


def _slice_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    end = df.index.max()
    start = end - pd.Timedelta(days=days)
    return df.loc[df.index >= start].copy()


def _avg_hold_days(trades) -> float:
    if not trades:
        return 0.0
    seconds = sum((t.exit_date - t.entry_date).total_seconds() for t in trades)
    return seconds / len(trades) / (24 * 60 * 60)


def _exit_mix(result) -> dict[str, dict[str, float | int]]:
    bucket = defaultdict(list)
    for trade in result.trades:
        bucket[trade.exit_type].append(trade)

    out: dict[str, dict[str, float | int]] = {}
    for reason, trades in sorted(bucket.items()):
        avg_hold_days = _avg_hold_days(trades)
        out[reason] = {
            "trade_count": len(trades),
            "ratio": len(trades) / result.n_trades if result.n_trades else 0.0,
            "avg_return": sum(t.ret for t in trades) / len(trades),
            "avg_hold_days": avg_hold_days,
            "avg_hold_bars": avg_hold_days * 48.0,
        }
    return out


def _benchmark_return(df: pd.DataFrame) -> float:
    closes = df["close"].dropna()
    if len(closes) < 2:
        return 0.0
    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    return last / first - 1.0 if first > 0 else 0.0


def _run_one(
    ticker: str,
    candidate: dict[str, Any],
    lookback_days: int,
    thirty: dict[str, pd.DataFrame],
    hourly: dict[str, pd.DataFrame],
    regime_daily: pd.DataFrame,
) -> dict[str, Any]:
    params = {**ENTRY_FIXED_PARAMS, **candidate["exit_params"]}
    sample_30m = _slice_days(thirty[ticker], lookback_days)
    # Enrich on the sliced trading sample, while projecting full daily/1H context.
    enriched = enrich_for_strategy(
        sample_30m,
        "regime_reclaim_30m",
        params,
        regime_df=regime_daily,
        hourly_setup_df=hourly[ticker],
        interval="minute30",
    )
    strategy = create_strategy("regime_reclaim_30m", params)
    result = backtest(
        enriched,
        strategy,
        fee=UPBIT_DEFAULT_FEE,
        slippage=DEFAULT_SLIPPAGE,
        interval="minute30",
    )
    benchmark = _benchmark_return(sample_30m)
    avg_hold_bars = result.avg_hold_days * 48.0
    return {
        "start": str(sample_30m.index[0]),
        "end": str(sample_30m.index[-1]),
        "cumulative_return": result.cumulative_return,
        "benchmark_return": benchmark,
        "excess_return": result.cumulative_return - benchmark,
        "mdd": result.mdd,
        "sharpe": result.sharpe_ratio,
        "total_trades": result.n_trades,
        "win_rate": result.win_rate,
        "avg_hold_days": result.avg_hold_days,
        "avg_hold_bars": avg_hold_bars,
        "expectancy": result.expectancy,
        "exit_mix": _exit_mix(result),
    }


def _candidate_summary(candidate_result: dict[str, Any]) -> dict[str, float | int]:
    leaves = [
        metrics
        for by_window in candidate_result["results"].values()
        for metrics in by_window.values()
    ]
    n = len(leaves) or 1
    total_trades = sum(m["total_trades"] for m in leaves)
    return {
        "avg_cumulative_return": sum(m["cumulative_return"] for m in leaves) / n,
        "avg_excess_return": sum(m["excess_return"] for m in leaves) / n,
        "avg_expectancy": sum(m["expectancy"] for m in leaves) / n,
        "avg_hold_bars": sum(m["avg_hold_bars"] for m in leaves) / n,
        "total_trades": total_trades,
        "time_exit_share": (
            sum(
                m["exit_mix"].get("regime_reclaim_30m_time_exit", {}).get("trade_count", 0)
                for m in leaves
            )
            / total_trades
            if total_trades
            else 0.0
        ),
        "reversion_exit_share": (
            sum(
                m["exit_mix"].get("regime_reclaim_30m_reversion_exit", {}).get("trade_count", 0)
                for m in leaves
            )
            / total_trades
            if total_trades
            else 0.0
        ),
        "trailing_exit_share": (
            sum(
                m["exit_mix"].get("regime_reclaim_30m_trailing_exit", {}).get("trade_count", 0)
                for m in leaves
            )
            / total_trades
            if total_trades
            else 0.0
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-days", type=int, default=DEFAULT_FETCH_DAYS)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    thirty = {ticker: _fetch_ohlcv(ticker, "minute30", args.fetch_days) for ticker in TICKERS}
    hourly = {ticker: _fetch_ohlcv(ticker, "minute60", args.fetch_days) for ticker in TICKERS}
    regime_daily = _fetch_ohlcv(REGIME_TICKER, "day", args.fetch_days)

    candidates: list[dict[str, Any]] = []
    for candidate in EXIT_CANDIDATES:
        candidate_result = {
            "name": candidate["name"],
            "params": {**ENTRY_FIXED_PARAMS, **candidate["exit_params"]},
            "results": {
                window_name: {
                    ticker: _run_one(
                        ticker,
                        candidate,
                        days,
                        thirty,
                        hourly,
                        regime_daily,
                    )
                    for ticker in TICKERS
                }
                for window_name, days in LOOKBACK_WINDOWS.items()
            },
        }
        candidate_result["summary"] = _candidate_summary(candidate_result)
        candidates.append(candidate_result)

    baseline = next(c for c in candidates if c["name"] == "v1_baseline_sma8")
    ranked = sorted(
        candidates,
        key=lambda c: (
            c["summary"]["avg_expectancy"],
            c["summary"]["avg_excess_return"],
            c["summary"]["avg_hold_bars"],
        ),
        reverse=True,
    )

    report = {
        "as_of": AS_OF,
        "strategy": "regime_reclaim_30m",
        "scope": "exit-only bounded Stage 2 revalidation; no walk-forward/live/UI/KPI changes",
        "interval": "minute30",
        "tickers": TICKERS,
        "lookback_windows": LOOKBACK_WINDOWS,
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "entry_fixed_params": ENTRY_FIXED_PARAMS,
        "exit_axes": {
            "reversion_sma_window_override": [None, 12, 24, 36, 48],
            "min_hold_bars_30m": [0, 2, 3, 4],
            "reversion_min_profit_pct_ratio": [0.0, 0.003, 0.005, 0.008],
            "reversion_confirmation_type": ["none", "rsi", "consecutive"],
            "atr_trailing_mult": [1.5, 2.0, 2.5],
        },
        "candidate_count": len(candidates),
        "baseline": baseline,
        "ranked_candidates": ranked,
        "best_candidate": ranked[0],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

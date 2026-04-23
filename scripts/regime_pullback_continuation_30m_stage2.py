"""regime_pullback_continuation_30m Stage 2 in-sample validation.

No walk-forward/live/UI work.  This script runs a bounded candidate set on
BTC/ETH/XRP 1y and 2y samples and writes a verdict-bearing JSON report.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.backtest.runner import DEFAULT_SLIPPAGE, UPBIT_DEFAULT_FEE, backtest
from auto_coin.data.candles import enrich_for_strategy, history_days_to_candles
from auto_coin.strategy import create_strategy

AS_OF = "2026-04-23"
REPORT_PATH = Path("reports/2026-04-23-regime-pullback-continuation-30m-stage2.json")
TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
CORE_TICKERS = ["KRW-BTC", "KRW-ETH"]
LOOKBACK_WINDOWS = {"1y": 365, "2y": 730}
DEFAULT_FETCH_DAYS = 830
REGIME_TICKER = "KRW-BTC"

BASE_PARAMS: dict[str, Any] = {
    "regime_ticker": REGIME_TICKER,
    "daily_regime_ma_window": 100,
    "trend_ema_fast_1h": 20,
    "trend_ema_slow_1h": 60,
    "trend_slope_lookback_1h": 3,
    "pullback_lookback_1h": 8,
    "pullback_min_pct": -0.045,
    "pullback_max_pct": -0.012,
    "pullback_ema_buffer_pct": 0.012,
    "setup_rsi_window": 14,
    "setup_rsi_min": 35.0,
    "setup_rsi_recovery": 40.0,
    "trigger_ema_fast_30m": 8,
    "trigger_ema_slow_30m": 21,
    "trigger_breakout_lookback_30m": 6,
    "trigger_volume_window_30m": 20,
    "trigger_volume_mult": 1.1,
    "trigger_close_location_min": 0.55,
    "trigger_rsi_momentum_min": 3.0,
    "trigger_rsi_min": 45.0,
    "trigger_required_votes": 2,
    "atr_window": 14,
    "initial_stop_atr_mult": 1.5,
    "atr_trailing_mult": 2.5,
    "trend_exit_mode": "close_below_ema20",
    "max_hold_bars_30m": 96,
}

CANDIDATES: list[dict[str, Any]] = [
    {"name": "base_votes2", "overrides": {}},
    {"name": "votes1", "overrides": {"trigger_required_votes": 1}},
    {"name": "votes1_no_volume_premium", "overrides": {"trigger_required_votes": 1, "trigger_volume_mult": 1.0}},
    {"name": "votes1_rsi38", "overrides": {"trigger_required_votes": 1, "setup_rsi_recovery": 38.0}},
    {"name": "votes1_pullback_wide", "overrides": {"trigger_required_votes": 1, "pullback_min_pct": -0.06, "pullback_max_pct": -0.008}},
    {"name": "votes1_fast12_slow48", "overrides": {"trigger_required_votes": 1, "trend_ema_fast_1h": 12, "trend_ema_slow_1h": 48}},
    {"name": "votes1_breakout4", "overrides": {"trigger_required_votes": 1, "trigger_breakout_lookback_30m": 4}},
    {"name": "votes2_relaxed_clv", "overrides": {"trigger_close_location_min": 0.50, "trigger_volume_mult": 1.0}},
    {"name": "votes1_atr20", "overrides": {"trigger_required_votes": 1, "atr_trailing_mult": 2.0}},
    {"name": "votes1_atr30", "overrides": {"trigger_required_votes": 1, "atr_trailing_mult": 3.0}},
    {"name": "votes1_stop12", "overrides": {"trigger_required_votes": 1, "initial_stop_atr_mult": 1.2}},
    {"name": "votes1_trend_slow_exit", "overrides": {"trigger_required_votes": 1, "trend_exit_mode": "ema20_below_ema60"}},
    {"name": "votes1_hold48", "overrides": {"trigger_required_votes": 1, "max_hold_bars_30m": 48}},
    {"name": "votes1_hold72", "overrides": {"trigger_required_votes": 1, "max_hold_bars_30m": 72}},
    {
        "name": "relaxed_rsi_pullback_votes1",
        "overrides": {
            "trigger_required_votes": 1,
            "setup_rsi_min": 50.0,
            "setup_rsi_recovery": 35.0,
            "pullback_min_pct": -0.10,
            "pullback_max_pct": -0.002,
            "pullback_ema_buffer_pct": 0.05,
            "trigger_close_location_min": 0.50,
            "trigger_volume_mult": 1.0,
            "trigger_rsi_min": 40.0,
            "trigger_rsi_momentum_min": 0.0,
        },
    },
    {
        "name": "relaxed_rsi_pullback_votes2",
        "overrides": {
            "trigger_required_votes": 2,
            "setup_rsi_min": 50.0,
            "setup_rsi_recovery": 35.0,
            "pullback_min_pct": -0.10,
            "pullback_max_pct": -0.002,
            "pullback_ema_buffer_pct": 0.05,
            "trigger_close_location_min": 0.50,
            "trigger_volume_mult": 1.0,
            "trigger_rsi_min": 40.0,
            "trigger_rsi_momentum_min": 0.0,
        },
    },
    {
        "name": "relaxed_trend_slow_exit",
        "overrides": {
            "trigger_required_votes": 1,
            "setup_rsi_min": 50.0,
            "setup_rsi_recovery": 35.0,
            "pullback_min_pct": -0.10,
            "pullback_max_pct": -0.002,
            "pullback_ema_buffer_pct": 0.05,
            "trigger_close_location_min": 0.50,
            "trigger_volume_mult": 1.0,
            "trigger_rsi_min": 40.0,
            "trigger_rsi_momentum_min": 0.0,
            "trend_exit_mode": "ema20_below_ema60",
        },
    },
]


def _fetch_ohlcv(ticker: str, interval: str, days: int) -> pd.DataFrame:
    count = history_days_to_candles(days, interval)
    chunk_size = min(count, 5000)
    chunks: list[pd.DataFrame] = []
    to = None
    while sum(len(chunk) for chunk in chunks) < count:
        remaining = count - sum(len(chunk) for chunk in chunks)
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


def _slice_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    start = df.index.max() - pd.Timedelta(days=days)
    return df.loc[df.index >= start].copy()


def _benchmark_return(df: pd.DataFrame) -> float:
    closes = df["close"].dropna()
    if len(closes) < 2:
        return 0.0
    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    return last / first - 1.0 if first > 0 else 0.0


def _exit_mix(result) -> dict[str, dict[str, float | int]]:
    bucket = defaultdict(list)
    for trade in result.trades:
        bucket[trade.exit_type].append(trade)
    out: dict[str, dict[str, float | int]] = {}
    for reason, trades in sorted(bucket.items()):
        avg_hold_days = sum((t.exit_date - t.entry_date).total_seconds() for t in trades) / len(trades) / (24 * 60 * 60)
        out[reason] = {
            "trade_count": len(trades),
            "ratio": len(trades) / result.n_trades if result.n_trades else 0.0,
            "avg_return": sum(t.ret for t in trades) / len(trades),
            "avg_hold_days": avg_hold_days,
            "avg_hold_bars": avg_hold_days * 48.0,
        }
    return out


def _run_one(
    ticker: str,
    params: dict[str, Any],
    lookback_days: int,
    thirty: dict[str, pd.DataFrame],
    hourly: dict[str, pd.DataFrame],
    regime_daily: pd.DataFrame,
) -> dict[str, Any]:
    sample = _slice_days(thirty[ticker], lookback_days)
    enriched = enrich_for_strategy(
        sample,
        "regime_pullback_continuation_30m",
        params,
        regime_df=regime_daily,
        hourly_setup_df=hourly[ticker],
        interval="minute30",
    )
    strategy = create_strategy("regime_pullback_continuation_30m", params)
    result = backtest(
        enriched,
        strategy,
        fee=UPBIT_DEFAULT_FEE,
        slippage=DEFAULT_SLIPPAGE,
        interval="minute30",
    )
    benchmark = _benchmark_return(sample)
    return {
        "start": str(sample.index[0]),
        "end": str(sample.index[-1]),
        "cumulative_return": result.cumulative_return,
        "benchmark_return": benchmark,
        "excess_return": result.cumulative_return - benchmark,
        "mdd": result.mdd,
        "sharpe": result.sharpe_ratio,
        "total_trades": result.n_trades,
        "win_rate": result.win_rate,
        "avg_hold_days": result.avg_hold_days,
        "avg_hold_bars": result.avg_hold_days * 48.0,
        "expectancy": result.expectancy,
        "exit_mix": _exit_mix(result),
    }


def _summary(candidate: dict[str, Any]) -> dict[str, float | int]:
    leaves = [m for by_window in candidate["results"].values() for m in by_window.values()]
    n = len(leaves) or 1
    total_trades = sum(m["total_trades"] for m in leaves)
    return {
        "avg_cumulative_return": sum(m["cumulative_return"] for m in leaves) / n,
        "avg_excess_return": sum(m["excess_return"] for m in leaves) / n,
        "avg_expectancy": sum(m["expectancy"] for m in leaves) / n,
        "avg_hold_bars": sum(m["avg_hold_bars"] for m in leaves) / n,
        "total_trades": total_trades,
        "time_exit_share": sum(m["exit_mix"].get("regime_pullback_continuation_30m_time_exit", {}).get("trade_count", 0) for m in leaves) / total_trades if total_trades else 0.0,
        "initial_stop_share": sum(m["exit_mix"].get("regime_pullback_continuation_30m_initial_stop", {}).get("trade_count", 0) for m in leaves) / total_trades if total_trades else 0.0,
        "trailing_exit_share": sum(m["exit_mix"].get("regime_pullback_continuation_30m_trailing_exit", {}).get("trade_count", 0) for m in leaves) / total_trades if total_trades else 0.0,
        "trend_exit_share": sum(m["exit_mix"].get("regime_pullback_continuation_30m_trend_exit", {}).get("trade_count", 0) for m in leaves) / total_trades if total_trades else 0.0,
    }


def _verdict(best: dict[str, Any]) -> dict[str, Any]:
    btc2 = best["results"]["2y"]["KRW-BTC"]
    eth2 = best["results"]["2y"]["KRW-ETH"]
    avg_core_excess = (btc2["excess_return"] + eth2["excess_return"]) / 2.0
    gates = {
        "btc_2y_trades_ge_10": btc2["total_trades"] >= 10,
        "eth_2y_trades_ge_20": eth2["total_trades"] >= 20,
        "avg_hold_bars_ge_6": best["summary"]["avg_hold_bars"] >= 6,
        "avg_hold_bars_le_72": best["summary"]["avg_hold_bars"] <= 72,
        "time_exit_share_le_20pct": best["summary"]["time_exit_share"] <= 0.20,
        "btc_or_eth_2y_expectancy_positive": btc2["expectancy"] > 0 or eth2["expectancy"] > 0,
        "avg_core_excess_non_negative": avg_core_excess >= 0,
    }
    if all(gates.values()):
        label = "PASS"
    elif best["summary"]["total_trades"] == 0 or best["summary"]["avg_expectancy"] < -0.01:
        label = "STOP"
    elif gates["btc_2y_trades_ge_10"] and gates["eth_2y_trades_ge_20"]:
        label = "REVISE"
    else:
        label = "HOLD"
    return {"label": label, "gates": gates, "avg_core_2y_excess_return": avg_core_excess}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-days", type=int, default=DEFAULT_FETCH_DAYS)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    thirty = {ticker: _fetch_ohlcv(ticker, "minute30", args.fetch_days) for ticker in TICKERS}
    hourly = {ticker: _fetch_ohlcv(ticker, "minute60", args.fetch_days) for ticker in TICKERS}
    regime_daily = _fetch_ohlcv(REGIME_TICKER, "day", args.fetch_days)

    candidates = []
    for candidate in CANDIDATES:
        params = {**BASE_PARAMS, **candidate["overrides"]}
        result = {
            "name": candidate["name"],
            "params": params,
            "results": {
                window: {
                    ticker: _run_one(ticker, params, days, thirty, hourly, regime_daily)
                    for ticker in TICKERS
                }
                for window, days in LOOKBACK_WINDOWS.items()
            },
        }
        result["summary"] = _summary(result)
        candidates.append(result)

    # A zero-trade candidate is not a tradable strategy even if its expectancy is
    # numerically 0. Rank viable candidates first, but keep all candidates in the
    # report for transparency.
    viable = [c for c in candidates if c["summary"]["total_trades"] > 0]
    ranking_pool = viable or candidates
    ranked = sorted(
        ranking_pool,
        key=lambda c: (
            c["summary"]["avg_expectancy"],
            c["summary"]["avg_excess_return"],
            c["summary"]["total_trades"],
        ),
        reverse=True,
    )
    best = ranked[0]
    report = {
        "as_of": AS_OF,
        "strategy": "regime_pullback_continuation_30m",
        "scope": "Stage 2 in-sample only; no walk-forward/live/UI/KPI",
        "interval": "minute30",
        "tickers": TICKERS,
        "lookback_windows": LOOKBACK_WINDOWS,
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "base_params": BASE_PARAMS,
        "candidate_count": len(candidates),
        "ranked_candidates": ranked,
        "best_candidate": best,
        "verdict": _verdict(best),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(args.out)
    print(json.dumps({"best": best["name"], "summary": best["summary"], "verdict": report["verdict"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

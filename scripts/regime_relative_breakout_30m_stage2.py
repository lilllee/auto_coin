"""regime_relative_breakout_30m Stage 2 in-sample validation.

No walk-forward, no live/paper, no UI/KPI changes.  Runs the Codex-approved
bounded candidate sweep on KRW-BTC/ETH/XRP across 1y and 2y windows and writes
a verdict-bearing JSON report.
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
from auto_coin.data.candles import (
    enrich_regime_relative_breakout_30m,
    history_days_to_candles,
)
from auto_coin.strategy import create_strategy

AS_OF = "2026-04-23"
REPORT_PATH = Path("reports/2026-04-23-regime-relative-breakout-30m-stage2.json")
TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
ALT_TICKERS = ["KRW-ETH", "KRW-XRP"]
REGIME_TICKER = "KRW-BTC"
LOOKBACK_WINDOWS = {"1y": 365, "2y": 730}
DEFAULT_FETCH_DAYS = 830

BASE_PARAMS: dict[str, Any] = {
    "regime_ticker": REGIME_TICKER,
    "daily_regime_ma_window": 100,
    "rs_24h_bars_30m": 48,
    "rs_7d_bars_30m": 336,
    "hourly_ema_fast": 20,
    "hourly_ema_slow": 60,
    "hourly_slope_lookback": 3,
    "breakout_lookback_30m": 6,
    "volume_window_30m": 20,
    "volume_mult": 1.2,
    "close_location_min": 0.55,
    "atr_window": 14,
    "initial_stop_atr_mult": 2.0,
    "atr_trailing_mult": 3.0,
    "trend_exit_confirm_bars": 2,
    "max_hold_bars_30m": 48,
}

CANDIDATES: list[dict[str, Any]] = [
    {"name": "base_stop2_trail3_hold48_confirm2", "overrides": {}},
    {"name": "stop15_trail3_hold48_confirm2", "overrides": {"initial_stop_atr_mult": 1.5}},
    {"name": "stop25_trail3_hold48_confirm2", "overrides": {"initial_stop_atr_mult": 2.5}},
    {"name": "stop2_trail25_hold48_confirm2", "overrides": {"atr_trailing_mult": 2.5}},
    {"name": "stop2_trail35_hold48_confirm2", "overrides": {"atr_trailing_mult": 3.5}},
    {"name": "stop2_trail3_hold24_confirm2", "overrides": {"max_hold_bars_30m": 24}},
    {"name": "stop2_trail3_hold72_confirm2", "overrides": {"max_hold_bars_30m": 72}},
    {"name": "stop2_trail3_hold48_confirm1", "overrides": {"trend_exit_confirm_bars": 1}},
    {"name": "stop2_trail3_hold48_confirm3", "overrides": {"trend_exit_confirm_bars": 3}},
]


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


def _slice_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    if df.empty:
        return df
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
    bucket: dict[str, list[Any]] = defaultdict(list)
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
    btc_daily: pd.DataFrame,
    btc_30m: pd.DataFrame,
) -> dict[str, Any]:
    sample = _slice_days(thirty[ticker], lookback_days)
    enriched = enrich_regime_relative_breakout_30m(
        sample,
        daily_regime_df=btc_daily,
        daily_regime_ma_window=params["daily_regime_ma_window"],
        hourly_setup_df=hourly[ticker],
        hourly_ema_fast=params["hourly_ema_fast"],
        hourly_ema_slow=params["hourly_ema_slow"],
        hourly_slope_lookback=params["hourly_slope_lookback"],
        rs_reference_df=btc_30m,
        rs_24h_bars_30m=params["rs_24h_bars_30m"],
        rs_7d_bars_30m=params["rs_7d_bars_30m"],
        breakout_lookback_30m=params["breakout_lookback_30m"],
        volume_window_30m=params["volume_window_30m"],
        atr_window=params["atr_window"],
    )
    strategy = create_strategy("regime_relative_breakout_30m", params)
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


def _exit_share(leaves: list[dict[str, Any]], suffix: str) -> float:
    total = sum(m["total_trades"] for m in leaves)
    if not total:
        return 0.0
    count = 0
    for m in leaves:
        for reason, mix in m["exit_mix"].items():
            if reason.endswith(suffix):
                count += mix["trade_count"]
    return count / total


def _summary(candidate: dict[str, Any]) -> dict[str, float | int]:
    results = candidate["results"]
    leaves = [m for by_window in results.values() for m in by_window.values()]
    alt_leaves = [
        m for by_window in results.values()
        for tkr, m in by_window.items()
        if tkr in ALT_TICKERS
    ]
    n = len(leaves) or 1
    alt_n = len(alt_leaves) or 1
    total_trades = sum(m["total_trades"] for m in leaves)
    alt_total_trades = sum(m["total_trades"] for m in alt_leaves)
    return {
        "avg_cumulative_return": sum(m["cumulative_return"] for m in leaves) / n,
        "avg_excess_return": sum(m["excess_return"] for m in leaves) / n,
        "alt_avg_excess_return": sum(m["excess_return"] for m in alt_leaves) / alt_n,
        "avg_expectancy": sum(m["expectancy"] for m in leaves) / n,
        "alt_avg_expectancy": sum(m["expectancy"] for m in alt_leaves) / alt_n,
        "avg_hold_bars": sum(m["avg_hold_bars"] for m in leaves) / n,
        "total_trades": total_trades,
        "alt_total_trades": alt_total_trades,
        "initial_stop_share": _exit_share(leaves, "_initial_stop"),
        "trailing_exit_share": _exit_share(leaves, "_trailing_exit"),
        "trend_exit_share": _exit_share(leaves, "_trend_exit"),
        "regime_off_exit_share": _exit_share(leaves, "_regime_off_exit"),
        "time_exit_share": _exit_share(leaves, "_time_exit"),
    }


def _verdict(best: dict[str, Any]) -> dict[str, Any]:
    results2 = best["results"]["2y"]
    eth = results2["KRW-ETH"]
    xrp = results2["KRW-XRP"]
    eth_trades = eth["total_trades"]
    xrp_trades = xrp["total_trades"]
    alt_trades = eth_trades + xrp_trades
    eth_expectancy = eth["expectancy"]
    xrp_expectancy = xrp["expectancy"]
    alt_expectancy = (
        (eth_expectancy * eth_trades + xrp_expectancy * xrp_trades) / alt_trades
        if alt_trades
        else 0.0
    )
    alt_excess = (eth["excess_return"] + xrp["excess_return"]) / 2.0
    summary = best["summary"]
    gates = {
        "alt_2y_trades_ge_50": alt_trades >= 50,
        "eth_2y_trades_ge_20": eth_trades >= 20,
        "xrp_2y_trades_ge_20": xrp_trades >= 20,
        "alt_2y_expectancy_positive": alt_expectancy > 0,
        "eth_2y_expectancy_positive": eth_expectancy > 0,
        "xrp_2y_expectancy_positive": xrp_expectancy > 0,
        "alt_2y_excess_positive": alt_excess > 0,
        "avg_hold_bars_between_4_and_48": 4 <= summary["avg_hold_bars"] <= 48,
        "time_exit_share_le_25pct": summary["time_exit_share"] <= 0.25,
    }
    count_gates = [
        gates["alt_2y_trades_ge_50"],
        gates["eth_2y_trades_ge_20"],
        gates["xrp_2y_trades_ge_20"],
    ]
    performance_gates = [
        gates["alt_2y_expectancy_positive"],
        gates["eth_2y_expectancy_positive"],
        gates["xrp_2y_expectancy_positive"],
        gates["alt_2y_excess_positive"],
        gates["avg_hold_bars_between_4_and_48"],
        gates["time_exit_share_le_25pct"],
    ]
    # STOP: trade count sufficient but ETH AND XRP both negative expectancy AND negative excess
    stop_trigger = (
        all(count_gates)
        and eth_expectancy < 0
        and xrp_expectancy < 0
        and eth["excess_return"] < 0
        and xrp["excess_return"] < 0
    )
    if all(gates.values()):
        label = "PASS"
    elif stop_trigger:
        label = "STOP"
    elif all(count_gates) and 1 <= sum(1 for g in performance_gates if not g) <= 3:
        label = "REVISE"
    else:
        label = "HOLD"
    return {
        "label": label,
        "gates": gates,
        "alt_2y_trades": alt_trades,
        "alt_2y_expectancy": alt_expectancy,
        "alt_2y_excess_return": alt_excess,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-days", type=int, default=DEFAULT_FETCH_DAYS)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)

    print(f"fetch minute30 for {TICKERS}")
    thirty = {t: _fetch_ohlcv(t, "minute30", args.fetch_days) for t in TICKERS}
    print(f"fetch minute60 for {TICKERS}")
    hourly = {t: _fetch_ohlcv(t, "minute60", args.fetch_days) for t in TICKERS}
    print(f"fetch day for {REGIME_TICKER}")
    btc_daily = _fetch_ohlcv(REGIME_TICKER, "day", args.fetch_days)
    btc_30m = thirty[REGIME_TICKER]

    candidates: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        params = {**BASE_PARAMS, **candidate["overrides"]}
        result = {
            "name": candidate["name"],
            "params": params,
            "results": {
                window: {
                    ticker: _run_one(ticker, params, days, thirty, hourly, btc_daily, btc_30m)
                    for ticker in TICKERS
                }
                for window, days in LOOKBACK_WINDOWS.items()
            },
        }
        result["summary"] = _summary(result)
        candidates.append(result)
        print(
            f"  [{candidate['name']}] "
            f"alt2y trades={result['summary']['alt_total_trades']} "
            f"alt_expectancy={result['summary']['alt_avg_expectancy']:+.4f} "
            f"alt_excess={result['summary']['alt_avg_excess_return']:+.4f}"
        )

    viable = [c for c in candidates if c["summary"]["alt_total_trades"] > 0]
    ranking_pool = viable if viable else candidates
    ranked = sorted(
        ranking_pool,
        key=lambda c: (
            c["summary"]["alt_avg_expectancy"],
            c["summary"]["alt_avg_excess_return"],
            c["summary"]["alt_total_trades"],
        ),
        reverse=True,
    )
    best = ranked[0]
    verdict = _verdict(best)

    report = {
        "as_of": AS_OF,
        "strategy": "regime_relative_breakout_30m",
        "scope": "Stage 2 in-sample only; no walk-forward/live/paper/UI/KPI",
        "interval": "minute30",
        "tickers": TICKERS,
        "regime_ticker": REGIME_TICKER,
        "lookback_windows": LOOKBACK_WINDOWS,
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "base_params": BASE_PARAMS,
        "candidate_count": len(candidates),
        "ranked_candidates": ranked,
        "best_candidate": best,
        "verdict": verdict,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.out)
    print(
        json.dumps(
            {
                "best": best["name"],
                "summary": best["summary"],
                "verdict": verdict,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

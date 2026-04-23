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
    # Original nine (kept for continuity with 0001 handoff).
    {"name": "base_stop2_trail3_hold48_confirm2", "overrides": {}},
    {"name": "stop15_trail3_hold48_confirm2", "overrides": {"initial_stop_atr_mult": 1.5}},
    {"name": "stop25_trail3_hold48_confirm2", "overrides": {"initial_stop_atr_mult": 2.5}},
    {"name": "stop2_trail25_hold48_confirm2", "overrides": {"atr_trailing_mult": 2.5}},
    {"name": "stop2_trail35_hold48_confirm2", "overrides": {"atr_trailing_mult": 3.5}},
    {"name": "stop2_trail3_hold24_confirm2", "overrides": {"max_hold_bars_30m": 24}},
    {"name": "stop2_trail3_hold72_confirm2", "overrides": {"max_hold_bars_30m": 72}},
    {"name": "stop2_trail3_hold48_confirm1", "overrides": {"trend_exit_confirm_bars": 1}},
    {"name": "stop2_trail3_hold48_confirm3", "overrides": {"trend_exit_confirm_bars": 3}},
    # 0002 REVISE additions — frozen confirm=2, wider trailing (+ one with
    # looser hold and one paired with wider initial stop).
    {"name": "stop2_trail40_hold48_confirm2", "overrides": {"atr_trailing_mult": 4.0}},
    {"name": "stop2_trail50_hold48_confirm2", "overrides": {"atr_trailing_mult": 5.0}},
    {"name": "stop2_trail40_hold72_confirm2", "overrides": {"atr_trailing_mult": 4.0, "max_hold_bars_30m": 72}},
    {"name": "stop2_trail50_hold72_confirm2", "overrides": {"atr_trailing_mult": 5.0, "max_hold_bars_30m": 72}},
    {"name": "stop25_trail40_hold72_confirm2", "overrides": {"initial_stop_atr_mult": 2.5, "atr_trailing_mult": 4.0, "max_hold_bars_30m": 72}},
    {"name": "stop25_trail50_hold72_confirm2", "overrides": {"initial_stop_atr_mult": 2.5, "atr_trailing_mult": 5.0, "max_hold_bars_30m": 72}},
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


def benchmark_mdd(close_series: pd.Series) -> float:
    """Buy-and-hold max drawdown (negative number) over the sample window."""
    closes = close_series.dropna()
    if len(closes) < 2:
        return 0.0
    first = float(closes.iloc[0])
    if first <= 0:
        return 0.0
    equity = closes / first
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    return float(drawdown.min())


def _ret_over_abs_mdd(ret: float, mdd_val: float) -> float:
    if mdd_val >= 0:
        return 0.0
    return ret / abs(mdd_val)


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
    bench_mdd = benchmark_mdd(sample["close"])
    strat_mdd = result.mdd
    strat_r_over_m = _ret_over_abs_mdd(result.cumulative_return, strat_mdd)
    bench_r_over_m = _ret_over_abs_mdd(benchmark, bench_mdd)
    mdd_improvement_abs = strat_mdd - bench_mdd  # both negative; positive means strategy smaller drawdown
    mdd_improvement_ratio = (
        abs(strat_mdd) / abs(bench_mdd) if bench_mdd < 0 else 0.0
    )  # lower is better; 1.0 = equal drawdown
    return {
        "start": str(sample.index[0]),
        "end": str(sample.index[-1]),
        "cumulative_return": result.cumulative_return,
        "benchmark_return": benchmark,
        "excess_return": result.cumulative_return - benchmark,
        "mdd": strat_mdd,
        "benchmark_mdd": bench_mdd,
        "strategy_return_over_abs_mdd": strat_r_over_m,
        "benchmark_return_over_abs_mdd": bench_r_over_m,
        "mdd_improvement_abs": mdd_improvement_abs,
        "mdd_improvement_ratio": mdd_improvement_ratio,
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


RISK_MDD_IMPROVEMENT_MIN = 0.20
RISK_MDD_RATIO_MAX = 0.40
RISK_ADJUSTED_MIN_TRADES_PER_ALT = 80
HOLD_BARS_MIN = 4
HOLD_BARS_MAX = 72
TIME_EXIT_SHARE_MAX = 0.25


def classify_verdict(
    eth_2y: dict[str, Any],
    xrp_2y: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Pure verdict helper, testable without a full candidate.

    Evaluates the 0002-spec gate set and returns label + pass_type + gates.
    """
    eth_trades = eth_2y["total_trades"]
    xrp_trades = xrp_2y["total_trades"]
    alt_trades = eth_trades + xrp_trades
    eth_exp = eth_2y["expectancy"]
    xrp_exp = xrp_2y["expectancy"]
    alt_expectancy = (
        (eth_exp * eth_trades + xrp_exp * xrp_trades) / alt_trades if alt_trades else 0.0
    )
    alt_excess = (eth_2y["excess_return"] + xrp_2y["excess_return"]) / 2.0
    avg_hold_bars = summary.get("avg_hold_bars", 0.0)
    time_exit_share = summary.get("time_exit_share", 0.0)

    excess_positive = alt_excess > 0

    eth_bench_mdd = eth_2y.get("benchmark_mdd", 0.0)
    xrp_bench_mdd = xrp_2y.get("benchmark_mdd", 0.0)
    risk_adjusted_ok = all(
        [
            eth_2y["cumulative_return"] > 0,
            xrp_2y["cumulative_return"] > 0,
            eth_exp > 0,
            xrp_exp > 0,
            eth_2y.get("mdd_improvement_abs", 0.0) > RISK_MDD_IMPROVEMENT_MIN,
            xrp_2y.get("mdd_improvement_abs", 0.0) > RISK_MDD_IMPROVEMENT_MIN,
            abs(eth_2y["mdd"]) <= abs(eth_bench_mdd) * RISK_MDD_RATIO_MAX
            if eth_bench_mdd < 0
            else False,
            abs(xrp_2y["mdd"]) <= abs(xrp_bench_mdd) * RISK_MDD_RATIO_MAX
            if xrp_bench_mdd < 0
            else False,
            eth_2y.get("strategy_return_over_abs_mdd", 0.0)
            > eth_2y.get("benchmark_return_over_abs_mdd", 0.0),
            xrp_2y.get("strategy_return_over_abs_mdd", 0.0)
            > xrp_2y.get("benchmark_return_over_abs_mdd", 0.0),
        ]
    )
    excess_or_risk = excess_positive or risk_adjusted_ok

    # Stop-trigger condition: trade count sufficient but both alts negative on
    # expectancy AND excess.
    stop_trigger = (
        eth_trades >= 20
        and xrp_trades >= 20
        and eth_exp < 0
        and xrp_exp < 0
        and eth_2y["excess_return"] < 0
        and xrp_2y["excess_return"] < 0
    )

    gates = {
        "alt_2y_trades_ge_50": alt_trades >= 50,
        "eth_2y_trades_ge_20": eth_trades >= 20,
        "xrp_2y_trades_ge_20": xrp_trades >= 20,
        "eth_2y_trades_ge_80": eth_trades >= RISK_ADJUSTED_MIN_TRADES_PER_ALT,
        "xrp_2y_trades_ge_80": xrp_trades >= RISK_ADJUSTED_MIN_TRADES_PER_ALT,
        "alt_2y_expectancy_positive": alt_expectancy > 0,
        "eth_2y_expectancy_positive": eth_exp > 0,
        "xrp_2y_expectancy_positive": xrp_exp > 0,
        "eth_2y_cum_return_positive": eth_2y["cumulative_return"] > 0,
        "xrp_2y_cum_return_positive": xrp_2y["cumulative_return"] > 0,
        "alt_2y_excess_positive_raw": excess_positive,
        "alt_2y_risk_adjusted_ok": risk_adjusted_ok,
        "alt_2y_excess_or_risk_adjusted": excess_or_risk,
        "avg_hold_bars_4_to_72": HOLD_BARS_MIN <= avg_hold_bars <= HOLD_BARS_MAX,
        "time_exit_share_le_25pct": time_exit_share <= TIME_EXIT_SHARE_MAX,
    }

    base_count_pass = (
        gates["alt_2y_trades_ge_50"]
        and gates["eth_2y_trades_ge_20"]
        and gates["xrp_2y_trades_ge_20"]
    )
    mdd_guard_pass = gates["eth_2y_trades_ge_80"] and gates["xrp_2y_trades_ge_80"]
    perf_pass = (
        gates["alt_2y_expectancy_positive"]
        and gates["eth_2y_expectancy_positive"]
        and gates["xrp_2y_expectancy_positive"]
        and gates["eth_2y_cum_return_positive"]
        and gates["xrp_2y_cum_return_positive"]
        and gates["alt_2y_excess_or_risk_adjusted"]
        and gates["avg_hold_bars_4_to_72"]
        and gates["time_exit_share_le_25pct"]
    )

    pass_type: str | None = None
    if base_count_pass and mdd_guard_pass and perf_pass:
        if excess_positive:
            label = "PASS"
            pass_type = "pure_excess"
        else:
            label = "PASS_RISK_ADJUSTED"
            pass_type = "risk_adjusted"
    elif stop_trigger and base_count_pass:
        label = "STOP"
    elif base_count_pass:
        label = "REVISE"
    else:
        label = "HOLD"

    return {
        "label": label,
        "pass_type": pass_type,
        "gates": gates,
        "alt_2y_trades": alt_trades,
        "alt_2y_expectancy": alt_expectancy,
        "alt_2y_excess_return": alt_excess,
    }


def _verdict(candidate: dict[str, Any]) -> dict[str, Any]:
    results2 = candidate["results"]["2y"]
    return classify_verdict(results2["KRW-ETH"], results2["KRW-XRP"], candidate["summary"])


def _risk_adjusted_sort_key(candidate: dict[str, Any]) -> tuple:
    """Sort tuple aligned with 0002 spec §4.4."""
    verdict = candidate.get("verdict") or _verdict(candidate)
    label = verdict["label"]
    # Pass tier beats revise beats hold/stop.
    tier = {"PASS": 3, "PASS_RISK_ADJUSTED": 2, "REVISE": 1}.get(label, 0)
    risk_ok = verdict["gates"]["alt_2y_risk_adjusted_ok"]
    summary = candidate["summary"]
    eth2 = candidate["results"]["2y"]["KRW-ETH"]
    xrp2 = candidate["results"]["2y"]["KRW-XRP"]
    alt_return_over_abs_mdd = (
        eth2.get("strategy_return_over_abs_mdd", 0.0)
        + xrp2.get("strategy_return_over_abs_mdd", 0.0)
    ) / 2.0
    return (
        tier,
        risk_ok,
        summary["alt_avg_expectancy"],
        alt_return_over_abs_mdd,
        -summary["time_exit_share"],
        summary["alt_total_trades"],
    )


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
        result["verdict"] = _verdict(result)
        candidates.append(result)
        print(
            f"  [{candidate['name']}] "
            f"alt2y trades={result['summary']['alt_total_trades']} "
            f"alt_expectancy={result['summary']['alt_avg_expectancy']:+.4f} "
            f"alt_excess={result['summary']['alt_avg_excess_return']:+.4f} "
            f"risk_adj={result['verdict']['gates']['alt_2y_risk_adjusted_ok']}"
        )

    viable = [c for c in candidates if c["summary"]["alt_total_trades"] > 0]
    ranking_pool = viable if viable else candidates
    # Previous (pure-expectancy) ranking kept for continuity with 0001 handoff.
    ranked = sorted(
        ranking_pool,
        key=lambda c: (
            c["summary"]["alt_avg_expectancy"],
            c["summary"]["alt_avg_excess_return"],
            c["summary"]["alt_total_trades"],
        ),
        reverse=True,
    )
    risk_adjusted_ranked = sorted(
        ranking_pool,
        key=_risk_adjusted_sort_key,
        reverse=True,
    )
    # Use risk-adjusted top as the primary best (Codex directive in 0002).
    best = risk_adjusted_ranked[0]
    verdict = best["verdict"]

    report = {
        "as_of": AS_OF,
        "strategy": "regime_relative_breakout_30m",
        "scope": "Stage 2 in-sample only; no walk-forward/live/paper/UI/KPI",
        "revision": "0002_risk_adjusted",
        "interval": "minute30",
        "tickers": TICKERS,
        "regime_ticker": REGIME_TICKER,
        "lookback_windows": LOOKBACK_WINDOWS,
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "base_params": BASE_PARAMS,
        "candidate_count": len(candidates),
        "ranked_candidates": ranked,
        "risk_adjusted_ranked_candidates": risk_adjusted_ranked,
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

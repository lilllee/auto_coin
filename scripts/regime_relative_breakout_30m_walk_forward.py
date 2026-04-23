"""Walk-forward validation for ``regime_relative_breakout_30m``.

Codex 0003 bounded authorization:

- No live/paper/UI/KPI/settings changes.
- No strategy entry/exit logic changes (frozen at commit ``e356891``).
- No additional in-sample parameter expansion.  Candidate set fixed at 4.
- No trail60/trail70.
- No reversion exit.

Design (per spec §4):

    train window : 180 days
    test  window :  60 days
    step         :  60 days
    warmup       : 100 days (reserved before the first fold so that daily
                             SMA100 + 7d RS have confirmed values).

For each fold, rank the 4 fixed candidates using their ETH+XRP train-window
risk-adjusted tuple and pick exactly one for the next OOS test window.
We also record each candidate's OOS performance on every fold so Codex can
see the fixed-candidate picture alongside the adaptive-selection picture.
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
REPORT_PATH = Path("reports/2026-04-23-regime-relative-breakout-30m-walk-forward.json")
TICKERS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]
ALT_TICKERS = ["KRW-ETH", "KRW-XRP"]
REGIME_TICKER = "KRW-BTC"
FETCH_DAYS = 830
WARMUP_DAYS = 100
TRAIN_DAYS = 180
TEST_DAYS = 60
STEP_DAYS = 60
INTERVAL = "minute30"

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
    # Candidate-specific overrides override the following three + confirm:
    "initial_stop_atr_mult": 2.0,
    "atr_trailing_mult": 3.0,
    "trend_exit_confirm_bars": 2,
    "max_hold_bars_30m": 48,
}

CANDIDATES: list[dict[str, Any]] = [
    {
        "name": "wf_a_stop2_trail50_hold72_confirm2",
        "overrides": {"atr_trailing_mult": 5.0, "max_hold_bars_30m": 72},
    },
    {
        "name": "wf_b_stop25_trail40_hold72_confirm2",
        "overrides": {
            "initial_stop_atr_mult": 2.5,
            "atr_trailing_mult": 4.0,
            "max_hold_bars_30m": 72,
        },
    },
    {
        "name": "wf_c_stop2_trail40_hold72_confirm2",
        "overrides": {"atr_trailing_mult": 4.0, "max_hold_bars_30m": 72},
    },
    {
        "name": "wf_d_stop2_trail35_hold48_confirm2",
        "overrides": {"atr_trailing_mult": 3.5},
    },
]

# ---------------------------------------------------------------------------
# Data fetch + small pure helpers (mirrors Stage 2 patterns)
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


def _slice_range(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df.loc[(df.index >= start) & (df.index < end)].copy()


def _benchmark_return(sample: pd.DataFrame) -> float:
    closes = sample["close"].dropna()
    if len(closes) < 2:
        return 0.0
    first = float(closes.iloc[0])
    last = float(closes.iloc[-1])
    return last / first - 1.0 if first > 0 else 0.0


def benchmark_mdd(close_series: pd.Series) -> float:
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
            "avg_hold_bars": avg_hold_days * 48.0,
        }
    return out


# ---------------------------------------------------------------------------
# Fold schedule
# ---------------------------------------------------------------------------


def generate_folds(
    data_start: pd.Timestamp,
    data_end: pd.Timestamp,
    *,
    warmup_days: int = WARMUP_DAYS,
    train_days: int = TRAIN_DAYS,
    test_days: int = TEST_DAYS,
    step_days: int = STEP_DAYS,
) -> list[dict[str, Any]]:
    """Produce [train_start, train_end) → [test_start, test_end) folds.

    The first train_start is ``data_start + warmup_days`` so features have
    a confirmed tail before the fold's first bar. Steps advance train_start
    by ``step_days`` until the next test window would cross ``data_end``.
    """
    folds: list[dict[str, Any]] = []
    train_start = data_start + pd.Timedelta(days=warmup_days)
    idx = 0
    while True:
        train_end = train_start + pd.Timedelta(days=train_days)
        test_start = train_end
        test_end = test_start + pd.Timedelta(days=test_days)
        if test_end > data_end:
            break
        folds.append(
            {
                "fold": idx,
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        idx += 1
        train_start += pd.Timedelta(days=step_days)
    return folds


# ---------------------------------------------------------------------------
# Per-window backtest metrics
# ---------------------------------------------------------------------------


def _window_metrics(enriched: pd.DataFrame, strategy, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    sample = _slice_range(enriched, start, end)
    if sample.empty:
        return _empty_metrics()
    result = backtest(
        sample,
        strategy,
        fee=UPBIT_DEFAULT_FEE,
        slippage=DEFAULT_SLIPPAGE,
        interval=INTERVAL,
    )
    bench = _benchmark_return(sample)
    bench_mdd_v = benchmark_mdd(sample["close"])
    strat_mdd = result.mdd
    return {
        "start": sample.index[0].isoformat(),
        "end": sample.index[-1].isoformat(),
        "total_trades": result.n_trades,
        "win_rate": result.win_rate,
        "cumulative_return": result.cumulative_return,
        "benchmark_return": bench,
        "excess_return": result.cumulative_return - bench,
        "expectancy": result.expectancy,
        "mdd": strat_mdd,
        "benchmark_mdd": bench_mdd_v,
        "strategy_return_over_abs_mdd": _ret_over_abs_mdd(result.cumulative_return, strat_mdd),
        "benchmark_return_over_abs_mdd": _ret_over_abs_mdd(bench, bench_mdd_v),
        "mdd_improvement_abs": strat_mdd - bench_mdd_v,
        "avg_hold_bars": result.avg_hold_days * 48.0,
        "exit_mix": _exit_mix(result),
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "start": None,
        "end": None,
        "total_trades": 0,
        "win_rate": 0.0,
        "cumulative_return": 0.0,
        "benchmark_return": 0.0,
        "excess_return": 0.0,
        "expectancy": 0.0,
        "mdd": 0.0,
        "benchmark_mdd": 0.0,
        "strategy_return_over_abs_mdd": 0.0,
        "benchmark_return_over_abs_mdd": 0.0,
        "mdd_improvement_abs": 0.0,
        "avg_hold_bars": 0.0,
        "exit_mix": {},
    }


# ---------------------------------------------------------------------------
# Train-window candidate ranking
# ---------------------------------------------------------------------------


def _alt_score(train_metrics_for_cand: dict[str, dict[str, Any]]) -> tuple:
    """Rank tuple for train-window candidate selection.

    (alt_expectancy, alt_return_over_abs_mdd, alt_total_trades) — higher is
    better. Matches the Stage 2 risk-adjusted ranking spirit but computed
    purely from the train window (no OOS leak).
    """
    eth = train_metrics_for_cand["KRW-ETH"]
    xrp = train_metrics_for_cand["KRW-XRP"]
    eth_trades = eth["total_trades"]
    xrp_trades = xrp["total_trades"]
    alt_trades = eth_trades + xrp_trades
    alt_expectancy = (
        (eth["expectancy"] * eth_trades + xrp["expectancy"] * xrp_trades) / alt_trades
        if alt_trades
        else 0.0
    )
    alt_ret_over_mdd = (
        eth["strategy_return_over_abs_mdd"] + xrp["strategy_return_over_abs_mdd"]
    ) / 2.0
    return (alt_expectancy, alt_ret_over_mdd, alt_trades)


# ---------------------------------------------------------------------------
# Aggregation across folds
# ---------------------------------------------------------------------------


def _aggregate_ticker(fold_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not fold_metrics:
        return _empty_metrics() | {
            "positive_expectancy_fold_ratio": 0.0,
            "positive_cum_fold_ratio": 0.0,
            "positive_risk_adjusted_fold_ratio": 0.0,
            "fold_count": 0,
        }
    trades = sum(m["total_trades"] for m in fold_metrics)
    total_wins = sum(m["win_rate"] * m["total_trades"] for m in fold_metrics)
    expectancy = (
        sum(m["expectancy"] * m["total_trades"] for m in fold_metrics) / trades
        if trades
        else 0.0
    )
    # Geometric chaining of per-fold returns.
    def _chain(values: list[float]) -> float:
        product = 1.0
        for v in values:
            product *= 1.0 + v
        return product - 1.0

    cum_return = _chain([m["cumulative_return"] for m in fold_metrics])
    bench_return = _chain([m["benchmark_return"] for m in fold_metrics])
    excess = cum_return - bench_return
    worst_mdd = min(m["mdd"] for m in fold_metrics)
    worst_bench_mdd = min(m["benchmark_mdd"] for m in fold_metrics)
    return_over_abs_mdd = _ret_over_abs_mdd(cum_return, worst_mdd)
    bench_return_over_abs_mdd = _ret_over_abs_mdd(bench_return, worst_bench_mdd)
    positive_expectancy_folds = sum(1 for m in fold_metrics if m["expectancy"] > 0)
    positive_cum_folds = sum(1 for m in fold_metrics if m["cumulative_return"] > 0)
    positive_risk_adj_folds = sum(
        1
        for m in fold_metrics
        if m["strategy_return_over_abs_mdd"] > m["benchmark_return_over_abs_mdd"]
    )
    n = len(fold_metrics)
    exit_mix_totals: dict[str, int] = defaultdict(int)
    for m in fold_metrics:
        for reason, mix in m["exit_mix"].items():
            exit_mix_totals[reason] += int(mix["trade_count"])

    return {
        "fold_count": n,
        "total_trades": trades,
        "total_wins": int(round(total_wins)),
        "win_rate": total_wins / trades if trades else 0.0,
        "expectancy": expectancy,
        "cumulative_return_chained": cum_return,
        "benchmark_return_chained": bench_return,
        "excess_return_chained": excess,
        "worst_fold_mdd": worst_mdd,
        "worst_fold_benchmark_mdd": worst_bench_mdd,
        "return_over_abs_worst_mdd": return_over_abs_mdd,
        "benchmark_return_over_abs_worst_mdd": bench_return_over_abs_mdd,
        "positive_expectancy_fold_ratio": positive_expectancy_folds / n,
        "positive_cum_fold_ratio": positive_cum_folds / n,
        "positive_risk_adjusted_fold_ratio": positive_risk_adj_folds / n,
        "exit_mix_totals": dict(exit_mix_totals),
    }


def _aggregate_alt(eth_agg: dict[str, Any], xrp_agg: dict[str, Any]) -> dict[str, Any]:
    """Alt-combined aggregate from already-aggregated per-ticker results."""
    eth_tr = eth_agg["total_trades"]
    xrp_tr = xrp_agg["total_trades"]
    alt_tr = eth_tr + xrp_tr
    expectancy = (
        (eth_agg["expectancy"] * eth_tr + xrp_agg["expectancy"] * xrp_tr) / alt_tr
        if alt_tr
        else 0.0
    )
    # For alt chained return, average the two tickers' chained returns (equal weight).
    cum_return = (eth_agg["cumulative_return_chained"] + xrp_agg["cumulative_return_chained"]) / 2.0
    bench_return = (
        eth_agg["benchmark_return_chained"] + xrp_agg["benchmark_return_chained"]
    ) / 2.0
    excess = cum_return - bench_return
    # Alt worst MDD = worst of the two tickers' worst fold MDDs.
    worst_mdd = min(eth_agg["worst_fold_mdd"], xrp_agg["worst_fold_mdd"])
    worst_bench_mdd = min(
        eth_agg["worst_fold_benchmark_mdd"], xrp_agg["worst_fold_benchmark_mdd"]
    )
    return_over_abs_mdd = _ret_over_abs_mdd(cum_return, worst_mdd)
    bench_return_over_abs_mdd = _ret_over_abs_mdd(bench_return, worst_bench_mdd)
    # Alt positive-expectancy fold ratio: a fold counts positive if the
    # alt-combined (ETH+XRP) expectancy on that fold is > 0. Requires raw
    # per-fold data; use the conservative union here (fold positive only if
    # BOTH alts positive that fold isn't strictly required — use pooled).
    # We'll compute the actual alt per-fold ratio outside this helper
    # because we need raw fold data, not aggregated.
    exit_mix = defaultdict(int)
    for reason, count in eth_agg["exit_mix_totals"].items():
        exit_mix[reason] += count
    for reason, count in xrp_agg["exit_mix_totals"].items():
        exit_mix[reason] += count
    return {
        "total_trades": alt_tr,
        "eth_trades": eth_tr,
        "xrp_trades": xrp_tr,
        "expectancy": expectancy,
        "cumulative_return_avg": cum_return,
        "benchmark_return_avg": bench_return,
        "excess_return_avg": excess,
        "worst_fold_mdd": worst_mdd,
        "worst_fold_benchmark_mdd": worst_bench_mdd,
        "return_over_abs_worst_mdd": return_over_abs_mdd,
        "benchmark_return_over_abs_worst_mdd": bench_return_over_abs_mdd,
        "exit_mix_totals": dict(exit_mix),
    }


# ---------------------------------------------------------------------------
# Walk-forward verdict
# ---------------------------------------------------------------------------


def classify_wf_verdict(
    eth_agg: dict[str, Any],
    xrp_agg: dict[str, Any],
    alt_agg: dict[str, Any],
    alt_positive_expectancy_fold_ratio: float,
    time_exit_share: float,
) -> dict[str, Any]:
    """PASS_WF / PASS_WF_RISK_ADJUSTED / REVISE_WF / HOLD_WF / STOP_WF.

    Pure function — inputs are aggregated dicts and two summary scalars.
    """
    eth_trades = eth_agg["total_trades"]
    xrp_trades = xrp_agg["total_trades"]
    alt_trades = alt_agg["total_trades"]

    gates = {
        "oos_alt_trades_ge_60": alt_trades >= 60,
        "oos_eth_trades_ge_25": eth_trades >= 25,
        "oos_xrp_trades_ge_25": xrp_trades >= 25,
        "oos_alt_expectancy_positive": alt_agg["expectancy"] > 0,
        "oos_eth_expectancy_positive": eth_agg["expectancy"] > 0,
        "oos_xrp_expectancy_positive": xrp_agg["expectancy"] > 0,
        "oos_eth_cum_return_positive": eth_agg["cumulative_return_chained"] > 0,
        "oos_xrp_cum_return_positive": xrp_agg["cumulative_return_chained"] > 0,
        "oos_risk_adjusted_edge_positive": (
            alt_agg["return_over_abs_worst_mdd"]
            > alt_agg["benchmark_return_over_abs_worst_mdd"]
        ),
        "positive_expectancy_folds_ge_60pct": alt_positive_expectancy_fold_ratio >= 0.60,
        "time_exit_share_le_30pct": time_exit_share <= 0.30,
    }

    raw_excess_positive = alt_agg["excess_return_avg"] > 0
    count_gates = [
        gates["oos_alt_trades_ge_60"],
        gates["oos_eth_trades_ge_25"],
        gates["oos_xrp_trades_ge_25"],
    ]
    perf_gates = [
        gates["oos_alt_expectancy_positive"],
        gates["oos_eth_expectancy_positive"],
        gates["oos_xrp_expectancy_positive"],
        gates["oos_eth_cum_return_positive"],
        gates["oos_xrp_cum_return_positive"],
        gates["oos_risk_adjusted_edge_positive"],
        gates["positive_expectancy_folds_ge_60pct"],
        gates["time_exit_share_le_30pct"],
    ]
    stop_trigger = (
        all(count_gates)
        and eth_agg["expectancy"] <= 0
        and xrp_agg["expectancy"] <= 0
    )

    pass_type: str | None = None
    if all(count_gates) and all(perf_gates):
        if raw_excess_positive:
            label = "PASS_WF"
            pass_type = "pure"
        else:
            label = "PASS_WF_RISK_ADJUSTED"
            pass_type = "risk_adjusted"
    elif stop_trigger:
        label = "STOP_WF"
    elif all(count_gates) and 1 <= sum(1 for g in perf_gates if not g) <= 3:
        label = "REVISE_WF"
    else:
        label = "HOLD_WF"
    return {"label": label, "pass_type": pass_type, "gates": gates}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _time_exit_share(exit_mix_totals: dict[str, int]) -> float:
    total = sum(exit_mix_totals.values())
    if not total:
        return 0.0
    time_hits = sum(
        count for reason, count in exit_mix_totals.items() if reason.endswith("_time_exit")
    )
    return time_hits / total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-days", type=int, default=FETCH_DAYS)
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    parser.add_argument("--train-days", type=int, default=TRAIN_DAYS)
    parser.add_argument("--test-days", type=int, default=TEST_DAYS)
    parser.add_argument("--step-days", type=int, default=STEP_DAYS)
    parser.add_argument("--warmup-days", type=int, default=WARMUP_DAYS)
    args = parser.parse_args(argv)

    print(f"fetch minute30 for {TICKERS}")
    thirty = {t: _fetch_ohlcv(t, "minute30", args.fetch_days) for t in TICKERS}
    print(f"fetch minute60 for {TICKERS}")
    hourly = {t: _fetch_ohlcv(t, "minute60", args.fetch_days) for t in TICKERS}
    print(f"fetch day for {REGIME_TICKER}")
    btc_daily = _fetch_ohlcv(REGIME_TICKER, "day", args.fetch_days)
    btc_30m = thirty[REGIME_TICKER]

    # All 4 candidates share the same enrichment parameters (only exit params differ),
    # so we enrich each ticker once and reuse.
    enriched: dict[str, pd.DataFrame] = {}
    for ticker in ALT_TICKERS:
        enriched[ticker] = enrich_regime_relative_breakout_30m(
            thirty[ticker],
            daily_regime_df=btc_daily,
            daily_regime_ma_window=BASE_PARAMS["daily_regime_ma_window"],
            hourly_setup_df=hourly[ticker],
            hourly_ema_fast=BASE_PARAMS["hourly_ema_fast"],
            hourly_ema_slow=BASE_PARAMS["hourly_ema_slow"],
            hourly_slope_lookback=BASE_PARAMS["hourly_slope_lookback"],
            rs_reference_df=btc_30m,
            rs_24h_bars_30m=BASE_PARAMS["rs_24h_bars_30m"],
            rs_7d_bars_30m=BASE_PARAMS["rs_7d_bars_30m"],
            breakout_lookback_30m=BASE_PARAMS["breakout_lookback_30m"],
            volume_window_30m=BASE_PARAMS["volume_window_30m"],
            atr_window=BASE_PARAMS["atr_window"],
        )

    data_start = min(df.index.min() for df in enriched.values())
    data_end = min(df.index.max() for df in enriched.values())
    folds = generate_folds(
        data_start,
        data_end,
        warmup_days=args.warmup_days,
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
    )
    print(f"{len(folds)} folds  data_start={data_start}  data_end={data_end}")

    # Pre-instantiate strategies per candidate (stateless).
    strategies = {
        cand["name"]: create_strategy(
            "regime_relative_breakout_30m", {**BASE_PARAMS, **cand["overrides"]}
        )
        for cand in CANDIDATES
    }

    fold_records: list[dict[str, Any]] = []
    for fold in folds:
        fold_id = fold["fold"]
        train_metrics: dict[str, dict[str, Any]] = {}
        test_metrics: dict[str, dict[str, Any]] = {}
        for cand in CANDIDATES:
            strategy = strategies[cand["name"]]
            train_metrics[cand["name"]] = {
                ticker: _window_metrics(
                    enriched[ticker], strategy, fold["train_start"], fold["train_end"]
                )
                for ticker in ALT_TICKERS
            }
            test_metrics[cand["name"]] = {
                ticker: _window_metrics(
                    enriched[ticker], strategy, fold["test_start"], fold["test_end"]
                )
                for ticker in ALT_TICKERS
            }

        ranked_candidates = sorted(
            CANDIDATES,
            key=lambda c: _alt_score(train_metrics[c["name"]]),
            reverse=True,
        )
        selected = ranked_candidates[0]["name"]
        selected_test = test_metrics[selected]
        print(
            f"  fold {fold_id:2d}  train [{fold['train_start'].date()}..{fold['train_end'].date()})"
            f"  test [{fold['test_start'].date()}..{fold['test_end'].date()})"
            f"  selected={selected}"
            f"  test ETH exp={selected_test['KRW-ETH']['expectancy']:+.4f}"
            f"  XRP exp={selected_test['KRW-XRP']['expectancy']:+.4f}"
        )
        fold_records.append(
            {
                "fold": fold_id,
                "train_start": fold["train_start"].isoformat(),
                "train_end": fold["train_end"].isoformat(),
                "test_start": fold["test_start"].isoformat(),
                "test_end": fold["test_end"].isoformat(),
                "train_ranking": [c["name"] for c in ranked_candidates],
                "selected_candidate": selected,
                "train_metrics": train_metrics,
                "test_metrics": test_metrics,
            }
        )

    # --- Selected-candidate OOS aggregate (per-fold switching) ---
    selected_eth_folds = [fr["test_metrics"][fr["selected_candidate"]]["KRW-ETH"] for fr in fold_records]
    selected_xrp_folds = [fr["test_metrics"][fr["selected_candidate"]]["KRW-XRP"] for fr in fold_records]
    selected_eth_agg = _aggregate_ticker(selected_eth_folds)
    selected_xrp_agg = _aggregate_ticker(selected_xrp_folds)
    selected_alt_agg = _aggregate_alt(selected_eth_agg, selected_xrp_agg)
    selected_alt_positive_expectancy_fold_ratio = (
        sum(
            1
            for eth, xrp in zip(selected_eth_folds, selected_xrp_folds, strict=False)
            if _fold_alt_expectancy(eth, xrp) > 0
        )
        / len(fold_records)
        if fold_records
        else 0.0
    )
    selected_time_exit_share = _time_exit_share(selected_alt_agg["exit_mix_totals"])
    selected_oos_summary = {
        "by_ticker": {"KRW-ETH": selected_eth_agg, "KRW-XRP": selected_xrp_agg},
        "alt_combined": selected_alt_agg,
        "positive_alt_expectancy_fold_ratio": selected_alt_positive_expectancy_fold_ratio,
        "time_exit_share": selected_time_exit_share,
    }

    # --- Fixed-candidate OOS comparison (no per-fold switching) ---
    fixed_oos_summary: dict[str, Any] = {}
    for cand in CANDIDATES:
        eth_folds = [fr["test_metrics"][cand["name"]]["KRW-ETH"] for fr in fold_records]
        xrp_folds = [fr["test_metrics"][cand["name"]]["KRW-XRP"] for fr in fold_records]
        eth_agg = _aggregate_ticker(eth_folds)
        xrp_agg = _aggregate_ticker(xrp_folds)
        alt_agg = _aggregate_alt(eth_agg, xrp_agg)
        alt_pos_exp_ratio = (
            sum(
                1
                for eth, xrp in zip(eth_folds, xrp_folds, strict=False)
                if _fold_alt_expectancy(eth, xrp) > 0
            )
            / len(fold_records)
            if fold_records
            else 0.0
        )
        time_share = _time_exit_share(alt_agg["exit_mix_totals"])
        fixed_oos_summary[cand["name"]] = {
            "by_ticker": {"KRW-ETH": eth_agg, "KRW-XRP": xrp_agg},
            "alt_combined": alt_agg,
            "positive_alt_expectancy_fold_ratio": alt_pos_exp_ratio,
            "time_exit_share": time_share,
        }

    verdict = classify_wf_verdict(
        selected_eth_agg,
        selected_xrp_agg,
        selected_alt_agg,
        selected_alt_positive_expectancy_fold_ratio,
        selected_time_exit_share,
    )

    report = {
        "as_of": AS_OF,
        "strategy": "regime_relative_breakout_30m",
        "scope": "walk-forward validation only; no live/paper/UI/KPI",
        "interval": INTERVAL,
        "tickers": TICKERS,
        "alt_tickers": ALT_TICKERS,
        "regime_ticker": REGIME_TICKER,
        "fetch_days": args.fetch_days,
        "fold_config": {
            "train_days": args.train_days,
            "test_days": args.test_days,
            "step_days": args.step_days,
            "warmup_days": args.warmup_days,
        },
        "base_params": BASE_PARAMS,
        "candidates": CANDIDATES,
        "num_folds": len(fold_records),
        "folds": fold_records,
        "selected_candidate_oos_summary": selected_oos_summary,
        "fixed_candidate_oos_summary": fixed_oos_summary,
        "verdict": verdict,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(args.out)
    print(
        json.dumps(
            {
                "num_folds": len(fold_records),
                "selected_folds_summary": {
                    "alt_trades": selected_alt_agg["total_trades"],
                    "alt_expectancy": selected_alt_agg["expectancy"],
                    "alt_excess_avg": selected_alt_agg["excess_return_avg"],
                    "alt_return_over_abs_mdd": selected_alt_agg[
                        "return_over_abs_worst_mdd"
                    ],
                    "alt_bench_return_over_abs_mdd": selected_alt_agg[
                        "benchmark_return_over_abs_worst_mdd"
                    ],
                    "positive_alt_expectancy_fold_ratio": selected_alt_positive_expectancy_fold_ratio,
                    "time_exit_share": selected_time_exit_share,
                },
                "verdict": verdict,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


def _fold_alt_expectancy(eth: dict[str, Any], xrp: dict[str, Any]) -> float:
    eth_tr = eth["total_trades"]
    xrp_tr = xrp["total_trades"]
    alt_tr = eth_tr + xrp_tr
    if not alt_tr:
        return 0.0
    return (eth["expectancy"] * eth_tr + xrp["expectancy"] * xrp_tr) / alt_tr


if __name__ == "__main__":
    raise SystemExit(main())

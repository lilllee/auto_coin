"""Daily regime + 1H reclaim mean reversion Stage 2 in-sample screening."""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import product
from pathlib import Path

import pandas as pd
import pyupbit

from auto_coin.backtest.runner import DEFAULT_SLIPPAGE, UPBIT_DEFAULT_FEE, backtest
from auto_coin.data.candles import enrich_for_strategy, history_days_to_candles
from auto_coin.strategy import create_strategy

AS_OF = "2026-04-23"
FETCH_DAYS = 900
LOOKBACK_WINDOWS = {
    "1y": 365,
    "2y": 730,
}
CORE_TICKERS = ["KRW-BTC", "KRW-ETH"]
OPTIONAL_TICKER = "KRW-XRP"

DEFAULT_PARAMS = {
    "regime_interval": "day",
    "daily_regime_ma_window": 100,
    "dip_lookback_bars": 6,
    "pullback_threshold_pct": -0.015,
    "rsi_window": 14,
    "rsi_threshold": 45.0,
    "reclaim_ema_window": 4,
    "max_hold_bars": 24,
    "atr_window": 14,
    "atr_trailing_mult": 1.5,
}

GRID = {
    "dip_lookback_bars": [4, 6],
    "pullback_threshold_pct": [-0.01, -0.015, -0.02],
    "rsi_threshold": [40.0, 45.0, 50.0],
    "reclaim_ema_window": [3, 4],
    "max_hold_bars": [18, 24],
    "atr_trailing_mult": [1.5, 2.0],
}


def _slice_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    start = df.index.max() - pd.Timedelta(days=days)
    return df.loc[df.index >= start].copy()


def _fetch_all() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    hourly: dict[str, pd.DataFrame] = {}
    daily: dict[str, pd.DataFrame] = {}
    for ticker in [*CORE_TICKERS, OPTIONAL_TICKER]:
        hdf = pyupbit.get_ohlcv(
            ticker,
            interval="minute60",
            count=history_days_to_candles(FETCH_DAYS, "minute60"),
        )
        ddf = pyupbit.get_ohlcv(ticker, interval="day", count=FETCH_DAYS)
        if hdf is None or hdf.empty:
            raise SystemExit(f"failed to fetch hourly candles for {ticker}")
        if ddf is None or ddf.empty:
            raise SystemExit(f"failed to fetch daily candles for {ticker}")
        hourly[ticker] = hdf
        daily[ticker] = ddf
    return hourly, daily


def _exit_mix(result) -> dict[str, dict[str, float | int]]:
    bucket = defaultdict(list)
    for trade in result.trades:
        bucket[trade.exit_type].append(trade)

    out: dict[str, dict[str, float | int]] = {}
    for reason, trades in bucket.items():
        avg_hold_days = sum((t.exit_date - t.entry_date).total_seconds() for t in trades) / len(trades) / (24 * 60 * 60)
        out[reason] = {
            "trade_count": len(trades),
            "ratio": len(trades) / result.n_trades if result.n_trades else 0.0,
            "avg_return": sum(t.ret for t in trades) / len(trades),
            "avg_hold_days": avg_hold_days,
            "avg_hold_bars": avg_hold_days * 24.0,
        }
    return out


def _run_one(
    hourly: dict[str, pd.DataFrame],
    daily: dict[str, pd.DataFrame],
    ticker: str,
    params: dict,
    *,
    lookback_days: int,
) -> dict:
    sample = _slice_days(hourly[ticker], lookback_days)
    run_params = {**params, "regime_ticker": ticker}
    enriched = enrich_for_strategy(
        sample,
        "regime_reclaim_1h",
        run_params,
        regime_df=daily[ticker],
        interval="minute60",
    )
    strategy = create_strategy("regime_reclaim_1h", run_params)
    result = backtest(
        enriched,
        strategy,
        fee=UPBIT_DEFAULT_FEE,
        slippage=DEFAULT_SLIPPAGE,
        interval="minute60",
    )
    closes = sample["close"].dropna()
    benchmark = (
        float(closes.iloc[-1] / closes.iloc[0] - 1.0)
        if len(closes) >= 2 and float(closes.iloc[0]) > 0
        else 0.0
    )
    excess = result.cumulative_return - benchmark
    return {
        "start": str(sample.index[0]),
        "end": str(sample.index[-1]),
        "cumulative_return": result.cumulative_return,
        "benchmark_return": benchmark,
        "excess_return": excess,
        "mdd": result.mdd,
        "sharpe": result.sharpe_ratio,
        "total_trades": result.n_trades,
        "win_rate": result.win_rate,
        "avg_hold_days": result.avg_hold_days,
        "avg_hold_bars": result.avg_hold_days * 24.0,
        "expectancy": result.expectancy,
        "exit_mix": _exit_mix(result),
    }


def _iter_grid():
    for bars, pullback, rsi, ema, hold, atr_mult in product(
        GRID["dip_lookback_bars"],
        GRID["pullback_threshold_pct"],
        GRID["rsi_threshold"],
        GRID["reclaim_ema_window"],
        GRID["max_hold_bars"],
        GRID["atr_trailing_mult"],
    ):
        yield {
            **DEFAULT_PARAMS,
            "dip_lookback_bars": bars,
            "pullback_threshold_pct": pullback,
            "rsi_threshold": rsi,
            "reclaim_ema_window": ema,
            "max_hold_bars": hold,
            "atr_trailing_mult": atr_mult,
        }


def _summarize_candidate(hourly: dict[str, pd.DataFrame], daily: dict[str, pd.DataFrame], params: dict) -> dict:
    by_ticker = {
        ticker: _run_one(hourly, daily, ticker, params, lookback_days=LOOKBACK_WINDOWS["1y"])
        for ticker in CORE_TICKERS
    }
    total_trades = sum(result["total_trades"] for result in by_ticker.values())
    time_share = sum(
        result["exit_mix"].get("regime_reclaim_1h_time_exit", {}).get("trade_count", 0)
        for result in by_ticker.values()
    ) / total_trades if total_trades else 1.0
    non_time_share = 1.0 - time_share if total_trades else 0.0
    return {
        "params": params,
        "btc": by_ticker["KRW-BTC"],
        "eth": by_ticker["KRW-ETH"],
        "avg_excess_return": (
            by_ticker["KRW-BTC"]["excess_return"] + by_ticker["KRW-ETH"]["excess_return"]
        ) / 2.0,
        "min_trades": min(by_ticker["KRW-BTC"]["total_trades"], by_ticker["KRW-ETH"]["total_trades"]),
        "time_exit_share": time_share,
        "non_time_exit_share": non_time_share,
    }


def main() -> int:
    hourly, daily = _fetch_all()
    default_results = {
        window_name: {
            ticker: _run_one(hourly, daily, ticker, DEFAULT_PARAMS, lookback_days=days)
            for ticker in [*CORE_TICKERS, OPTIONAL_TICKER]
        }
        for window_name, days in LOOKBACK_WINDOWS.items()
    }

    rows = [_summarize_candidate(hourly, daily, params) for params in _iter_grid()]
    eligible = [row for row in rows if row["min_trades"] >= 5]
    pool = eligible or rows
    chosen = sorted(
        pool,
        key=lambda row: (
            row["avg_excess_return"],
            row["btc"]["excess_return"],
            row["non_time_exit_share"],
            row["min_trades"],
        ),
        reverse=True,
    )[0]
    chosen_eval = {
        window_name: {
            ticker: _run_one(hourly, daily, ticker, chosen["params"], lookback_days=days)
            for ticker in [*CORE_TICKERS, OPTIONAL_TICKER]
        }
        for window_name, days in LOOKBACK_WINDOWS.items()
    }
    chosen["evaluation"] = chosen_eval

    report = {
        "as_of": AS_OF,
        "strategy": "regime_reclaim_1h",
        "design": "daily regime + 1H pullback + reclaim mean reversion",
        "interval": "minute60",
        "regime_basis": "same-asset daily close > daily SMA(window)",
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "default_params": DEFAULT_PARAMS,
        "grid": GRID,
        "default_results": default_results,
        "top_candidates": sorted(
            pool,
            key=lambda row: (
                row["avg_excess_return"],
                row["btc"]["excess_return"],
                row["non_time_exit_share"],
            ),
            reverse=True,
        )[:10],
        "chosen_candidate": chosen,
    }

    out_path = Path("reports/2026-04-23-regime-reclaim-1h-stage2.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

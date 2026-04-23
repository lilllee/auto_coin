"""RCDB v2 minimal Stage 2 in-sample rescreen."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pyupbit

from auto_coin.backtest.runner import DEFAULT_SLIPPAGE, UPBIT_DEFAULT_FEE, backtest
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy import create_strategy

AS_OF = "2026-04-22"
FETCH_DAYS = 900
LOOKBACK_DAYS = 730
CORE_TICKERS = ["KRW-BTC", "KRW-ETH"]
OPTIONAL_TICKER = "KRW-XRP"

DEFAULT_PARAMS = {
    "regime_ticker": "KRW-BTC",
    "regime_ma_window": 120,
    "dip_lookback_days": 5,
    "vol_window": 20,
    "dip_z_threshold": -1.75,
    "rsi_window": 14,
    "rsi_threshold": 35.0,
    "reversal_ema_window": 5,
    "max_hold_days": 5,
    "atr_window": 14,
    "atr_trailing_mult": 2.0,
}

GRID = {
    "dip_z_threshold": [-2.0, -1.75, -1.5, -1.25, -1.0, -0.75],
    "rsi_threshold": [35.0, 40.0, 45.0, 50.0],
    "reversal_ema_window": [3, 5],
    "max_hold_days": [3, 5, 7],
    "atr_trailing_mult": [1.5, 1.8, 2.0, 2.3],
}


def _slice_2y(df: pd.DataFrame) -> pd.DataFrame:
    start = df.index.max() - pd.Timedelta(days=LOOKBACK_DAYS)
    return df.loc[df.index >= start].copy()


def _fetch_all() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for ticker in [*CORE_TICKERS, OPTIONAL_TICKER]:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=FETCH_DAYS)
        if df is None or df.empty:
            raise SystemExit(f"failed to fetch candles for {ticker}")
        out[ticker] = df
    return out


def _exit_mix(result) -> dict[str, dict[str, float | int]]:
    bucket = defaultdict(list)
    for trade in result.trades:
        bucket[trade.exit_type].append(trade)

    out: dict[str, dict[str, float | int]] = {}
    for reason, trades in bucket.items():
        out[reason] = {
            "trade_count": len(trades),
            "ratio": len(trades) / result.n_trades if result.n_trades else 0.0,
            "avg_return": sum(t.ret for t in trades) / len(trades),
            "avg_hold_days": sum((t.exit_date - t.entry_date).days for t in trades) / len(trades),
        }
    return out


def _run_one(candles: dict[str, pd.DataFrame], ticker: str, params: dict) -> dict:
    regime_df = None if ticker == params["regime_ticker"] else candles[params["regime_ticker"]]
    enriched = enrich_for_strategy(candles[ticker], "rcdb_v2", params, regime_df=regime_df)
    sample = _slice_2y(enriched)
    strategy = create_strategy("rcdb_v2", params)
    result = backtest(sample, strategy, fee=UPBIT_DEFAULT_FEE, slippage=DEFAULT_SLIPPAGE)
    closes = sample["close"].dropna()
    benchmark = (
        float(closes.iloc[-1] / closes.iloc[0] - 1.0)
        if len(closes) >= 2 and float(closes.iloc[0]) > 0
        else 0.0
    )
    excess = result.cumulative_return - benchmark
    return {
        "start": str(sample.index[0].date()),
        "end": str(sample.index[-1].date()),
        "cumulative_return": result.cumulative_return,
        "benchmark_return": benchmark,
        "excess_return": excess,
        "mdd": result.mdd,
        "sharpe": result.sharpe_ratio,
        "total_trades": result.n_trades,
        "win_rate": result.win_rate,
        "avg_hold_days": result.avg_hold_days,
        "expectancy": result.expectancy,
        "exit_mix": _exit_mix(result),
    }


def _iter_grid():
    for dip_z in GRID["dip_z_threshold"]:
        for rsi in GRID["rsi_threshold"]:
            for ema in GRID["reversal_ema_window"]:
                for hold in GRID["max_hold_days"]:
                    for atr_mult in GRID["atr_trailing_mult"]:
                        yield {
                            **DEFAULT_PARAMS,
                            "dip_z_threshold": dip_z,
                            "rsi_threshold": rsi,
                            "reversal_ema_window": ema,
                            "max_hold_days": hold,
                            "atr_trailing_mult": atr_mult,
                        }


def _summarize_candidate(candles: dict[str, pd.DataFrame], params: dict) -> dict:
    by_ticker = {ticker: _run_one(candles, ticker, params) for ticker in CORE_TICKERS}
    total_trades = sum(result["total_trades"] for result in by_ticker.values())
    time_share = sum(
        result["exit_mix"].get("rcdb_v2_time_exit", {}).get("trade_count", 0)
        for result in by_ticker.values()
    ) / total_trades if total_trades else 0.0
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
    candles = _fetch_all()
    default_results = {
        ticker: _run_one(candles, ticker, DEFAULT_PARAMS)
        for ticker in [*CORE_TICKERS, OPTIONAL_TICKER]
    }

    rows = [_summarize_candidate(candles, params) for params in _iter_grid()]
    eligible = [row for row in rows if row["min_trades"] >= 3]
    pool = eligible or rows
    chosen = sorted(
        pool,
        key=lambda row: (
            row["btc"]["excess_return"],
            row["avg_excess_return"],
            row["non_time_exit_share"],
            row["min_trades"],
        ),
        reverse=True,
    )[0]
    chosen["xrp_optional"] = _run_one(candles, OPTIONAL_TICKER, chosen["params"])

    report = {
        "as_of": AS_OF,
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "strategy": "rcdb_v2",
        "design": "vol-normalized dip + reversal confirmation + reversion exit",
        "default_params": DEFAULT_PARAMS,
        "grid": GRID,
        "default_results": default_results,
        "top_candidates_by_btc_excess": sorted(
            pool,
            key=lambda row: (
                row["btc"]["excess_return"],
                row["avg_excess_return"],
                row["non_time_exit_share"],
            ),
            reverse=True,
        )[:10],
        "chosen_candidate": chosen,
    }

    out_path = Path("reports/2026-04-22-rcdb-v2-stage2.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

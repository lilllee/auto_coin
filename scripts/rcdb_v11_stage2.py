"""RCDB v1.1 Stage 2 rescreen.

목적:
- entry strictness 중간 구간 sweep
- exit contribution 분해
- BTC / ETH 일반화 재심사
- walk-forward 전 단계 후보성 판단 근거 생성
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyupbit

from auto_coin.backtest.runner import DEFAULT_SLIPPAGE, UPBIT_DEFAULT_FEE, backtest
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy.base import ExitDecision, PositionSnapshot
from auto_coin.strategy.rcdb import RcdbStrategy

AS_OF = "2026-04-22"
LOOKBACK_DAYS = 730
FETCH_DAYS = 900
TICKERS = ["KRW-BTC", "KRW-ETH"]
OPTIONAL_TICKER = "KRW-XRP"

# RCDB v1.2 bounded redesign axes
DIP_THRESHOLDS = [-0.06, -0.05, -0.045, -0.04]
RSI_THRESHOLDS = [35.0, 38.0, 40.0, 42.0, 45.0]
MAX_HOLDS = [3, 5, 6, 7]
ATR_MULTS = [1.8, 2.0, 2.3, 2.5]


@dataclass(frozen=True)
class RcdbV10Reference(RcdbStrategy):
    """v1 reference: trailing anchored to highest close."""

    def generate_exit(
        self,
        snap,
        position: PositionSnapshot,
    ) -> ExitDecision | None:
        if snap.df.empty or snap.current_price <= 0:
            return None

        last = snap.df.iloc[-1]
        low = last.get("low")
        atr = last.get(self._atr_col)
        regime_on = last.get("regime_on")

        if self._is_finite(low) and self._is_finite(atr):
            trailing_stop = position.highest_close - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(reason="rcdb_trailing_exit", exit_price=trailing_stop)

        if self._is_false(regime_on):
            return ExitDecision(reason="rcdb_regime_off")

        if position.hold_days >= self.max_hold_days:
            return ExitDecision(reason="rcdb_time_exit")

        return None


def fetch_candles() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for ticker in [*TICKERS, OPTIONAL_TICKER]:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=FETCH_DAYS)
        if df is None or df.empty:
            raise SystemExit(f"failed to fetch candles for {ticker}")
        out[ticker] = df
    return out


def _slice_2y(df: pd.DataFrame) -> pd.DataFrame:
    start = df.index.max() - pd.Timedelta(days=LOOKBACK_DAYS)
    return df.loc[df.index >= start].copy()


def _exit_stats(result) -> dict[str, dict[str, float | int]]:
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


def run_one(
    candles: dict[str, pd.DataFrame],
    ticker: str,
    params: dict,
    *,
    strategy_cls: type[RcdbStrategy] = RcdbStrategy,
) -> dict:
    regime_df = None if ticker == params["regime_ticker"] else candles[params["regime_ticker"]]
    enriched = enrich_for_strategy(candles[ticker], "rcdb", params, regime_df=regime_df)
    sample = _slice_2y(enriched)
    strategy = strategy_cls(**params)
    result = backtest(
        sample,
        strategy,
        fee=UPBIT_DEFAULT_FEE,
        slippage=DEFAULT_SLIPPAGE,
    )
    return {
        "start": str(sample.index[0].date()),
        "end": str(sample.index[-1].date()),
        "cumulative_return": result.cumulative_return,
        "benchmark_return": result.benchmark_return,
        "excess_return": result.excess_return,
        "mdd": result.mdd,
        "sharpe": result.sharpe_ratio,
        "total_trades": result.n_trades,
        "win_rate": result.win_rate,
        "avg_hold_days": result.avg_hold_days,
        "expectancy": result.expectancy,
        "exit_mix": _exit_stats(result),
    }


def sweep(candles: dict[str, pd.DataFrame]) -> list[dict]:
    rows: list[dict] = []
    for dip in DIP_THRESHOLDS:
        for rsi in RSI_THRESHOLDS:
            for hold in MAX_HOLDS:
                for mult in ATR_MULTS:
                    params = {
                        "regime_ticker": "KRW-BTC",
                        "regime_ma_window": 120,
                        "dip_lookback_days": 5,
                        "dip_threshold_pct": dip,
                        "rsi_window": 14,
                        "rsi_threshold": rsi,
                        "max_hold_days": hold,
                        "atr_window": 14,
                        "atr_trailing_mult": mult,
                    }
                    by_ticker = {ticker: run_one(candles, ticker, params) for ticker in TICKERS}

                    btc = by_ticker["KRW-BTC"]
                    eth = by_ticker["KRW-ETH"]
                    total_trades = btc["total_trades"] + eth["total_trades"]
                    time_count = sum(
                        stats["trade_count"]
                        for result in by_ticker.values()
                        for reason, stats in result["exit_mix"].items()
                        if reason == "rcdb_time_exit"
                    )
                    trailing_count = sum(
                        stats["trade_count"]
                        for result in by_ticker.values()
                        for reason, stats in result["exit_mix"].items()
                        if reason == "rcdb_trailing_exit"
                    )
                    regime_count = sum(
                        stats["trade_count"]
                        for result in by_ticker.values()
                        for reason, stats in result["exit_mix"].items()
                        if reason == "rcdb_regime_off"
                    )
                    rows.append(
                        {
                            "params": params,
                            "btc": btc,
                            "eth": eth,
                            "avg_excess_return": (btc["excess_return"] + eth["excess_return"]) / 2.0,
                            "min_trades": min(btc["total_trades"], eth["total_trades"]),
                            "total_trades": total_trades,
                            "time_exit_share": time_count / total_trades if total_trades else 0.0,
                            "trailing_exit_share": trailing_count / total_trades if total_trades else 0.0,
                            "regime_exit_share": regime_count / total_trades if total_trades else 0.0,
                        }
                    )
    return rows


def _sort_key_for_balance(row: dict) -> tuple:
    return (
        row["min_trades"] >= 5,
        row["btc"]["excess_return"],
        row["avg_excess_return"],
        -abs(row["time_exit_share"] - 0.5),
    )


def shortlist(rows: list[dict], candles: dict[str, pd.DataFrame]) -> dict:
    rows_by_balance = sorted(rows, key=_sort_key_for_balance, reverse=True)
    rows_by_btc = sorted(
        rows,
        key=lambda r: (r["btc"]["excess_return"], r["btc"]["total_trades"], r["avg_excess_return"]),
        reverse=True,
    )
    rows_by_diversified_exit = sorted(
        rows,
        key=lambda r: (
            r["min_trades"] >= 5,
            r["trailing_exit_share"] + r["regime_exit_share"],
            -r["time_exit_share"],
            r["btc"]["excess_return"],
        ),
        reverse=True,
    )

    chosen_pool = [
        row for row in rows
        if row["min_trades"] >= 5 and row["btc"]["excess_return"] > -0.10
    ]
    if not chosen_pool:
        chosen_pool = rows_by_balance
    chosen_pool = sorted(
        chosen_pool,
        key=lambda r: (
            r["trailing_exit_share"] + r["regime_exit_share"],
            -r["time_exit_share"],
            r["btc"]["excess_return"],
            r["avg_excess_return"],
        ),
        reverse=True,
    )
    chosen = chosen_pool[0]
    chosen_optional = run_one(candles, OPTIONAL_TICKER, chosen["params"])

    thesis_guard_pool = [
        row for row in rows
        if row["params"]["dip_threshold_pct"] <= -0.05
        and row["params"]["rsi_threshold"] <= 40.0
        and row["min_trades"] >= 2
    ]
    thesis_guard_pool = sorted(
        thesis_guard_pool,
        key=lambda r: (
            r["btc"]["excess_return"],
            r["avg_excess_return"],
            r["min_trades"],
        ),
        reverse=True,
    )
    thesis_guard = thesis_guard_pool[0] if thesis_guard_pool else None

    ref_params = {
        "regime_ticker": "KRW-BTC",
        "regime_ma_window": 120,
        "dip_lookback_days": 5,
        "dip_threshold_pct": -0.04,
        "rsi_window": 14,
        "rsi_threshold": 45.0,
        "max_hold_days": 7,
        "atr_window": 14,
        "atr_trailing_mult": 3.0,
    }
    reference_compare = {
        "params": ref_params,
        "v1_close_anchor": {
            ticker: run_one(candles, ticker, ref_params, strategy_cls=RcdbV10Reference)
            for ticker in TICKERS
        },
        "v1_1_high_anchor": {
            ticker: run_one(candles, ticker, ref_params, strategy_cls=RcdbStrategy)
            for ticker in TICKERS
        },
    }

    return {
        "chosen_candidate": {
            **chosen,
            "xrp_optional": chosen_optional,
        },
        "thesis_guard_candidate": thesis_guard,
        "top_by_balance": rows_by_balance[:10],
        "top_by_btc_excess": rows_by_btc[:10],
        "top_by_exit_diversification": rows_by_diversified_exit[:10],
        "reference_comparison": reference_compare,
    }


def main() -> int:
    candles = fetch_candles()
    rows = sweep(candles)
    report = {
        "as_of": AS_OF,
        "fee": UPBIT_DEFAULT_FEE,
        "slippage": DEFAULT_SLIPPAGE,
        "strategy": "rcdb_v1_2",
        "design_change": "ATR trailing anchor changed from highest_close to highest_high",
        "sweep_axes": {
            "dip_threshold_pct": DIP_THRESHOLDS,
            "rsi_threshold": RSI_THRESHOLDS,
            "max_hold_days": MAX_HOLDS,
            "atr_trailing_mult": ATR_MULTS,
        },
        "rows": rows,
        "shortlist": shortlist(rows, candles),
    }

    out_path = Path("reports/2026-04-22-rcdb-v12-stage2.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

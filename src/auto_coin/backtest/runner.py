"""변동성 돌파 전략 백테스트.

가정 (단순화):
    - 일봉 단위. 09:00 KST에 일봉이 갱신된다.
    - 진입: 당일 high가 target에 닿으면 target 가격에 매수 (낙관적 표준 가정).
    - 청산: 다음날 시가에 매도.
    - 수수료는 매수·매도 양쪽에 동일 적용. 슬리피지는 진입가에 +, 청산가에 -.
    - 손절·일일 손실 한도는 제외 (M5 RiskManager에서 다룸).
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import pyupbit

from auto_coin.data.candles import enrich_daily
from auto_coin.strategy.volatility_breakout import VolatilityBreakout

UPBIT_DEFAULT_FEE = 0.0005  # 0.05% (KRW 마켓 일반 수수료)


@dataclass(frozen=True)
class Trade:
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    ret: float  # 수수료·슬리피지 반영 후 수익률


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    cumulative_return: float = 0.0  # (1+r1)*(1+r2)*... - 1
    mdd: float = 0.0  # 최대 낙폭 (음수)
    win_rate: float = 0.0
    n_trades: int = 0
    n_wins: int = 0

    def summary(self) -> str:
        return (
            f"trades={self.n_trades:4d}  "
            f"cum={self.cumulative_return*100:+7.2f}%  "
            f"mdd={self.mdd*100:+6.2f}%  "
            f"win={self.win_rate*100:5.1f}%"
        )


def backtest(
    df: pd.DataFrame,
    strategy: VolatilityBreakout,
    *,
    fee: float = UPBIT_DEFAULT_FEE,
    slippage: float = 0.0,
) -> BacktestResult:
    """변동성 돌파 백테스트.

    `df`는 `enrich_daily`로 `target`/`maN` 컬럼이 채워져 있어야 한다.
    매 row를 "오늘"로 가정하고 진입 여부를 판정, 다음 row의 시가에 청산한다.
    """
    if df.empty:
        return BacktestResult()

    ma_col = f"ma{strategy.ma_window}"
    if "target" not in df.columns:
        raise ValueError("df must be enriched (call enrich_daily first)")
    if strategy.require_ma_filter and ma_col not in df.columns:
        raise ValueError(f"df missing {ma_col} but strategy requires MA filter")

    trades: list[Trade] = []

    # 마지막 row는 다음날이 없어 청산 불가 → 제외
    for i in range(len(df) - 1):
        row = df.iloc[i]
        target = row["target"]
        high = row["high"]
        if not _is_finite(target) or not _is_finite(high):
            continue
        if high < target:
            continue  # 돌파 실패

        if strategy.require_ma_filter:
            ma = row.get(ma_col)
            if not _is_finite(ma):
                continue
            if target <= float(ma):
                continue

        entry_price = float(target) * (1.0 + slippage)
        next_row = df.iloc[i + 1]
        exit_price = float(next_row["open"]) * (1.0 - slippage)
        # 수수료: 매수 시 entry * (1+fee) 만큼 KRW 차감, 매도 시 exit * (1-fee) 수령
        # 수익률 = (exit*(1-fee)) / (entry*(1+fee)) - 1
        ret = (exit_price * (1.0 - fee)) / (entry_price * (1.0 + fee)) - 1.0

        trades.append(
            Trade(
                entry_date=df.index[i].to_pydatetime() if hasattr(df.index[i], "to_pydatetime") else df.index[i],
                entry_price=entry_price,
                exit_date=df.index[i + 1].to_pydatetime() if hasattr(df.index[i + 1], "to_pydatetime") else df.index[i + 1],
                exit_price=exit_price,
                ret=ret,
            )
        )

    return _build_result(trades)


def _build_result(trades: list[Trade]) -> BacktestResult:
    if not trades:
        return BacktestResult()

    rets = np.array([t.ret for t in trades])
    equity = np.cumprod(1.0 + rets)
    cum_return = float(equity[-1] - 1.0)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    mdd = float(drawdown.min())
    n_wins = int((rets > 0).sum())
    win_rate = n_wins / len(trades)

    return BacktestResult(
        trades=trades,
        cumulative_return=cum_return,
        mdd=mdd,
        win_rate=win_rate,
        n_trades=len(trades),
        n_wins=n_wins,
    )


def _is_finite(x: float | None) -> bool:
    if x is None:
        return False
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return not math.isnan(f) and not math.isinf(f)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _fetch_candles(ticker: str, days: int) -> pd.DataFrame:
    df = pyupbit.get_ohlcv(ticker, interval="day", count=days)
    if df is None or df.empty:
        raise SystemExit(f"failed to fetch candles for {ticker}")
    return df


def _run_one(df: pd.DataFrame, k: float, ma_window: int, fee: float, slippage: float,
             require_ma: bool) -> BacktestResult:
    enriched = enrich_daily(df, ma_window=ma_window, k=k)
    strat = VolatilityBreakout(k=k, ma_window=ma_window, require_ma_filter=require_ma)
    return backtest(enriched, strat, fee=fee, slippage=slippage)


def _frange(start: float, stop: float, step: float) -> list[float]:
    n = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 6) for i in range(n) if start + i * step <= stop + 1e-9]


def cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auto-coin-backtest",
                                description="Volatility breakout backtest on Upbit daily candles.")
    p.add_argument("--ticker", default="KRW-BTC")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--k", type=float, default=0.5)
    p.add_argument("--ma-window", type=int, default=5)
    p.add_argument("--fee", type=float, default=UPBIT_DEFAULT_FEE)
    p.add_argument("--slippage", type=float, default=0.0)
    p.add_argument("--no-ma-filter", action="store_true")
    p.add_argument("--sweep", nargs=3, type=float, metavar=("START", "STOP", "STEP"),
                   help="K 값 스윕: --sweep 0.3 0.7 0.05")
    args = p.parse_args(argv)

    raw = _fetch_candles(args.ticker, args.days)
    print(f"# {args.ticker}  candles={len(raw)}  fee={args.fee}  slippage={args.slippage}  "
          f"ma_filter={not args.no_ma_filter}")

    if args.sweep:
        ks = _frange(args.sweep[0], args.sweep[1], args.sweep[2])
        print(f"# K sweep: {ks}")
        print(f"{'k':>6}  result")
        for k in ks:
            r = _run_one(raw, k, args.ma_window, args.fee, args.slippage, not args.no_ma_filter)
            print(f"{k:>6.3f}  {r.summary()}")
    else:
        r = _run_one(raw, args.k, args.ma_window, args.fee, args.slippage, not args.no_ma_filter)
        print(r.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

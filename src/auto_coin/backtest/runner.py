"""범용 전략 백테스트.

지원 모드:
    1. **Legacy VB** (`backtest_vb`): 변동성 돌파 전용. high ≥ target 판정 → 다음날 시가 청산.
    2. **Generic** (`backtest`): 임의의 `Strategy` 객체를 받아 시그널 기반으로 진입/청산.
       stop-loss, time-exit 옵션 제공.

공통 가정 (단순화):
    - 일봉 단위. 09:00 KST에 일봉이 갱신된다.
    - 수수료는 매수·매도 양쪽에 동일 적용. 슬리피지는 진입가에 +, 청산가에 -.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import pyupbit

from auto_coin.data.candles import enrich_daily, enrich_for_strategy
from auto_coin.strategy import STRATEGY_REGISTRY, create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy
from auto_coin.strategy.volatility_breakout import VolatilityBreakout

UPBIT_DEFAULT_FEE = 0.0005  # 0.05% (KRW 마켓 일반 수수료)
DEFAULT_SLIPPAGE = 0.0005   # 0.05% — CLI 기본값 (보수적)


@dataclass(frozen=True)
class Trade:
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    ret: float  # 수수료·슬리피지 반영 후 수익률
    exit_type: str = "signal"  # "signal", "stop_loss", "time_exit"


@dataclass(frozen=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    cumulative_return: float = 0.0  # (1+r1)*(1+r2)*... - 1
    mdd: float = 0.0  # 최대 낙폭 (음수)
    win_rate: float = 0.0
    n_trades: int = 0
    n_wins: int = 0
    # P1: risk metrics
    sharpe_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_hold_days: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    annualized_return: float = 0.0
    total_days: int = 0
    # P1: benchmark
    benchmark_return: float = 0.0
    excess_return: float = 0.0

    def summary(self) -> str:
        return (
            f"trades={self.n_trades:4d}  "
            f"cum={self.cumulative_return*100:+7.2f}%  "
            f"mdd={self.mdd*100:+6.2f}%  "
            f"win={self.win_rate*100:5.1f}%"
        )

    def report(self) -> str:
        """시장 대비 전략 성과를 한눈에 보여주는 상세 보고."""
        sep = "═" * 59
        thin = "─" * 59
        lines = [
            sep,
            "  BACKTEST REPORT",
            sep,
            f"  Strategy Return    :  {self.cumulative_return * 100:+.2f}%",
            f"  Buy & Hold Return  :  {self.benchmark_return * 100:+.2f}%",
            f"  Excess Return      :  {self.excess_return * 100:+.2f}%",
            thin,
            f"  Sharpe Ratio       :  {self.sharpe_ratio:6.2f}",
            f"  Calmar Ratio       :  {self.calmar_ratio:6.2f}",
            f"  Profit Factor      :  {self.profit_factor:6.2f}",
            f"  MDD                :  {self.mdd * 100:+.2f}%",
            f"  Annualized Return  :  {self.annualized_return * 100:+.2f}%",
            thin,
            f"  Total Trades       :  {self.n_trades:5d}",
            f"  Win Rate           :  {self.win_rate * 100:5.1f}%  ({self.n_wins}/{self.n_trades})",
            f"  Avg Hold Days      :  {self.avg_hold_days:6.1f}",
            f"  Avg Win            :  {self.avg_win * 100:+.2f}%",
            f"  Avg Loss           :  {self.avg_loss * 100:+.2f}%",
            f"  Expectancy         :  {self.expectancy * 100:+.2f}%",
            sep,
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _is_finite(x: float | None) -> bool:
    if x is None:
        return False
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    return not math.isnan(f) and not math.isinf(f)


def _to_dt(idx_val) -> datetime:
    """pandas Timestamp → datetime 변환."""
    return idx_val.to_pydatetime() if hasattr(idx_val, "to_pydatetime") else idx_val


def _build_result(
    trades: list[Trade],
    *,
    total_days: int = 0,
    benchmark_return: float = 0.0,
) -> BacktestResult:
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

    # --- P1: risk metrics ---

    # Annualized return
    annualized = (1.0 + cum_return) ** (365.0 / total_days) - 1.0 if total_days > 0 else 0.0

    # Sharpe ratio (per-trade, annualized)
    if len(trades) >= 2 and total_days > 0:
        trades_per_year = len(trades) * 365.0 / total_days
        sharpe = float(np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(trades_per_year))
        if not math.isfinite(sharpe):
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Calmar ratio
    calmar = annualized / abs(mdd) if abs(mdd) > 1e-10 else 0.0
    if not math.isfinite(calmar):
        calmar = 0.0

    # Profit factor
    gross_wins = float(rets[rets > 0].sum()) if (rets > 0).any() else 0.0
    gross_losses = float(abs(rets[rets < 0].sum())) if (rets < 0).any() else 0.0
    pf = gross_wins / gross_losses if gross_losses > 1e-10 else 99.99 if gross_wins > 0 else 0.0

    # Average hold days
    hold_days_list = [(t.exit_date - t.entry_date).days for t in trades]
    avg_hold = float(np.mean(hold_days_list)) if hold_days_list else 0.0

    # Avg win / avg loss
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    avg_win_val = float(np.mean(wins)) if len(wins) > 0 else 0.0
    avg_loss_val = float(np.mean(losses)) if len(losses) > 0 else 0.0

    # Expectancy
    expectancy = win_rate * avg_win_val - (1.0 - win_rate) * abs(avg_loss_val)

    # Excess return
    excess = cum_return - benchmark_return

    return BacktestResult(
        trades=trades,
        cumulative_return=cum_return,
        mdd=mdd,
        win_rate=win_rate,
        n_trades=len(trades),
        n_wins=n_wins,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        profit_factor=pf,
        expectancy=expectancy,
        avg_hold_days=avg_hold,
        avg_win=avg_win_val,
        avg_loss=avg_loss_val,
        annualized_return=annualized,
        total_days=total_days,
        benchmark_return=benchmark_return,
        excess_return=excess,
    )


# ---------------------------------------------------------------------------
# Legacy: 변동성 돌파 전용 백테스트
# ---------------------------------------------------------------------------


def backtest_vb(
    df: pd.DataFrame,
    strategy: VolatilityBreakout,
    *,
    fee: float = UPBIT_DEFAULT_FEE,
    slippage: float = 0.0,
) -> BacktestResult:
    """변동성 돌파 백테스트 (레거시).

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
                entry_date=_to_dt(df.index[i]),
                entry_price=entry_price,
                exit_date=_to_dt(df.index[i + 1]),
                exit_price=exit_price,
                ret=ret,
            )
        )

    return _build_result(trades)


# ---------------------------------------------------------------------------
# Generic: 범용 시그널 기반 백테스트
# ---------------------------------------------------------------------------


@dataclass
class _SimState:
    """시뮬레이션 내부 상태."""
    has_position: bool = False
    entry_price: float | None = None
    entry_day: int = 0
    hold_days: int = 0


def backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    *,
    fee: float = UPBIT_DEFAULT_FEE,
    slippage: float = 0.0,
    stop_loss_ratio: float | None = None,
    enable_time_exit: bool = False,
    mark_to_market: bool = True,
) -> BacktestResult:
    """범용 시그널 기반 백테스트.

    `df`는 `enrich_for_strategy`로 전략에 필요한 보조 컬럼이 채워져 있어야 한다.
    매 row의 close를 현재가로 사용하여 전략 시그널을 생성한다.

    Args:
        df: 보조 컬럼이 채워진 일봉 DataFrame.
        strategy: generate_signal(snap) → Signal 을 구현한 전략 객체.
        fee: 매수·매도 수수료율 (양쪽 동일).
        slippage: 슬리피지 비율.
        stop_loss_ratio: 손절 비율 (예: -0.02). None이면 비활성.
        enable_time_exit: True면 보유 1일 후 다음날 시가에 청산.
    """
    if df.empty:
        return BacktestResult()

    trades: list[Trade] = []
    state = _SimState()

    for i in range(len(df)):
        row = df.iloc[i]
        close = float(row["close"]) if _is_finite(row.get("close")) else None
        open_ = float(row["open"]) if _is_finite(row.get("open")) else None
        low = float(row["low"]) if _is_finite(row.get("low")) else None

        if close is None:
            continue

        # --- Phase 1: Time-exit at open ---
        if (
            state.has_position
            and enable_time_exit
            and state.hold_days >= 1
            and open_ is not None
        ):
            exit_price = open_ * (1.0 - slippage)
            assert state.entry_price is not None
            ret = (exit_price * (1.0 - fee)) / (state.entry_price * (1.0 + fee)) - 1.0
            trades.append(
                Trade(
                    entry_date=_to_dt(df.index[state.entry_day]),
                    entry_price=state.entry_price,
                    exit_date=_to_dt(df.index[i]),
                    exit_price=exit_price,
                    ret=ret,
                    exit_type="time_exit",
                )
            )
            state = _SimState()
            # time-exit 후 같은 날 close에서 재진입 가능 → continue 안 함

        # --- Phase 2: Stop-loss check (day's low) ---
        if state.has_position and stop_loss_ratio is not None:
            assert state.entry_price is not None
            stop_price = state.entry_price * (1.0 + stop_loss_ratio)
            check_low = low if low is not None else close
            if check_low <= stop_price:
                exit_price = stop_price * (1.0 - slippage)
                ret = (exit_price * (1.0 - fee)) / (state.entry_price * (1.0 + fee)) - 1.0
                trades.append(
                    Trade(
                        entry_date=_to_dt(df.index[state.entry_day]),
                        entry_price=state.entry_price,
                        exit_date=_to_dt(df.index[i]),
                        exit_price=exit_price,
                        ret=ret,
                        exit_type="stop_loss",
                    )
                )
                state = _SimState()
                continue  # 손절 후 같은 날 재진입 금지

        # --- Phase 3: Signal generation ---
        snap = MarketSnapshot(
            df=df.iloc[: i + 1],
            current_price=close,
            has_position=state.has_position,
        )
        signal = strategy.generate_signal(snap)

        # --- Phase 4: Strategy SELL ---
        if state.has_position and signal == Signal.SELL:
            assert state.entry_price is not None
            exit_price = close * (1.0 - slippage)
            ret = (exit_price * (1.0 - fee)) / (state.entry_price * (1.0 + fee)) - 1.0
            trades.append(
                Trade(
                    entry_date=_to_dt(df.index[state.entry_day]),
                    entry_price=state.entry_price,
                    exit_date=_to_dt(df.index[i]),
                    exit_price=exit_price,
                    ret=ret,
                    exit_type="signal",
                )
            )
            state = _SimState()
            continue

        # --- Phase 5: BUY ---
        if not state.has_position and signal == Signal.BUY:
            state = _SimState(
                has_position=True,
                entry_price=close * (1.0 + slippage),
                entry_day=i,
                hold_days=0,
            )

        # --- Phase 6: Hold increment ---
        if state.has_position:
            state.hold_days += 1

    # Mark-to-market: close open position at last close
    if mark_to_market and state.has_position and state.entry_price is not None:
        last_close = float(df.iloc[-1]["close"]) if _is_finite(df.iloc[-1].get("close")) else None
        if last_close is not None:
            exit_price = last_close * (1.0 - slippage)
            ret = (exit_price * (1.0 - fee)) / (state.entry_price * (1.0 + fee)) - 1.0
            trades.append(Trade(
                entry_date=_to_dt(df.index[state.entry_day]),
                entry_price=state.entry_price,
                exit_date=_to_dt(df.index[-1]),
                exit_price=exit_price,
                ret=ret,
                exit_type="end_of_data",
            ))

    # Benchmark: buy-and-hold
    first_close = None
    last_close_val = None
    for j in range(len(df)):
        c = df.iloc[j].get("close")
        if _is_finite(c):
            if first_close is None:
                first_close = float(c)
            last_close_val = float(c)

    benchmark = (last_close_val / first_close - 1.0) if (first_close and last_close_val and first_close > 0) else 0.0
    total_days = (df.index[-1] - df.index[0]).days if len(df) > 1 else 0

    return _build_result(trades, total_days=total_days, benchmark_return=benchmark)


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
    return backtest_vb(enriched, strat, fee=fee, slippage=slippage)


def _run_generic(
    df: pd.DataFrame,
    strategy_name: str,
    params: dict,
    fee: float,
    slippage: float,
    stop_loss: float | None,
    enable_time_exit: bool,
) -> BacktestResult:
    """범용 전략 백테스트 실행."""
    enriched = enrich_for_strategy(
        df, strategy_name, params,
        k=params.get("k", 0.5),
        ma_window=params.get("ma_window", 5),
    )
    strategy = create_strategy(strategy_name, params)
    return backtest(
        enriched,
        strategy,
        fee=fee,
        slippage=slippage,
        stop_loss_ratio=stop_loss,
        enable_time_exit=enable_time_exit,
    )


def _frange(start: float, stop: float, step: float) -> list[float]:
    n = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 6) for i in range(n) if start + i * step <= stop + 1e-9]


def cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="auto-coin-backtest",
                                description="Strategy backtest on Upbit daily candles.")
    p.add_argument("--ticker", default="KRW-BTC")
    p.add_argument("--days", type=int, default=365)
    p.add_argument("--k", type=float, default=0.5)
    p.add_argument("--ma-window", type=int, default=5)
    p.add_argument("--fee", type=float, default=UPBIT_DEFAULT_FEE)
    p.add_argument("--slippage", type=float, default=None)
    p.add_argument("--no-ma-filter", action="store_true")
    p.add_argument("--sweep", nargs=3, type=float, metavar=("START", "STOP", "STEP"),
                   help="K 값 스윕: --sweep 0.3 0.7 0.05")
    # 범용 전략 옵션
    p.add_argument("--strategy", default=None, choices=list(STRATEGY_REGISTRY.keys()),
                   help="전략 이름. 미지정 시 레거시 VB 모드.")
    p.add_argument("--params", default="{}", type=str,
                   help="JSON string for strategy params")
    p.add_argument("--stop-loss", default=None, type=float,
                   help="Stop-loss ratio e.g. -0.02")
    p.add_argument("--enable-time-exit", action="store_true",
                   help="보유 1일 후 다음날 시가 청산")
    p.add_argument("--enable-sell", action="store_true",
                   help="전략의 SELL 시그널 활성화 (지원 전략만)")
    args = p.parse_args(argv)

    raw = _fetch_candles(args.ticker, args.days)

    # --- 범용 전략 모드 ---
    if args.strategy is not None:
        if args.sweep:
            print("ERROR: --sweep is only supported in legacy VB mode (without --strategy).",
                  file=__import__("sys").stderr)
            return 1

        params: dict = json.loads(args.params)
        slippage = args.slippage if args.slippage is not None else DEFAULT_SLIPPAGE

        # --enable-sell → allow_sell_signal 주입 (전략이 지원하는 경우에만)
        if args.enable_sell:
            cls = STRATEGY_REGISTRY[args.strategy]
            cls_fields = {f.name for f in dataclasses.fields(cls)}
            if "allow_sell_signal" in cls_fields:
                params.setdefault("allow_sell_signal", True)

        print(
            f"# {args.ticker}  strategy={args.strategy}  candles={len(raw)}  "
            f"fee={args.fee}  slippage={slippage}  stop_loss={args.stop_loss}"
        )
        r = _run_generic(
            raw, args.strategy, params, args.fee, slippage,
            args.stop_loss, args.enable_time_exit,
        )
        print(r.report())
        return 0

    # --- 레거시 VB 모드 ---
    slippage = args.slippage if args.slippage is not None else 0.0
    print(f"# {args.ticker}  candles={len(raw)}  fee={args.fee}  slippage={slippage}  "
          f"ma_filter={not args.no_ma_filter}")

    if args.sweep:
        ks = _frange(args.sweep[0], args.sweep[1], args.sweep[2])
        print(f"# K sweep: {ks}")
        print(f"{'k':>6}  result")
        for k in ks:
            r = _run_one(raw, k, args.ma_window, args.fee, slippage, not args.no_ma_filter)
            print(f"{k:>6.3f}  {r.summary()}")
    else:
        r = _run_one(raw, args.k, args.ma_window, args.fee, slippage, not args.no_ma_filter)
        print(r.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

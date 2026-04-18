"""Portfolio-aware backtest engine.

CSMOM / RCDB 등 멀티자산 · cross-sectional 전략 검증을 위한 엔진.
단일 ticker `backtest()` (per-ticker Strategy) 와 독립적으로 universe 전체를
동시에 시뮬레이션한다.

설계 포인트:

- **Strategy-agnostic**: `PortfolioSignal` 은 (ticker → target weight) dict 를 반환하는
  Callable. 랭킹/레짐/평균회귀 어느 전략이든 이 인터페이스를 구현하면 된다.
- **Rebalance-driven**: `rebal_days` 간격의 tick 에서만 signal 을 호출해 체결.
  중간 날짜는 mark-to-market 으로 equity curve 만 갱신.
- **Benchmark**: universe 동등비중 buy-and-hold. 시작일 초기 할당 후 daily
  마크투마켓. portfolio vs universe B&H 로 "상대 edge" 를 직접 측정.
- **Fee / slippage**: 매수·매도 양쪽 대칭 적용.

본 모듈은 CSMOM 본 로직을 포함하지 않는다. 참조 구현으로 `equal_weight_signal`
(universe 전원 동등 보유) 만 제공 — 테스트와 인프라 검증용.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

UPBIT_DEFAULT_FEE = 0.0005
DEFAULT_SLIPPAGE = 0.0005


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioContext:
    """Signal 과 엔진이 공유하는 실행 컨텍스트.

    후속 전략(CSMOM · RCDB · XS-LOWVOL · 1H-MR 등)이 이 구조로 파라미터를 받는다.
    Sizing / rebalance / lookback 등 공통 knob 을 한 곳에 모았다.
    """

    # sizing
    risk_budget: float = 0.8              # 포트폴리오 총자본 중 위험자산 투입 비율 (상한)
    risk_budget_krw: float | None = None  # 고정 KRW 로 override 할 때만 사용
    atr_window_for_sizing: int = 20       # vol-scaled sizing 용 ATR 기간

    # rebalance cadence
    rebal_days: int = 7                   # 리밸런싱 주기 (일)
    hold_N: int = 3                       # 동시 보유 상한 힌트 (signal 이 준수할 책임)
    lookback_days: int = 60               # 시그널 룩백

    # strategy group tag (DailySnapshot.active_strategy_group 에 들어감)
    active_strategy_group: str = "unknown"


# ---------------------------------------------------------------------------
# Signal protocol (Callable)
# ---------------------------------------------------------------------------


PortfolioSignal = Callable[
    [dict[str, pd.DataFrame], pd.Timestamp, PortfolioContext],
    dict[str, float],
]
"""시그널 함수 시그니처.

Args:
    candles: universe 전체의 DataFrame dict. 각 df 는 현재 시점까지 슬라이스된 상태.
    current_date: 현재 시점 (last index).
    context: PortfolioContext.

Returns:
    dict[ticker, weight]. 가중치 합은 ≤ risk_budget.
    dict 에 없는 ticker 는 target weight 0 (보유 중이면 청산 대상).
"""


def equal_weight_signal(
    candles: dict[str, pd.DataFrame],
    current_date: pd.Timestamp,
    ctx: PortfolioContext,
) -> dict[str, float]:
    """참조 구현 — universe 내 사용 가능한 모든 ticker 를 동등 가중."""
    available = [t for t, df in candles.items() if len(df) > 0]
    if not available:
        return {}
    w = ctx.risk_budget / len(available)
    return {t: w for t in available}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioTrade:
    """단일 ticker 의 rebalance 유발 체결 1건."""

    ticker: str
    date: pd.Timestamp
    side: str                       # "buy" | "sell"
    price: float                    # 슬리피지 반영된 체결가
    shares: float                   # 양수
    krw_amount: float               # 체결 KRW (fee 전)
    fee_krw: float
    reason: str = "rebalance"       # "rebalance" | "regime_off" | "drop_from_topN" 등


@dataclass(frozen=True)
class RebalanceEvent:
    """매 rebalance tick 기록."""

    date: pd.Timestamp
    target_weights: dict[str, float]
    realized_weights: dict[str, float]
    portfolio_value_before: float
    portfolio_value_after: float
    trades: list[PortfolioTrade]


@dataclass(frozen=True)
class PortfolioBacktestResult:
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    benchmark_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    trades: list[PortfolioTrade] = field(default_factory=list)
    rebalance_events: list[RebalanceEvent] = field(default_factory=list)

    initial_krw: float = 0.0
    final_equity_krw: float = 0.0
    cumulative_return: float = 0.0
    benchmark_return: float = 0.0
    excess_return: float = 0.0
    mdd: float = 0.0
    sharpe_ratio: float = 0.0
    n_trades: int = 0
    n_rebalances: int = 0

    def summary(self) -> str:
        return (
            f"portfolio  cum={self.cumulative_return*100:+7.2f}%  "
            f"bnh={self.benchmark_return*100:+7.2f}%  "
            f"excess={self.excess_return*100:+7.2f}%  "
            f"mdd={self.mdd*100:+6.2f}%  "
            f"sharpe={self.sharpe_ratio:5.2f}  "
            f"trades={self.n_trades:4d}  rebals={self.n_rebalances:3d}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _align_universe(candles: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """모든 ticker 의 날짜 index 교집합. 초기 스켈레톤은 공통 구간만 사용."""
    if not candles:
        return pd.DatetimeIndex([])
    idx: pd.DatetimeIndex | None = None
    for df in candles.values():
        if df.empty:
            continue
        this_idx = df.index
        idx = this_idx if idx is None else idx.intersection(this_idx)
    return pd.DatetimeIndex([]) if idx is None else idx.sort_values()


def _close_at(
    candles: dict[str, pd.DataFrame], ticker: str, date: pd.Timestamp,
) -> float | None:
    df = candles.get(ticker)
    if df is None or date not in df.index:
        return None
    close = df.loc[date].get("close")
    if close is None or (isinstance(close, float) and (math.isnan(close) or math.isinf(close))):
        return None
    return float(close)


def _mark_to_market(
    candles: dict[str, pd.DataFrame],
    positions: dict[str, float],
    date: pd.Timestamp,
    cash: float,
) -> float:
    total = cash
    for ticker, shares in positions.items():
        p = _close_at(candles, ticker, date)
        if p is not None:
            total += shares * p
    return total


def _apply_rebalance(
    candles: dict[str, pd.DataFrame],
    date: pd.Timestamp,
    positions: dict[str, float],
    cash: float,
    target_weights: dict[str, float],
    portfolio_value: float,
    *,
    fee: float,
    slippage: float,
) -> tuple[list[PortfolioTrade], float, dict[str, float]]:
    """Rebalance 체결. 매도 먼저 → 매수. 반환: (trades, new_cash, new_positions)."""
    new_positions = dict(positions)
    new_cash = cash
    trades: list[PortfolioTrade] = []

    involved = set(new_positions.keys()) | set(target_weights.keys())

    # --- Sells first ---
    for ticker in sorted(involved):
        close = _close_at(candles, ticker, date)
        if close is None or close <= 0:
            continue
        current_shares = new_positions.get(ticker, 0.0)
        current_krw = current_shares * close
        target_krw = portfolio_value * target_weights.get(ticker, 0.0)
        if current_krw - target_krw > 1e-6 and current_shares > 0:
            sell_shares = min(current_shares, (current_krw - target_krw) / close)
            if sell_shares <= 0:
                continue
            exec_price = close * (1.0 - slippage)
            gross = sell_shares * exec_price
            f = gross * fee
            new_cash += gross - f
            new_shares = current_shares - sell_shares
            if new_shares < 1e-12:
                new_positions.pop(ticker, None)
            else:
                new_positions[ticker] = new_shares
            trades.append(PortfolioTrade(
                ticker=ticker, date=date, side="sell",
                price=exec_price, shares=sell_shares,
                krw_amount=gross, fee_krw=f,
            ))

    # --- Buys second ---
    for ticker in sorted(involved):
        close = _close_at(candles, ticker, date)
        if close is None or close <= 0:
            continue
        current_shares = new_positions.get(ticker, 0.0)
        current_krw = current_shares * close
        target_krw = portfolio_value * target_weights.get(ticker, 0.0)
        if target_krw - current_krw > 1e-6:
            want_krw = target_krw - current_krw
            spend = min(want_krw, max(0.0, new_cash))
            if spend <= 0:
                continue
            exec_price = close * (1.0 + slippage)
            effective_price = exec_price * (1.0 + fee)
            shares = spend / effective_price
            if shares <= 0:
                continue
            f = shares * exec_price * fee
            new_cash -= shares * exec_price + f
            new_positions[ticker] = current_shares + shares
            trades.append(PortfolioTrade(
                ticker=ticker, date=date, side="buy",
                price=exec_price, shares=shares,
                krw_amount=shares * exec_price, fee_krw=f,
            ))

    return trades, new_cash, new_positions


def _finalize_result(
    equity_points: list[tuple[pd.Timestamp, float]],
    bench_points: list[tuple[pd.Timestamp, float]],
    trades: list[PortfolioTrade],
    rebal_events: list[RebalanceEvent],
    *,
    initial_krw: float,
) -> PortfolioBacktestResult:
    if not equity_points:
        return PortfolioBacktestResult(initial_krw=initial_krw)

    eq_idx = pd.DatetimeIndex([p[0] for p in equity_points])
    eq_vals = np.array([p[1] for p in equity_points], dtype=float)
    equity = pd.Series(eq_vals, index=eq_idx, name="equity")

    if bench_points:
        bench_idx = pd.DatetimeIndex([p[0] for p in bench_points])
        bench_vals = np.array([p[1] for p in bench_points], dtype=float)
        benchmark = pd.Series(bench_vals, index=bench_idx, name="benchmark")
    else:
        bench_vals = np.array([])
        benchmark = pd.Series(dtype=float, name="benchmark")

    final_equity = float(eq_vals[-1])
    cum_ret = final_equity / initial_krw - 1.0 if initial_krw > 0 else 0.0
    bench_ret = (
        float(bench_vals[-1] / initial_krw - 1.0)
        if len(bench_vals) and initial_krw > 0 else 0.0
    )
    excess = cum_ret - bench_ret

    # MDD
    peak = np.maximum.accumulate(eq_vals)
    dd = (eq_vals - peak) / np.where(peak > 0, peak, 1.0)
    mdd = float(dd.min()) if len(dd) else 0.0

    # Sharpe (daily)
    if len(eq_vals) >= 2:
        daily_ret = np.diff(eq_vals) / np.where(eq_vals[:-1] != 0, eq_vals[:-1], 1.0)
        std = float(np.std(daily_ret, ddof=1))
        sharpe = float(np.mean(daily_ret) / std * math.sqrt(365)) if std > 1e-12 else 0.0
        if not math.isfinite(sharpe):
            sharpe = 0.0
    else:
        sharpe = 0.0

    return PortfolioBacktestResult(
        equity_curve=equity,
        benchmark_curve=benchmark,
        trades=trades,
        rebalance_events=rebal_events,
        initial_krw=initial_krw,
        final_equity_krw=final_equity,
        cumulative_return=cum_ret,
        benchmark_return=bench_ret,
        excess_return=excess,
        mdd=mdd,
        sharpe_ratio=sharpe,
        n_trades=len(trades),
        n_rebalances=len(rebal_events),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def portfolio_backtest(
    candles: dict[str, pd.DataFrame],
    signal: PortfolioSignal,
    *,
    context: PortfolioContext | None = None,
    fee: float = UPBIT_DEFAULT_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
    initial_krw: float = 1_000_000.0,
    start_date: pd.Timestamp | None = None,
    end_date: pd.Timestamp | None = None,
) -> PortfolioBacktestResult:
    """Universe 전체 시뮬레이션.

    각 날짜에 대해:
        1. rebal tick 이면 signal 호출 → target weights → sells→buys 체결.
        2. 현 포지션 + cash 를 mark-to-market 해 equity curve 에 추가.
        3. equal-weight B&H benchmark curve 를 병행 계산.

    Args:
        candles: `ticker → pd.DataFrame(OHLCV, index=DatetimeIndex)`.
        signal: `(candles_up_to_t, t, ctx) → dict[ticker, weight]`.
        context: PortfolioContext. None 이면 default.
        fee: 매수·매도 양쪽 수수료율.
        slippage: 슬리피지율.
        initial_krw: 시작 자본.
        start_date: 시뮬레이션 시작 날짜. None 이면 universe 의 첫 날짜.
            start_date 이전 데이터는 signal 의 lookback/regime 계산용으로만 쓰이고,
            equity/trades 에는 기록되지 않는다 (walk-forward 용).
        end_date: 시뮬레이션 종료 날짜. None 이면 universe 의 마지막 날짜.
    """
    ctx = context or PortfolioContext()
    idx = _align_universe(candles)
    if len(idx) == 0 or initial_krw <= 0:
        return PortfolioBacktestResult(initial_krw=initial_krw)

    # 시작/종료 position 결정
    if start_date is not None:
        mask = idx >= start_date
        if not mask.any():
            return PortfolioBacktestResult(initial_krw=initial_krw)
        start_pos = int(mask.argmax())
    else:
        start_pos = 0
    if end_date is not None:
        mask_end = idx <= end_date
        if not mask_end.any():
            return PortfolioBacktestResult(initial_krw=initial_krw)
        end_pos = int(len(idx) - mask_end[::-1].argmax())  # exclusive upper
    else:
        end_pos = len(idx)

    if start_pos >= end_pos:
        return PortfolioBacktestResult(initial_krw=initial_krw)

    cash = initial_krw
    positions: dict[str, float] = {}
    equity_points: list[tuple[pd.Timestamp, float]] = []
    bench_points: list[tuple[pd.Timestamp, float]] = []
    trades: list[PortfolioTrade] = []
    rebal_events: list[RebalanceEvent] = []

    # --- benchmark: equal-weight B&H (시뮬레이션 시작 시점 기준) ---
    first_date = idx[start_pos]
    bench_available = [t for t in candles if _close_at(candles, t, first_date) is not None]
    bench_positions: dict[str, float] = {}
    if bench_available:
        alloc = initial_krw / len(bench_available)
        for t in bench_available:
            p0 = _close_at(candles, t, first_date)
            if p0 and p0 > 0:
                bench_positions[t] = alloc / p0

    rebal_days = max(1, int(ctx.rebal_days))

    for rel_i, i in enumerate(range(start_pos, end_pos)):
        date = idx[i]
        is_rebal = (rel_i % rebal_days == 0)

        if is_rebal:
            sliced = {t: df.loc[:date] for t, df in candles.items() if not df.empty}
            raw_weights = signal(sliced, date, ctx) or {}
            w_sum = sum(max(0.0, v) for v in raw_weights.values())
            if w_sum > ctx.risk_budget and w_sum > 0:
                factor = ctx.risk_budget / w_sum
                target_weights = {k: max(0.0, v) * factor for k, v in raw_weights.items()}
            else:
                target_weights = {k: max(0.0, v) for k, v in raw_weights.items()}

            pv_before = _mark_to_market(candles, positions, date, cash)
            ev_trades, cash, positions = _apply_rebalance(
                candles, date, positions, cash,
                target_weights=target_weights,
                portfolio_value=pv_before,
                fee=fee, slippage=slippage,
            )
            trades.extend(ev_trades)
            pv_after = _mark_to_market(candles, positions, date, cash)

            realized: dict[str, float] = {}
            if pv_after > 0:
                for t, shares in positions.items():
                    p = _close_at(candles, t, date)
                    if p is not None:
                        realized[t] = (shares * p) / pv_after

            rebal_events.append(RebalanceEvent(
                date=date,
                target_weights=dict(target_weights),
                realized_weights=realized,
                portfolio_value_before=pv_before,
                portfolio_value_after=pv_after,
                trades=list(ev_trades),
            ))

        pv_now = _mark_to_market(candles, positions, date, cash)
        equity_points.append((date, pv_now))

        bench_val = 0.0
        for t, shares in bench_positions.items():
            p = _close_at(candles, t, date)
            if p is not None:
                bench_val += shares * p
        bench_points.append((date, bench_val))

    return _finalize_result(
        equity_points, bench_points, trades, rebal_events,
        initial_krw=initial_krw,
    )

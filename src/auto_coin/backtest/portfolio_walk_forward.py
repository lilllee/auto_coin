"""Portfolio-aware walk-forward validation.

기존 `walk_forward.py` (per-ticker Strategy) 와 독립적으로, universe 단위
walk-forward 를 수행한다. CSMOM 등 portfolio 전략의 Stage 4 판정에 사용.

설계 포인트:

- Train 구간에서 파라미터 grid 탐색 → optimizer metric (default: sharpe) 최적
- Test 구간에서 해당 파라미터로 portfolio_backtest 실행
- 윈도우 간 rolling step 으로 반복 (2y 데이터 / 180d train / 60d test / 30d step → 12~18 windows)
- 집계:
    avg_train / avg_test / avg_benchmark / avg_excess
    positive_excess_ratio
    train_test_ratio (과적합 지표)
    trade_count aggregate

본 모듈은 signal factory 를 받는다 — CSMOM 구현체가 `params → PortfolioSignal`
factory 를 제공하면 여기서 탐색/검증한다.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from auto_coin.backtest.portfolio_runner import (
    DEFAULT_SLIPPAGE,
    UPBIT_DEFAULT_FEE,
    PortfolioBacktestResult,
    PortfolioContext,
    PortfolioSignal,
    _align_universe,
    portfolio_backtest,
)

# Signal factory: params dict → PortfolioSignal + context-update dict (rebal_days 등)
# 리턴은 (signal, context_overrides) 튜플. overrides 없으면 빈 dict.
SignalFactory = Callable[
    [dict[str, Any]],
    tuple[PortfolioSignal, dict[str, Any]],
]


@dataclass(frozen=True)
class PortfolioWindowResult:
    """단일 walk-forward 윈도우 결과."""

    window_id: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict[str, Any]
    train_return: float
    test_return: float
    test_benchmark: float
    test_excess: float
    test_mdd: float
    test_trades: int
    test_rebalances: int
    test_sharpe: float


@dataclass(frozen=True)
class PortfolioWalkForwardResult:
    """Walk-forward 요약."""

    param_grid: dict[str, list]
    n_windows: int = 0
    avg_train_return: float = 0.0
    avg_test_return: float = 0.0
    avg_test_benchmark: float = 0.0
    avg_test_excess: float = 0.0
    positive_excess_ratio: float = 0.0     # test_excess > 0 인 윈도우 비율
    train_test_ratio: float = 0.0          # |avg_train| / |avg_test|
    total_test_trades: int = 0
    best_param_stability: float = 0.0      # 가장 빈번한 best_params 의 점유율
    windows: list[PortfolioWindowResult] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"portfolio-WF  n={self.n_windows}  "
            f"avg_test={self.avg_test_return*100:+6.2f}%  "
            f"bnh={self.avg_test_benchmark*100:+6.2f}%  "
            f"excess={self.avg_test_excess*100:+6.2f}%  "
            f"positive={self.positive_excess_ratio*100:4.1f}%  "
            f"T/T={self.train_test_ratio:4.2f}x  "
            f"trades={self.total_test_trades}  "
            f"best_stab={self.best_param_stability*100:4.1f}%"
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _slice_universe(
    candles: dict[str, pd.DataFrame],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    return {t: df.loc[start:end] for t, df in candles.items() if not df.empty}


def _iter_param_combos(grid: dict[str, Iterable]) -> list[dict[str, Any]]:
    if not grid:
        return [{}]
    keys = list(grid.keys())
    vals = [list(grid[k]) for k in keys]
    return [dict(zip(keys, combo, strict=False)) for combo in itertools.product(*vals)]


def _build_context(base: PortfolioContext, overrides: dict[str, Any]) -> PortfolioContext:
    """overrides 로 PortfolioContext 를 복제 (frozen dataclass 대응)."""
    if not overrides:
        return base
    data = {f: getattr(base, f) for f in base.__dataclass_fields__}
    for k, v in overrides.items():
        if k in data:
            data[k] = v
    return PortfolioContext(**data)


def _score(result: PortfolioBacktestResult, metric: str) -> float:
    if metric == "cumulative_return":
        return result.cumulative_return
    if metric == "sharpe_ratio":
        return result.sharpe_ratio
    if metric == "excess_return":
        return result.excess_return
    raise ValueError(f"unknown optimize metric: {metric}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def portfolio_walk_forward(
    candles: dict[str, pd.DataFrame],
    factory: SignalFactory,
    *,
    param_grid: dict[str, list],
    base_context: PortfolioContext | None = None,
    train_days: int = 180,
    test_days: int = 60,
    step_days: int = 30,
    fee: float = UPBIT_DEFAULT_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
    initial_krw: float = 1_000_000.0,
    optimize_by: str = "sharpe_ratio",
) -> PortfolioWalkForwardResult:
    """Portfolio 전략의 walk-forward 검증.

    Args:
        candles: universe dict.
        factory: `params → (PortfolioSignal, context_overrides)`. CSMOM 구현체가 제공.
        param_grid: 탐색할 파라미터 조합.
        base_context: 기본 PortfolioContext (rebal_days / risk_budget 등).
        train_days / test_days / step_days: 롤링 윈도우 설정.
        optimize_by: train 에서 고를 기준 메트릭.

    Returns:
        PortfolioWalkForwardResult. 윈도우 0개여도 비어있는 결과 반환 (크래시 안 함).
    """
    idx = _align_universe(candles)
    base_ctx = base_context or PortfolioContext()
    if len(idx) < train_days + test_days or not param_grid:
        return PortfolioWalkForwardResult(param_grid=dict(param_grid))

    combos = _iter_param_combos(param_grid)
    windows: list[PortfolioWindowResult] = []

    # 시그널 lookback + regime_ma 를 여유있게 커버하기 위해 warmup 슬라이스.
    # train_days 만큼을 그대로 warmup 으로 재사용 — 어떤 param 조합의 lookback 이든 커버.
    start = 0
    window_id = 0
    while start + train_days + test_days <= len(idx):
        train_start_ts = idx[start]
        train_end_ts = idx[start + train_days - 1]
        test_start_ts = idx[start + train_days]
        test_end_ts = idx[min(start + train_days + test_days - 1, len(idx) - 1)]

        # train: train 기간 전체를 포함 (warmup 없이도 180d 면 충분)
        train_candles = _slice_universe(candles, train_start_ts, train_end_ts)
        # test: train 구간까지 포함한 확장 슬라이스 — signal 이 lookback/regime 를
        # 충분히 계산할 수 있도록. start_date 로 "실제 시뮬레이션은 test_start 부터"
        # 를 보장해 train 구간의 trade 가 test 에 누수되지 않음.
        test_candles_extended = _slice_universe(candles, train_start_ts, test_end_ts)

        # --- 1. train 에서 best params 선택 ---
        best_params: dict[str, Any] = {}
        best_score = -float("inf")
        best_train: PortfolioBacktestResult | None = None
        for params in combos:
            try:
                signal, overrides = factory(params)
            except Exception:
                continue
            ctx = _build_context(base_ctx, overrides)
            try:
                r = portfolio_backtest(
                    train_candles, signal,
                    context=ctx, fee=fee, slippage=slippage, initial_krw=initial_krw,
                )
            except Exception:
                continue
            s = _score(r, optimize_by)
            if s > best_score:
                best_score = s
                best_params = dict(params)
                best_train = r

        if best_train is None:
            start += step_days
            window_id += 1
            continue

        # --- 2. test 에서 best params 로 평가 (warmup 포함, start_date 로 경계) ---
        signal, overrides = factory(best_params)
        ctx = _build_context(base_ctx, overrides)
        test_r = portfolio_backtest(
            test_candles_extended, signal,
            context=ctx, fee=fee, slippage=slippage, initial_krw=initial_krw,
            start_date=test_start_ts,
            end_date=test_end_ts,
        )

        windows.append(PortfolioWindowResult(
            window_id=window_id,
            train_start=str(train_start_ts.date()),
            train_end=str(train_end_ts.date()),
            test_start=str(test_start_ts.date()),
            test_end=str(test_end_ts.date()),
            best_params=best_params,
            train_return=best_train.cumulative_return,
            test_return=test_r.cumulative_return,
            test_benchmark=test_r.benchmark_return,
            test_excess=test_r.excess_return,
            test_mdd=test_r.mdd,
            test_trades=test_r.n_trades,
            test_rebalances=test_r.n_rebalances,
            test_sharpe=test_r.sharpe_ratio,
        ))

        start += step_days
        window_id += 1

    if not windows:
        return PortfolioWalkForwardResult(param_grid=dict(param_grid))

    # --- 3. 집계 ---
    n = len(windows)
    avg_train = sum(w.train_return for w in windows) / n
    avg_test = sum(w.test_return for w in windows) / n
    avg_bnh = sum(w.test_benchmark for w in windows) / n
    avg_excess = sum(w.test_excess for w in windows) / n
    positive = sum(1 for w in windows if w.test_excess > 0) / n
    total_trades = sum(w.test_trades for w in windows)
    tt_ratio = (abs(avg_train) / abs(avg_test)) if abs(avg_test) > 1e-12 else 0.0

    # best-param 안정성: 가장 빈번한 params 조합의 점유율
    param_counts: dict[tuple, int] = {}
    for w in windows:
        key = tuple(sorted(w.best_params.items()))
        param_counts[key] = param_counts.get(key, 0) + 1
    stability = (max(param_counts.values()) / n) if param_counts else 0.0

    return PortfolioWalkForwardResult(
        param_grid=dict(param_grid),
        n_windows=n,
        avg_train_return=avg_train,
        avg_test_return=avg_test,
        avg_test_benchmark=avg_bnh,
        avg_test_excess=avg_excess,
        positive_excess_ratio=positive,
        train_test_ratio=tt_ratio,
        total_test_trades=total_trades,
        best_param_stability=stability,
        windows=windows,
    )

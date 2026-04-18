"""B5 · CSMOM v2 REVISE + regime-only baseline 분해.

4-way walk-forward 비교:
    1. CSMOM v1   — B4 원본 grid
    2. Regime-only equal_weight baseline
    3. Regime-only btc_only baseline
    4. CSMOM v2   — stability 우선 축소 grid

목적: "CSMOM excess 가 momentum selection 에서 오는지, 단순 regime 회피에서 오는지"
분해. v2 는 top_k=1 금지 · lookback 축소 · regime_ma 축소로 overfit 제어.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pyupbit

from auto_coin.backtest.portfolio_runner import (
    DEFAULT_SLIPPAGE,
    UPBIT_DEFAULT_FEE,
    PortfolioContext,
)
from auto_coin.backtest.portfolio_walk_forward import (
    PortfolioWalkForwardResult,
    portfolio_walk_forward,
)
from auto_coin.strategy.portfolio.baselines import (
    regime_baseline_factory_btc,
    regime_baseline_factory_equal,
)
from auto_coin.strategy.portfolio.csmom import csmom_factory

UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
DAYS = 730


def fetch() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for t in UNIVERSE:
        df = pyupbit.get_ohlcv(t, interval="day", count=DAYS)
        out[t] = df
        print(f"# {t}: {len(df)} candles")
    return out


def run_one(
    label: str,
    candles: dict[str, pd.DataFrame],
    factory,
    param_grid: dict[str, list],
    base_ctx: PortfolioContext,
) -> PortfolioWalkForwardResult:
    r = portfolio_walk_forward(
        candles, factory,
        param_grid=param_grid, base_context=base_ctx,
        train_days=180, test_days=30, step_days=30,
        fee=UPBIT_DEFAULT_FEE, slippage=DEFAULT_SLIPPAGE,
        initial_krw=1_000_000,
        optimize_by="excess_return",
    )
    print(f"\n=== {label} ===")
    print(f"  grid: {param_grid}")
    print(f"  n_windows={r.n_windows}  avg_test_excess={r.avg_test_excess * 100:+.2f}%  "
          f"positive={r.positive_excess_ratio * 100:4.1f}%  "
          f"T/T={r.train_test_ratio:4.2f}x  trades={r.total_test_trades}  "
          f"stability={r.best_param_stability * 100:4.1f}%")

    strategic = [w for w in r.windows if w.test_trades > 0]
    flat = [w for w in r.windows if w.test_trades == 0]
    if strategic:
        sa = sum(w.test_excess for w in strategic) / len(strategic)
        sp = sum(1 for w in strategic if w.test_excess > 0) / len(strategic)
        print(f"  strategic (n={len(strategic)}): avg_excess={sa * 100:+.2f}%  "
              f"positive={sp * 100:4.1f}%")
    if flat:
        fa = sum(w.test_excess for w in flat) / len(flat)
        print(f"  flat      (n={len(flat)}): avg_excess={fa * 100:+.2f}%")
    return r


def print_three_way(results: dict[str, PortfolioWalkForwardResult]) -> None:
    print("\n" + "=" * 100)
    print("4-WAY COMPARISON")
    print("=" * 100)
    print(f"{'label':<22} {'avg_excess':>10} {'positive':>9} {'T/T':>7} "
          f"{'trades':>7} {'stab':>6} {'strategic_avg':>13} {'strategic_pos':>13}")
    for label, r in results.items():
        strategic = [w for w in r.windows if w.test_trades > 0]
        sa = sum(w.test_excess for w in strategic) / len(strategic) if strategic else 0.0
        sp = sum(1 for w in strategic if w.test_excess > 0) / len(strategic) if strategic else 0.0
        print(
            f"{label:<22} "
            f"{r.avg_test_excess * 100:+9.2f}% "
            f"{r.positive_excess_ratio * 100:7.1f}% "
            f"{r.train_test_ratio:6.2f}x "
            f"{r.total_test_trades:7d} "
            f"{r.best_param_stability * 100:5.1f}% "
            f"{sa * 100:+12.2f}% "
            f"{sp * 100:12.1f}%",
        )


def decomposition(results: dict[str, PortfolioWalkForwardResult]) -> None:
    print("\n" + "=" * 100)
    print("SELECTION ALPHA DECOMPOSITION")
    print("=" * 100)
    v1 = results["CSMOM v1"]
    reg_eq = results["regime_equal_weight"]
    v2 = results.get("CSMOM v2")

    v1_strat = [w for w in v1.windows if w.test_trades > 0]
    v1_strat_avg = sum(w.test_excess for w in v1_strat) / len(v1_strat) if v1_strat else 0.0

    reg_strat = [w for w in reg_eq.windows if w.test_trades > 0]
    reg_strat_avg = sum(w.test_excess for w in reg_strat) / len(reg_strat) if reg_strat else 0.0

    # v1 vs baseline: incremental alpha from momentum selection
    # = v1.strategic_avg - baseline.strategic_avg (매우 단순화 · 윈도우별 matching X)
    incremental = v1_strat_avg - reg_strat_avg

    print(f"  CSMOM v1 strategic avg_excess       : {v1_strat_avg * 100:+.2f}%")
    print(f"  regime_equal baseline strategic avg : {reg_strat_avg * 100:+.2f}%")
    print(f"  → incremental selection alpha (v1-baseline) : {incremental * 100:+.2f}%")
    if v2 is not None:
        v2_strat = [w for w in v2.windows if w.test_trades > 0]
        v2_strat_avg = sum(w.test_excess for w in v2_strat) / len(v2_strat) if v2_strat else 0.0
        inc_v2 = v2_strat_avg - reg_strat_avg
        print(f"  CSMOM v2 strategic avg_excess       : {v2_strat_avg * 100:+.2f}%")
        print(f"  → incremental selection alpha (v2-baseline) : {inc_v2 * 100:+.2f}%")

    # overall avg_excess 측면
    v1_regime_contribution = v1.avg_test_excess - v1_strat_avg
    print(f"\n  v1 전체 avg_excess 중 regime-flat 덕     : ~ {v1_regime_contribution * 100:+.2f}%p")


def main() -> None:
    candles = fetch()

    base_ctx = PortfolioContext(
        risk_budget=0.8, rebal_days=7, hold_N=3,
        lookback_days=60, active_strategy_group="b5",
    )

    results: dict[str, PortfolioWalkForwardResult] = {}

    # 1. CSMOM v1 — B4 원본 grid
    v1_grid: dict[str, list[Any]] = {
        "lookback_days": [30, 60, 90],
        "top_k": [2, 3, 4],
        "rebal_days": [7, 14],
        "regime_ma_window": [100, 150],
    }
    results["CSMOM v1"] = run_one(
        "CSMOM v1 (B4 grid)", candles, csmom_factory, v1_grid, base_ctx,
    )

    # 2. Regime-only equal_weight baseline
    baseline_grid: dict[str, list[Any]] = {
        "regime_ma_window": [50, 100, 150, 200],
        "rebal_days": [7, 14],
    }
    results["regime_equal_weight"] = run_one(
        "Regime-only Equal-Weight", candles,
        regime_baseline_factory_equal, baseline_grid, base_ctx,
    )

    # 3. Regime-only btc_only baseline
    results["regime_btc_only"] = run_one(
        "Regime-only BTC-only", candles,
        regime_baseline_factory_btc, baseline_grid, base_ctx,
    )

    # 4. CSMOM v2 — stability 우선 축소 grid
    #    - top_k >= 2 (이미 v1 grid 가 2 부터라 변경 없음)
    #    - lookback 30 제거 (winner-chasing 의심)
    #    - regime_ma 축소 (100, 150 만)
    #    - rebal_days 14 로 고정 (turnover 감소)
    v2_grid: dict[str, list[Any]] = {
        "lookback_days": [60, 90, 120],
        "top_k": [2, 3],
        "rebal_days": [14],
        "regime_ma_window": [100, 150],
    }
    results["CSMOM v2"] = run_one(
        "CSMOM v2 (stability-first)", candles, csmom_factory, v2_grid, base_ctx,
    )

    # 5. Comparison + decomposition
    print_three_way(results)
    decomposition(results)


if __name__ == "__main__":
    main()

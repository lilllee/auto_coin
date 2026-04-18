"""B6 · CSMOM v3 stability-first 최종 시도.

v3 grid (6 조합):
    lookback_days ∈ {45, 60, 90}
    top_k         ∈ {2}
    rebal_days    ∈ {14}
    regime_ma     ∈ {100, 150}

4-way WF 비교: v1 / v2 / v3 / regime_equal_weight baseline.
strategic-only 기준을 메인 지표로 승격.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
from auto_coin.strategy.portfolio.baselines import regime_baseline_factory_equal
from auto_coin.strategy.portfolio.csmom import csmom_factory

UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]
DAYS = 730


@dataclass
class ModelSpec:
    label: str
    factory: Callable[[dict[str, Any]], Any]
    grid: dict[str, list[Any]]


def fetch() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for t in UNIVERSE:
        df = pyupbit.get_ohlcv(t, interval="day", count=DAYS)
        out[t] = df
        print(f"# {t}: {len(df)}")
    return out


def run(spec: ModelSpec, candles: dict[str, pd.DataFrame]) -> PortfolioWalkForwardResult:
    base = PortfolioContext(
        risk_budget=0.8, rebal_days=7, hold_N=3,
        lookback_days=60, active_strategy_group="b6",
    )
    return portfolio_walk_forward(
        candles, spec.factory,
        param_grid=spec.grid, base_context=base,
        train_days=180, test_days=30, step_days=30,
        fee=UPBIT_DEFAULT_FEE, slippage=DEFAULT_SLIPPAGE,
        initial_krw=1_000_000, optimize_by="excess_return",
    )


def metrics(r: PortfolioWalkForwardResult) -> dict[str, Any]:
    strategic = [w for w in r.windows if w.test_trades > 0]
    flat = [w for w in r.windows if w.test_trades == 0]
    s_avg = sum(w.test_excess for w in strategic) / len(strategic) if strategic else 0.0
    s_pos = sum(1 for w in strategic if w.test_excess > 0) / len(strategic) if strategic else 0.0
    f_avg = sum(w.test_excess for w in flat) / len(flat) if flat else 0.0
    return {
        "n_windows": r.n_windows,
        "avg_excess": r.avg_test_excess,
        "positive_ratio": r.positive_excess_ratio,
        "train_test_ratio": r.train_test_ratio,
        "trades": r.total_test_trades,
        "stability": r.best_param_stability,
        "strategic_avg": s_avg,
        "strategic_positive": s_pos,
        "strategic_n": len(strategic),
        "flat_avg": f_avg,
        "flat_n": len(flat),
    }


def pct(x: float) -> str:
    return f"{x * 100:+7.2f}%"


def print_block(label: str, m: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    print(f"  n_windows                : {m['n_windows']}")
    print(f"  avg_excess (전체)          : {pct(m['avg_excess'])}")
    print(f"  positive_ratio (전체)      : {m['positive_ratio'] * 100:5.1f}%")
    print(f"  train_test_ratio          : {m['train_test_ratio']:5.2f}x")
    print(f"  total_test_trades         : {m['trades']}")
    print(f"  best_param_stability      : {m['stability'] * 100:5.1f}%")
    print(f"  strategic_avg (trades>0)  : {pct(m['strategic_avg'])}  "
          f"(n={m['strategic_n']})")
    print(f"  strategic_positive_ratio  : {m['strategic_positive'] * 100:5.1f}%")
    print(f"  flat_avg (trades=0)       : {pct(m['flat_avg'])}  "
          f"(n={m['flat_n']})")


def main() -> None:
    candles = fetch()

    specs = [
        ModelSpec(
            "v1 (B4 grid, 36 combos)",
            csmom_factory,
            {
                "lookback_days": [30, 60, 90],
                "top_k": [2, 3, 4],
                "rebal_days": [7, 14],
                "regime_ma_window": [100, 150],
            },
        ),
        ModelSpec(
            "v2 (B5, 12 combos)",
            csmom_factory,
            {
                "lookback_days": [60, 90, 120],
                "top_k": [2, 3],
                "rebal_days": [14],
                "regime_ma_window": [100, 150],
            },
        ),
        ModelSpec(
            "v3 (B6 stability-first, 6 combos)",
            csmom_factory,
            {
                "lookback_days": [45, 60, 90],
                "top_k": [2],
                "rebal_days": [14],
                "regime_ma_window": [100, 150],
            },
        ),
        ModelSpec(
            "regime_equal_weight baseline",
            regime_baseline_factory_equal,
            {
                "regime_ma_window": [50, 100, 150, 200],
                "rebal_days": [7, 14],
            },
        ),
    ]

    results: dict[str, dict[str, Any]] = {}
    raw: dict[str, PortfolioWalkForwardResult] = {}
    for spec in specs:
        r = run(spec, candles)
        raw[spec.label] = r
        results[spec.label] = metrics(r)
        print_block(spec.label, results[spec.label])

    # Baseline 참조
    baseline_key = "regime_equal_weight baseline"
    base_strat = results[baseline_key]["strategic_avg"]

    print("\n" + "=" * 108)
    print("4-WAY TABLE (strategic-only metrics promoted)")
    print("=" * 108)
    header = (
        f"{'model':<40} "
        f"{'avg':>8} "
        f"{'strat_avg':>10} "
        f"{'strat_pos':>10} "
        f"{'pos':>7} "
        f"{'T/T':>6} "
        f"{'trades':>7} "
        f"{'stab':>6} "
        f"{'incr_alpha':>10}"
    )
    print(header)
    for label, m in results.items():
        incr = m["strategic_avg"] - base_strat if label != baseline_key else 0.0
        print(
            f"{label:<40} "
            f"{pct(m['avg_excess']):>8} "
            f"{pct(m['strategic_avg']):>10} "
            f"{m['strategic_positive'] * 100:9.1f}% "
            f"{m['positive_ratio'] * 100:6.1f}% "
            f"{m['train_test_ratio']:5.2f}x "
            f"{m['trades']:7d} "
            f"{m['stability'] * 100:5.1f}% "
            f"{pct(incr):>10}",
        )

    # v3 PASS 조건 체크
    print("\n" + "=" * 108)
    print("v3 PASS CRITERIA (B6 spec)")
    print("=" * 108)
    v3 = results["v3 (B6 stability-first, 6 combos)"]
    incr_v3 = v3["strategic_avg"] - base_strat

    def check(cond_pass: bool, cond_warn: bool, label: str, actual: str) -> None:
        tag = "✅ pass" if cond_pass else ("⚠️  warn" if cond_warn else "❌ FAIL")
        print(f"  {label:<35}: {tag:<10} actual={actual}")

    check(v3["stability"] >= 0.60, v3["stability"] >= 0.50,
          "stability >= 60%", f"{v3['stability'] * 100:.1f}%")
    check(v3["strategic_avg"] >= 0, v3["strategic_avg"] >= -0.005,
          "strategic_avg >= 0", pct(v3["strategic_avg"]))
    check(incr_v3 > 0, incr_v3 > -0.01,
          "incremental selection alpha > 0", pct(incr_v3))
    check(v3["positive_ratio"] >= 0.55, v3["positive_ratio"] >= 0.40,
          "positive_ratio >= 55%", f"{v3['positive_ratio'] * 100:.1f}%")
    check(v3["train_test_ratio"] <= 4.0, v3["train_test_ratio"] <= 5.0,
          "train_test_ratio <= 4x (ideal)", f"{v3['train_test_ratio']:.2f}x")
    check(v3["trades"] >= 50, v3["trades"] >= 30,
          "total_test_trades >= 50", f"{v3['trades']}")


if __name__ == "__main__":
    main()

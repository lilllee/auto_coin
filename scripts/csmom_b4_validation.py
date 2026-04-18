"""B4 · CSMOM Stage 3 sensitivity + Stage 4 walk-forward 검증.

한 번의 API 호출로 universe candles 를 캐싱한 뒤,
sensitivity grid 와 portfolio walk-forward 를 in-memory 로 평가한다.

출력:
- Stage 3: 파라미터 grid 별 cumulative/excess/MDD/Sharpe/trades/rebals 표
- Stage 4: walk-forward 윈도우별 + aggregate 메트릭
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from typing import Any

import pandas as pd
import pyupbit

from auto_coin.backtest.portfolio_runner import (
    DEFAULT_SLIPPAGE,
    UPBIT_DEFAULT_FEE,
    PortfolioContext,
    portfolio_backtest,
)
from auto_coin.backtest.portfolio_walk_forward import portfolio_walk_forward
from auto_coin.strategy.portfolio.csmom import (
    CsmomParams,
    csmom_factory,
    make_csmom_signal,
)

DEFAULT_UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-DOGE"]


def fetch_candles(tickers: list[str], days: int) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = pyupbit.get_ohlcv(t, interval="day", count=days)
        if df is None or df.empty:
            print(f"# WARN: {t} no data, skip", file=sys.stderr)
            continue
        out[t] = df
        print(
            f"# {t}: {len(df)} candles  "
            f"{df.index[0].date()} -> {df.index[-1].date()}",
            file=sys.stderr,
        )
    return out


# ---------------------------------------------------------------------------
# Stage 3 · sensitivity sweep
# ---------------------------------------------------------------------------


def run_sensitivity(
    candles: dict[str, pd.DataFrame],
    *,
    lookbacks: list[int],
    top_ks: list[int],
    rebals: list[int],
    regime_mas: list[int],
    regime_enabled_values: list[bool],
    risk_budget: float,
    initial_krw: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    combos = list(itertools.product(
        lookbacks, top_ks, rebals, regime_mas, regime_enabled_values,
    ))
    print(f"# sensitivity grid size: {len(combos)}", file=sys.stderr)
    for i, (lb, tk, rb, rma, reg_on) in enumerate(combos):
        params = CsmomParams(
            lookback_days=lb, top_k=tk,
            regime_enabled=reg_on, regime_ma_window=rma,
            regime_ticker="KRW-BTC",
        )
        ctx = PortfolioContext(
            risk_budget=risk_budget, rebal_days=rb, hold_N=tk,
            lookback_days=lb, active_strategy_group="csmom_v1",
        )
        signal = make_csmom_signal(params)
        r = portfolio_backtest(
            candles, signal, context=ctx,
            fee=UPBIT_DEFAULT_FEE, slippage=DEFAULT_SLIPPAGE,
            initial_krw=initial_krw,
        )
        rows.append({
            "lookback": lb, "top_k": tk, "rebal": rb, "regime_ma": rma,
            "regime_on": reg_on,
            "cum": r.cumulative_return,
            "bnh": r.benchmark_return,
            "excess": r.excess_return,
            "mdd": r.mdd,
            "sharpe": r.sharpe_ratio,
            "trades": r.n_trades,
            "rebals": r.n_rebalances,
        })
        if (i + 1) % 25 == 0:
            print(f"# ... {i + 1}/{len(combos)} combos", file=sys.stderr)
    return rows


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+7.2f}%"


def summarize_sensitivity(rows: list[dict[str, Any]]) -> None:
    print("=" * 88)
    print("STAGE 3 · SENSITIVITY SWEEP RESULTS")
    print("=" * 88)

    # All combos
    total = len(rows)
    positive = sum(1 for r in rows if r["excess"] > 0)
    strong = sum(1 for r in rows if r["excess"] >= 0.1)
    hard_fail_mdd = sum(1 for r in rows if r["mdd"] < -0.30)
    hard_fail_excess = sum(1 for r in rows if r["excess"] <= 0)
    print(f"  total combos         : {total}")
    print(f"  excess > 0           : {positive} ({positive / total * 100:.1f}%)")
    print(f"  excess >= +10%       : {strong} ({strong / total * 100:.1f}%)")
    print(f"  excess <= 0 (hard-fail): {hard_fail_excess}")
    print(f"  MDD < -30% (hard-fail): {hard_fail_mdd}")
    print()

    # Default neighbourhood (lookback=60, top_k=3, rebal=7, regime_ma=100, regime_on=True)
    print("-- Neighbourhood of default (lb=60, k=3, rb=7, rma=100, reg=ON) --")
    default = next(
        (r for r in rows if r["lookback"] == 60 and r["top_k"] == 3
         and r["rebal"] == 7 and r["regime_ma"] == 100 and r["regime_on"]),
        None,
    )
    if default:
        print(f"  default: excess={_fmt_pct(default['excess'])}  "
              f"sharpe={default['sharpe']:.2f}  mdd={_fmt_pct(default['mdd'])}  "
              f"trades={default['trades']}")

    # Table by (lookback, top_k, rebal_days) at regime_ma=100, regime_on=True
    print()
    print("-- Slice: regime_ma=100, regime=ON --")
    print(f"{'lookback':>9} {'top_k':>6} {'rebal':>6} "
          f"{'excess':>9} {'sharpe':>8} {'mdd':>9} {'trades':>7}")
    slice_rows = [
        r for r in rows if r["regime_ma"] == 100 and r["regime_on"]
    ]
    for r in sorted(
        slice_rows,
        key=lambda x: (x["lookback"], x["top_k"], x["rebal"]),
    ):
        print(
            f"{r['lookback']:>9} {r['top_k']:>6} {r['rebal']:>6} "
            f"{_fmt_pct(r['excess']):>9} {r['sharpe']:>8.2f} "
            f"{_fmt_pct(r['mdd']):>9} {r['trades']:>7}",
        )

    # regime_ma sensitivity at (lookback=60, top_k=3, rebal=7)
    print()
    print("-- regime_ma sweep (lb=60, k=3, rb=7) --")
    for r in sorted(
        [x for x in rows if x["lookback"] == 60 and x["top_k"] == 3
         and x["rebal"] == 7],
        key=lambda x: (x["regime_on"], x["regime_ma"]),
    ):
        tag = f"regime_ma={r['regime_ma']}" if r["regime_on"] else "regime OFF"
        print(f"  {tag:>16}  excess={_fmt_pct(r['excess'])}  "
              f"sharpe={r['sharpe']:.2f}  mdd={_fmt_pct(r['mdd'])}  "
              f"trades={r['trades']}")

    # Top-5 and bottom-5 by excess
    print()
    print("-- Top 5 by excess --")
    for r in sorted(rows, key=lambda x: -x["excess"])[:5]:
        print(f"  lb={r['lookback']:3d} k={r['top_k']} rb={r['rebal']:2d} "
              f"rma={r['regime_ma']:3d} reg={'ON' if r['regime_on'] else 'OFF'} "
              f"| excess={_fmt_pct(r['excess'])} sharpe={r['sharpe']:.2f} "
              f"mdd={_fmt_pct(r['mdd'])} trades={r['trades']}")
    print("-- Bottom 5 by excess --")
    for r in sorted(rows, key=lambda x: x["excess"])[:5]:
        print(f"  lb={r['lookback']:3d} k={r['top_k']} rb={r['rebal']:2d} "
              f"rma={r['regime_ma']:3d} reg={'ON' if r['regime_on'] else 'OFF'} "
              f"| excess={_fmt_pct(r['excess'])} sharpe={r['sharpe']:.2f} "
              f"mdd={_fmt_pct(r['mdd'])} trades={r['trades']}")

    # Stability: how does excess change when you perturb one axis?
    print()
    print("-- Axis stability (excess std-dev when one axis varies, others fixed at default) --")
    axes = {
        "lookback": ("lookback", lambda r: r["top_k"] == 3 and r["rebal"] == 7
                     and r["regime_ma"] == 100 and r["regime_on"]),
        "top_k": ("top_k", lambda r: r["lookback"] == 60 and r["rebal"] == 7
                  and r["regime_ma"] == 100 and r["regime_on"]),
        "rebal": ("rebal", lambda r: r["lookback"] == 60 and r["top_k"] == 3
                  and r["regime_ma"] == 100 and r["regime_on"]),
        "regime_ma": ("regime_ma", lambda r: r["lookback"] == 60 and r["top_k"] == 3
                      and r["rebal"] == 7 and r["regime_on"]),
    }
    for name, (_axis_key, cond) in axes.items():
        series = [r for r in rows if cond(r)]
        if len(series) < 2:
            continue
        vals = [r["excess"] for r in series]
        spread = max(vals) - min(vals)
        mean = sum(vals) / len(vals)
        print(f"  {name:>10}  n={len(series)}  mean={_fmt_pct(mean)}  "
              f"min={_fmt_pct(min(vals))}  max={_fmt_pct(max(vals))}  "
              f"spread={_fmt_pct(spread)}")


# ---------------------------------------------------------------------------
# Stage 4 · portfolio walk-forward
# ---------------------------------------------------------------------------


def run_walk_forward(
    candles: dict[str, pd.DataFrame],
    *,
    param_grid: dict[str, list],
    train_days: int,
    test_days: int,
    step_days: int,
    optimize_by: str,
    risk_budget: float,
    initial_krw: float,
) -> None:
    base_ctx = PortfolioContext(
        risk_budget=risk_budget, rebal_days=7, hold_N=3,
        lookback_days=60, active_strategy_group="csmom_v1",
    )
    result = portfolio_walk_forward(
        candles, csmom_factory,
        param_grid=param_grid,
        base_context=base_ctx,
        train_days=train_days, test_days=test_days, step_days=step_days,
        fee=UPBIT_DEFAULT_FEE, slippage=DEFAULT_SLIPPAGE,
        initial_krw=initial_krw,
        optimize_by=optimize_by,
    )

    print("=" * 100)
    print(f"STAGE 4 · PORTFOLIO WALK-FORWARD  "
          f"(train={train_days}d, test={test_days}d, step={step_days}d, opt={optimize_by})")
    print("=" * 100)
    print(f"  param_grid: {json.dumps(param_grid)}")
    print()
    print(f"  {'#':>3} {'train_range':<24} {'test_range':<24} "
          f"{'best_params':<42} {'train':>9} {'test':>9} {'bnh':>9} {'excess':>9} {'trades':>6}")
    for w in result.windows:
        bp = json.dumps(w.best_params, separators=(",", ":"))
        print(
            f"  {w.window_id:>3} "
            f"{w.train_start + ' → ' + w.train_end:<24} "
            f"{w.test_start + ' → ' + w.test_end:<24} "
            f"{bp:<42} "
            f"{_fmt_pct(w.train_return):>9} "
            f"{_fmt_pct(w.test_return):>9} "
            f"{_fmt_pct(w.test_benchmark):>9} "
            f"{_fmt_pct(w.test_excess):>9} "
            f"{w.test_trades:>6}",
        )
    print()
    print("-- AGGREGATE --")
    print(f"  n_windows                    : {result.n_windows}")
    print(f"  avg_train_return             : {_fmt_pct(result.avg_train_return)}")
    print(f"  avg_test_return              : {_fmt_pct(result.avg_test_return)}")
    print(f"  avg_test_benchmark (B&H)     : {_fmt_pct(result.avg_test_benchmark)}")
    print(f"  avg_test_excess              : {_fmt_pct(result.avg_test_excess)}")
    print(f"  positive_excess_ratio        : {result.positive_excess_ratio * 100:5.1f}%")
    print(f"  train_test_ratio             : {result.train_test_ratio:5.2f}x")
    print(f"  total_test_trades            : {result.total_test_trades}")
    print(f"  best_param_stability         : {result.best_param_stability * 100:5.1f}%")

    # PLAN_CSMOM §4 Stage 4 기준 판정
    print()
    print("-- STAGE 4 기준 판정 (PLAN_CSMOM §4) --")
    aex = result.avg_test_excess
    pos = result.positive_excess_ratio
    tt = result.train_test_ratio
    trades = result.total_test_trades

    def verdict(ok: bool, warn: bool) -> str:
        if ok:
            return "✅ pass"
        if warn:
            return "⚠️  warn"
        return "❌ HARD-FAIL"

    print(f"  avg_excess    ≥ +2%  : {verdict(aex >= 0.02, aex > 0):<20} "
          f"actual={_fmt_pct(aex)}")
    print(f"  positive_excess ≥ 55%: {verdict(pos >= 0.55, pos >= 0.40):<20} "
          f"actual={pos * 100:.1f}%")
    print(f"  train/test ≤ 3x      : {verdict(tt <= 3.0, tt <= 5.0):<20} "
          f"actual={tt:.2f}x")
    print(f"  test_trades ≥ 50     : {verdict(trades >= 50, trades >= 30):<20} "
          f"actual={trades}")
    print(f"  best_param_stability ≥ 60%: {verdict(result.best_param_stability >= 0.60, result.best_param_stability >= 0.30):<20} "
          f"actual={result.best_param_stability * 100:.1f}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CSMOM Stage 3 + Stage 4 validation")
    p.add_argument("--tickers", default=",".join(DEFAULT_UNIVERSE))
    p.add_argument("--days", type=int, default=730)
    p.add_argument("--risk-budget", type=float, default=0.8)
    p.add_argument("--initial-krw", type=float, default=1_000_000)
    # Stage 4 settings
    p.add_argument("--train-days", type=int, default=180)
    p.add_argument("--test-days", type=int, default=30)
    p.add_argument("--step-days", type=int, default=30)
    p.add_argument("--optimize-by", default="excess_return",
                   choices=["cumulative_return", "sharpe_ratio", "excess_return"])
    p.add_argument("--skip-stage3", action="store_true")
    p.add_argument("--skip-stage4", action="store_true")
    args = p.parse_args(argv)

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    candles = fetch_candles(tickers, args.days)
    if not candles:
        print("ERROR: no candles fetched", file=sys.stderr)
        return 1

    if not args.skip_stage3:
        lookbacks = [30, 45, 60, 90, 120]
        top_ks = [1, 2, 3, 4]
        rebals = [5, 7, 14]
        regime_mas = [50, 100, 150, 200]
        regime_on_list = [True, False]
        rows = run_sensitivity(
            candles,
            lookbacks=lookbacks, top_ks=top_ks,
            rebals=rebals, regime_mas=regime_mas,
            regime_enabled_values=regime_on_list,
            risk_budget=args.risk_budget,
            initial_krw=args.initial_krw,
        )
        summarize_sensitivity(rows)
        print()

    if not args.skip_stage4:
        # WF grid — sensitivity 결과를 보고 합리적 범위로 축소
        wf_grid = {
            "lookback_days": [30, 60, 90],
            "top_k": [2, 3, 4],
            "rebal_days": [7, 14],
            "regime_ma_window": [100, 150],
        }
        run_walk_forward(
            candles,
            param_grid=wf_grid,
            train_days=args.train_days,
            test_days=args.test_days,
            step_days=args.step_days,
            optimize_by=args.optimize_by,
            risk_budget=args.risk_budget,
            initial_krw=args.initial_krw,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

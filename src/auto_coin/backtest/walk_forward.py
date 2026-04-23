"""Walk-forward 검증.

Train 구간에서 최적 파라미터를 찾고, Test 구간에서 검증하여
과적합 여부를 판별한다. Rolling window 방식.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import pyupbit

from auto_coin.backtest.runner import (
    DEFAULT_SLIPPAGE,
    UPBIT_DEFAULT_FEE,
    BacktestResult,
    backtest,
)
from auto_coin.data.candles import enrich_for_strategy
from auto_coin.strategy import STRATEGY_REGISTRY, create_strategy

DEFAULT_PARAM_GRIDS: dict[str, dict[str, list]] = {
    "volatility_breakout": {
        "k": [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7],
    },
    "sma200_regime": {
        "ma_window": [180, 200, 220],
        "buffer_pct": [0.0, 0.005, 0.01],
    },
    "ema_adx_atr_trend": {
        "ema_fast_window": [20, 27, 35],
        "ema_slow_window": [100, 125, 150],
        "adx_threshold": [10.0, 14.0, 18.0],
        "adx_window": 90,
        "atr_window": 14,
    },
    "sma200_ema_adx_composite": {
        "adx_threshold": [8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0],
    },
    "atr_channel_breakout": {
        "atr_window": [7, 10, 14, 20, 30],
        "channel_multiplier": [0.75, 1.0, 1.5, 2.0],
    },
}


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardWindow:
    """단일 walk-forward 윈도우 결과."""

    window_id: int
    train_start: str  # ISO date string
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
    test_sharpe: float


@dataclass(frozen=True)
class WalkForwardResult:
    """Walk-forward 검증 요약."""

    strategy_name: str
    param_grid: dict[str, list]
    n_windows: int = 0
    avg_train_return: float = 0.0
    avg_test_return: float = 0.0
    avg_test_benchmark: float = 0.0
    avg_test_excess: float = 0.0
    positive_excess_ratio: float = 0.0
    train_test_ratio: float = 0.0
    windows: list[WalkForwardWindow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _param_combos(param_grid: dict[str, list | Any]) -> list[dict[str, Any]]:
    """Parameter grid → list of dicts.

    리스트 값은 sweep 대상, 스칼라 값은 고정 파라미터로 취급한다.
    """
    if not param_grid:
        return [{}]

    sweep_keys: list[str] = []
    sweep_values: list[list] = []
    fixed: dict[str, Any] = {}

    for k in sorted(param_grid.keys()):
        v = param_grid[k]
        if isinstance(v, list):
            sweep_keys.append(k)
            sweep_values.append(v)
        else:
            fixed[k] = v

    if not sweep_keys:
        return [dict(fixed)]

    combos: list[dict[str, Any]] = []
    for combo in itertools.product(*sweep_values):
        d = dict(fixed)
        d.update(zip(sweep_keys, combo, strict=True))
        combos.append(d)
    return combos


def _enrich(df: pd.DataFrame, strategy_name: str, params: dict) -> pd.DataFrame:
    """enrich_for_strategy wrapper — k/ma_window을 params에서 전달."""
    k = params.get("k", 0.5)
    ma_window = params.get("ma_window", 5)
    return enrich_for_strategy(df, strategy_name, params, k=k, ma_window=ma_window)


def _date_str(idx_val) -> str:
    """pandas Timestamp → ISO date 문자열."""
    if hasattr(idx_val, "date"):
        return idx_val.date().isoformat()
    return str(idx_val)[:10]


# ---------------------------------------------------------------------------
# 메인 walk-forward
# ---------------------------------------------------------------------------


def walk_forward(
    df: pd.DataFrame,
    strategy_name: str,
    param_grid: dict[str, list | Any] | None = None,
    *,
    train_days: int = 180,
    test_days: int = 30,
    fee: float = UPBIT_DEFAULT_FEE,
    slippage: float = DEFAULT_SLIPPAGE,
    stop_loss_ratio: float | None = None,
    enable_time_exit: bool = False,
    optimize_by: str = "cumulative_return",
) -> WalkForwardResult:
    """Rolling walk-forward 검증.

    Train 구간에서 param_grid의 모든 조합을 백테스트하고,
    optimize_by 기준 최적 파라미터를 Test 구간에서 검증한다.
    """
    if param_grid is None:
        param_grid = DEFAULT_PARAM_GRIDS.get(strategy_name, {})

    # sweep 대상이 있는지 확인
    has_sweep = any(isinstance(v, list) for v in param_grid.values())
    if not param_grid or not has_sweep:
        return WalkForwardResult(
            strategy_name=strategy_name,
            param_grid=param_grid if param_grid else {},
        )

    combos = _param_combos(param_grid)

    # Pre-enrich cache: 전체 df를 각 combo로 한 번씩만 enrichment
    cache: dict[tuple, pd.DataFrame] = {}
    for combo in combos:
        key = tuple(sorted(combo.items()))
        cache[key] = _enrich(df, strategy_name, combo)

    # 윈도우 생성
    n_rows = len(df)
    window_specs: list[tuple[int, int, int, int]] = []
    ws = 0
    while ws + train_days + test_days <= n_rows:
        train_start = ws
        train_end = ws + train_days
        test_start = train_end
        test_end = train_end + test_days
        window_specs.append((train_start, train_end, test_start, test_end))
        ws += test_days

    if not window_specs:
        return WalkForwardResult(
            strategy_name=strategy_name,
            param_grid=param_grid,
        )

    windows: list[WalkForwardWindow] = []

    for wid, (tr_s, tr_e, te_s, te_e) in enumerate(window_specs):
        # --- Train: 모든 combo 백테스트 ---
        best_metric = -np.inf
        best_combo: dict[str, Any] = combos[0]
        best_train_result: BacktestResult | None = None

        for combo in combos:
            key = tuple(sorted(combo.items()))
            enriched = cache[key]
            train_df = enriched.iloc[tr_s:tr_e]

            strategy = create_strategy(strategy_name, combo)
            result = backtest(
                train_df,
                strategy,
                fee=fee,
                slippage=slippage,
                stop_loss_ratio=stop_loss_ratio,
                enable_time_exit=enable_time_exit,
            )
            metric = getattr(result, optimize_by, result.cumulative_return)
            if metric > best_metric:
                best_metric = metric
                best_combo = combo
                best_train_result = result

        # --- Test: 최적 파라미터로 검증 ---
        best_key = tuple(sorted(best_combo.items()))
        test_df = cache[best_key].iloc[te_s:te_e]
        best_strategy = create_strategy(strategy_name, best_combo)
        test_result = backtest(
            test_df,
            best_strategy,
            fee=fee,
            slippage=slippage,
            stop_loss_ratio=stop_loss_ratio,
            enable_time_exit=enable_time_exit,
        )

        assert best_train_result is not None

        windows.append(
            WalkForwardWindow(
                window_id=wid,
                train_start=_date_str(df.index[tr_s]),
                train_end=_date_str(df.index[tr_e - 1]),
                test_start=_date_str(df.index[te_s]),
                test_end=_date_str(df.index[te_e - 1]),
                best_params=best_combo,
                train_return=best_train_result.cumulative_return,
                test_return=test_result.cumulative_return,
                test_benchmark=test_result.benchmark_return,
                test_excess=test_result.excess_return,
                test_mdd=test_result.mdd,
                test_trades=test_result.n_trades,
                test_sharpe=test_result.sharpe_ratio,
            )
        )

    # --- 요약 통계 ---
    n_w = len(windows)
    avg_train = np.mean([w.train_return for w in windows])
    avg_test = np.mean([w.test_return for w in windows])
    avg_bench = np.mean([w.test_benchmark for w in windows])
    avg_excess = np.mean([w.test_excess for w in windows])
    pos_excess_count = sum(1 for w in windows if w.test_excess > 0)
    pos_excess_ratio = pos_excess_count / n_w

    if avg_test != 0.0:
        ratio = abs(avg_train / avg_test)
        if not np.isfinite(ratio):
            ratio = 99.99
        ratio = min(ratio, 99.99)
    else:
        ratio = 0.0

    return WalkForwardResult(
        strategy_name=strategy_name,
        param_grid=param_grid,
        n_windows=n_w,
        avg_train_return=float(avg_train),
        avg_test_return=float(avg_test),
        avg_test_benchmark=float(avg_bench),
        avg_test_excess=float(avg_excess),
        positive_excess_ratio=float(pos_excess_ratio),
        train_test_ratio=float(ratio),
        windows=windows,
    )


# ---------------------------------------------------------------------------
# 리포트
# ---------------------------------------------------------------------------


def _abbrev_params(params: dict[str, Any], grid: dict[str, list | Any]) -> str:
    """sweep 대상 파라미터만 축약 표시."""
    sweep_keys = [k for k in sorted(grid.keys()) if isinstance(grid[k], list)]
    if not sweep_keys:
        return "-"
    parts = []
    for k in sweep_keys:
        abbr = k[:5]
        v = params.get(k, "?")
        if isinstance(v, float):
            parts.append(f"{abbr}={v:.2f}")
        else:
            parts.append(f"{abbr}={v}")
    return ", ".join(parts)


def report(result: WalkForwardResult) -> str:
    """Walk-forward 결과를 ASCII 테이블로 포맷."""
    sep = "═" * 80
    thin = "───"

    lines: list[str] = [
        sep,
        f"  WALK-FORWARD REPORT: {result.strategy_name}",
        f"  Windows: {result.n_windows}",
        sep,
        "",
    ]

    if not result.windows:
        lines.append("  (윈도우 없음 — 데이터 부족 또는 파라미터 그리드 비어있음)")
        lines.append(sep)
        return "\n".join(lines)

    # 테이블 헤더
    hdr = (
        f"  {'#':>3}  "
        f"{'Train Period':<22}  "
        f"{'Test Period':<22}  "
        f"{'Params':<14}  "
        f"{'Train':>8}  "
        f"{'Test':>8}  "
        f"{'BnH':>8}  "
        f"{'Excess':>8}  "
        f"{'Trades':>6}"
    )
    lines.append(hdr)
    lines.append(
        f"  {thin}  "
        f"{'─' * 22}  "
        f"{'─' * 22}  "
        f"{'─' * 14}  "
        f"{'─' * 8}  "
        f"{'─' * 8}  "
        f"{'─' * 8}  "
        f"{'─' * 8}  "
        f"{'─' * 6}"
    )

    for w in result.windows:
        train_period = f"{w.train_start} → {w.train_end[5:]}"
        test_period = f"{w.test_start} → {w.test_end[5:]}"
        params_str = _abbrev_params(w.best_params, result.param_grid)

        lines.append(
            f"  {w.window_id + 1:>3}  "
            f"{train_period:<22}  "
            f"{test_period:<22}  "
            f"{params_str:<14}  "
            f"{w.train_return * 100:>+7.1f}%  "
            f"{w.test_return * 100:>+7.1f}%  "
            f"{w.test_benchmark * 100:>+7.1f}%  "
            f"{w.test_excess * 100:>+7.1f}%  "
            f"{w.test_trades:>6}"
        )

    # 요약
    lines.append("")
    lines.append(sep)
    lines.append("  SUMMARY")
    lines.append(sep)
    lines.append(f"  Avg Train Return     :  {result.avg_train_return * 100:+.2f}%")
    lines.append(f"  Avg Test Return      :  {result.avg_test_return * 100:+.2f}%")
    lines.append(f"  Avg BnH (test)       :  {result.avg_test_benchmark * 100:+.2f}%")
    lines.append(f"  Avg Excess Return    :  {result.avg_test_excess * 100:+.2f}%")

    pos_count = sum(1 for w in result.windows if w.test_excess > 0)
    total = result.n_windows
    pct = result.positive_excess_ratio * 100
    lines.append(f"  Positive Excess %    :  {pct:.0f}%  ({pos_count}/{total})")

    ratio = result.train_test_ratio
    if ratio < 2:
        verdict = "안정적"
    elif ratio <= 3:
        verdict = "주의"
    else:
        verdict = "과적합 의심"
    lines.append(f"  Train/Test Ratio     :  {ratio:.2f}  ← {verdict}")
    lines.append(sep)

    # 종합 판정
    if result.positive_excess_ratio >= 0.5 and result.avg_test_excess > 0:
        lines.append("  → 시장 대비 양의 알파 가능성")
    elif result.positive_excess_ratio < 0.4 or result.avg_test_excess <= 0:
        lines.append("  → 시장 대비 알파 부재")
    else:
        lines.append("  → 결과 혼재 — 추가 검증 필요")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cli(argv: list[str] | None = None) -> int:
    """Walk-forward 검증 CLI."""
    p = argparse.ArgumentParser(
        prog="auto-coin-walk-forward",
        description="Walk-forward validation on Upbit daily candles.",
    )
    p.add_argument("--strategy", required=True, choices=list(STRATEGY_REGISTRY.keys()))
    p.add_argument("--ticker", default="KRW-BTC")
    p.add_argument("--days", type=int, default=730, help="Total candles to fetch")
    p.add_argument("--train-days", type=int, default=180)
    p.add_argument("--test-days", type=int, default=30)
    p.add_argument("--fee", type=float, default=UPBIT_DEFAULT_FEE)
    p.add_argument("--slippage", type=float, default=DEFAULT_SLIPPAGE)
    p.add_argument("--stop-loss", type=float, default=None)
    p.add_argument("--enable-time-exit", action="store_true")
    p.add_argument(
        "--optimize-by",
        default="cumulative_return",
        choices=["cumulative_return", "sharpe_ratio"],
    )
    p.add_argument(
        "--param-grid",
        type=str,
        default=None,
        help='JSON param grid, e.g. \'{"k": [0.3, 0.5, 0.7]}\'',
    )
    args = p.parse_args(argv)

    # Fetch candles
    raw = pyupbit.get_ohlcv(args.ticker, interval="day", count=args.days)
    if raw is None or raw.empty:
        print(f"ERROR: no candles for {args.ticker}", file=sys.stderr)
        return 1

    grid = json.loads(args.param_grid) if args.param_grid else None

    result = walk_forward(
        raw,
        args.strategy,
        grid,
        train_days=args.train_days,
        test_days=args.test_days,
        fee=args.fee,
        slippage=args.slippage,
        stop_loss_ratio=args.stop_loss,
        enable_time_exit=args.enable_time_exit,
        optimize_by=args.optimize_by,
    )

    print(f"# {args.ticker}  strategy={args.strategy}  total_candles={len(raw)}")
    print(report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())

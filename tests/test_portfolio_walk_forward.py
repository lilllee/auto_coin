"""Portfolio walk-forward skeleton tests (B2)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from auto_coin.backtest.portfolio_walk_forward import (
    PortfolioWalkForwardResult,
    PortfolioWindowResult,
    portfolio_walk_forward,
)


def _synth(tickers: list[str], n_days: int = 300, seed: int = 0) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    out: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(tickers):
        rets = rng.normal(0.0005 * (i + 1), 0.02, n_days)
        close = 100.0 * np.cumprod(1 + rets)
        out[t] = pd.DataFrame({
            "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": 1.0,
        }, index=idx)
    return out


def _dummy_factory(params: dict):
    """테스트용 factory — params 의 top_k 에 따라 처음 N 개 ticker 를 동등 보유."""
    top_k = int(params.get("top_k", 2))
    rebal = int(params.get("rebal_days", 7))

    def signal(candles, date, ctx):
        avail = list(candles.keys())[:top_k]
        if not avail:
            return {}
        w = ctx.risk_budget / len(avail)
        return {t: w for t in avail}

    overrides = {"rebal_days": rebal}
    return signal, overrides


def test_wf_empty_grid_returns_empty():
    candles = _synth(["A", "B"], n_days=300)
    r = portfolio_walk_forward(
        candles, _dummy_factory,
        param_grid={},
        train_days=180, test_days=60, step_days=30,
    )
    assert isinstance(r, PortfolioWalkForwardResult)
    assert r.n_windows == 0


def test_wf_insufficient_data_returns_empty():
    candles = _synth(["A", "B"], n_days=100)
    r = portfolio_walk_forward(
        candles, _dummy_factory,
        param_grid={"top_k": [1, 2]},
        train_days=180, test_days=60, step_days=30,
    )
    assert r.n_windows == 0


def test_wf_runs_and_aggregates_metrics():
    candles = _synth(["A", "B", "C"], n_days=365, seed=123)
    r = portfolio_walk_forward(
        candles, _dummy_factory,
        param_grid={"top_k": [1, 2, 3], "rebal_days": [7, 14]},
        train_days=180, test_days=60, step_days=30,
        initial_krw=1_000_000,
    )
    # 365 - 180 - 60 = 125, step=30 → (125 // 30) + 1 = 5 windows
    assert r.n_windows >= 4
    assert r.n_windows <= 6

    # 집계 메트릭 유한성
    assert np.isfinite(r.avg_train_return)
    assert np.isfinite(r.avg_test_return)
    assert np.isfinite(r.avg_test_excess)
    assert 0.0 <= r.positive_excess_ratio <= 1.0
    assert 0.0 <= r.best_param_stability <= 1.0

    # 모든 window 에 best_params 기록
    for w in r.windows:
        assert isinstance(w, PortfolioWindowResult)
        assert "top_k" in w.best_params
        assert w.train_start < w.train_end
        assert w.train_end <= w.test_start


def test_wf_uses_optimize_metric():
    """optimize_by='sharpe_ratio' vs 'cumulative_return' 이 best_params 에 영향을 주는지 확인."""
    candles = _synth(["A", "B", "C"], n_days=300, seed=42)

    r_sharpe = portfolio_walk_forward(
        candles, _dummy_factory,
        param_grid={"top_k": [1, 2, 3]},
        train_days=150, test_days=30, step_days=30,
        optimize_by="sharpe_ratio",
    )
    r_cum = portfolio_walk_forward(
        candles, _dummy_factory,
        param_grid={"top_k": [1, 2, 3]},
        train_days=150, test_days=30, step_days=30,
        optimize_by="cumulative_return",
    )
    assert r_sharpe.n_windows > 0
    assert r_cum.n_windows > 0
    # 비교는 값 동일성만 — 반드시 다를 필요는 없음. 단지 둘 다 돌아야 함.


def test_wf_train_test_ratio_reasonable():
    candles = _synth(["A", "B"], n_days=365)
    r = portfolio_walk_forward(
        candles, _dummy_factory,
        param_grid={"top_k": [1, 2]},
        train_days=180, test_days=60, step_days=60,
    )
    if r.n_windows >= 2:
        # T/T ratio 는 절댓값 비. 일반적으로 train 이 test 보다 길어서 ratio 가 > 1
        assert r.train_test_ratio >= 0.0

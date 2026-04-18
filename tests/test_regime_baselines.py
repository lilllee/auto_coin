"""Regime-only baseline signal tests (B5)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.backtest.portfolio_runner import (
    PortfolioContext,
    portfolio_backtest,
)
from auto_coin.strategy.portfolio.baselines import (
    RegimeBaselineParams,
    make_regime_baseline_signal,
    regime_baseline_factory_btc,
    regime_baseline_factory_equal,
)


def _monotone(n: int, start: float, daily_ret: float) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    close = start * np.cumprod(np.full(n, 1 + daily_ret))
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1.0,
    }, index=idx)


def test_params_validation():
    with pytest.raises(ValueError):
        RegimeBaselineParams(mode="bogus").validate()
    with pytest.raises(ValueError):
        RegimeBaselineParams(regime_ma_window=1).validate()
    RegimeBaselineParams().validate()  # defaults ok


def test_equal_weight_regime_on_allocates_to_all():
    candles = {
        "KRW-BTC": _monotone(150, 100, 0.005),
        "KRW-ETH": _monotone(150, 100, 0.003),
        "KRW-XRP": _monotone(150, 100, -0.001),  # 음수 momentum 이어도 baseline 은 포함
    }
    params = RegimeBaselineParams(mode="equal_weight", regime_ma_window=50)
    ctx = PortfolioContext(risk_budget=0.9)
    signal = make_regime_baseline_signal(params)

    w = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    # regime ON (BTC 상승세) → 3 ticker 균등 = 0.9/3 = 0.3
    assert set(w.keys()) == {"KRW-BTC", "KRW-ETH", "KRW-XRP"}
    for val in w.values():
        assert val == pytest.approx(0.3)


def test_equal_weight_regime_off_returns_empty():
    candles = {
        "KRW-BTC": _monotone(150, 100, -0.01),   # 하락세 → regime off
        "KRW-ETH": _monotone(150, 100, 0.005),
    }
    params = RegimeBaselineParams(mode="equal_weight", regime_ma_window=50)
    ctx = PortfolioContext(risk_budget=0.9)
    signal = make_regime_baseline_signal(params)

    w = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert w == {}


def test_btc_only_regime_on_allocates_to_btc():
    candles = {
        "KRW-BTC": _monotone(150, 100, 0.005),
        "KRW-ETH": _monotone(150, 100, 0.01),    # ETH 가 더 강해도 무시
    }
    params = RegimeBaselineParams(mode="btc_only", regime_ma_window=50)
    ctx = PortfolioContext(risk_budget=0.7)
    signal = make_regime_baseline_signal(params)

    w = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert w == {"KRW-BTC": pytest.approx(0.7)}


def test_btc_only_regime_off_returns_empty():
    candles = {
        "KRW-BTC": _monotone(150, 100, -0.01),
        "KRW-ETH": _monotone(150, 100, 0.01),
    }
    params = RegimeBaselineParams(mode="btc_only", regime_ma_window=50)
    ctx = PortfolioContext(risk_budget=0.7)
    signal = make_regime_baseline_signal(params)

    w = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert w == {}


def test_factory_equal_returns_signal_and_overrides():
    signal, overrides = regime_baseline_factory_equal({
        "regime_ma_window": 150,
        "rebal_days": 14,
    })
    assert callable(signal)
    assert overrides == {"rebal_days": 14}


def test_factory_btc_returns_signal_and_overrides():
    signal, overrides = regime_baseline_factory_btc({
        "regime_ma_window": 50,
        "rebal_days": 7,
    })
    assert callable(signal)
    assert overrides == {"rebal_days": 7}


def test_equal_weight_runs_through_portfolio_backtest():
    candles = {
        "KRW-BTC": _monotone(220, 100, 0.003),
        "KRW-ETH": _monotone(220, 100, 0.002),
        "KRW-XRP": _monotone(220, 100, 0.001),
    }
    params = RegimeBaselineParams(mode="equal_weight", regime_ma_window=60)
    ctx = PortfolioContext(rebal_days=14, risk_budget=0.8)
    signal = make_regime_baseline_signal(params)

    r = portfolio_backtest(candles, signal, context=ctx, initial_krw=1_000_000)
    assert r.n_rebalances >= 1
    assert r.n_trades > 0
    # baseline 은 cross-sectional 선택이 없으므로 universe 전원 편입
    last_ev = r.rebalance_events[-1]
    assert set(last_ev.realized_weights.keys()) == {"KRW-BTC", "KRW-ETH", "KRW-XRP"}

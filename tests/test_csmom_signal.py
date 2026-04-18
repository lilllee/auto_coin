"""CSMOM v1 signal tests (B3)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.backtest.portfolio_runner import (
    PortfolioContext,
    portfolio_backtest,
)
from auto_coin.strategy.portfolio.csmom import (
    CsmomParams,
    _is_risk_on,
    _momentum_score,
    _rank_top_k,
    csmom_factory,
    make_csmom_signal,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _monotone_df(n_days: int, start: float, daily_ret: float) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    close = start * np.cumprod(np.full(n_days, 1 + daily_ret))
    return pd.DataFrame({
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1.0,
    }, index=idx)


def _synth(
    specs: dict[str, float],
    n_days: int = 120,
    start: float = 100.0,
) -> dict[str, pd.DataFrame]:
    return {t: _monotone_df(n_days, start, r) for t, r in specs.items()}


# ---------------------------------------------------------------------------
# Params validation
# ---------------------------------------------------------------------------


def test_params_validation_rejects_bad_values():
    with pytest.raises(ValueError):
        CsmomParams(lookback_days=1).validate()
    with pytest.raises(ValueError):
        CsmomParams(top_k=0).validate()
    with pytest.raises(ValueError):
        CsmomParams(regime_ma_window=1).validate()


def test_params_defaults_are_sensible():
    p = CsmomParams()
    p.validate()
    assert p.lookback_days == 60
    assert p.top_k == 3
    assert p.regime_enabled is True
    assert p.regime_ticker == "KRW-BTC"
    assert p.regime_ma_window == 100


# ---------------------------------------------------------------------------
# Momentum score helper
# ---------------------------------------------------------------------------


def test_momentum_score_monotone_uptrend():
    df = _monotone_df(70, 100.0, 0.01)
    s = _momentum_score(df, 60)
    assert s is not None
    assert s > 0
    # 60일 × 1% 복리 ≈ 1.01^60 - 1 ≈ 0.817
    assert s == pytest.approx((1.01 ** 60) - 1, rel=1e-6)


def test_momentum_score_insufficient_data_returns_none():
    df = _monotone_df(50, 100.0, 0.01)
    assert _momentum_score(df, 60) is None


def test_momentum_score_empty_df_returns_none():
    assert _momentum_score(pd.DataFrame(), 60) is None


# ---------------------------------------------------------------------------
# Rank top-K
# ---------------------------------------------------------------------------


def test_rank_top_k_basic():
    scores = {"A": 0.1, "B": 0.3, "C": 0.2, "D": -0.05}
    top = _rank_top_k(scores, 2)
    assert top == ["B", "C"]


def test_rank_top_k_handles_ties():
    scores = {"A": 0.1, "B": 0.1, "C": 0.2}
    top = _rank_top_k(scores, 2)
    assert top[0] == "C"
    # 동점 A/B 는 알파벳 순
    assert top[1] == "A"


def test_rank_top_k_k_larger_than_n():
    scores = {"A": 0.1, "B": 0.2}
    assert _rank_top_k(scores, 5) == ["B", "A"]


# ---------------------------------------------------------------------------
# Regime filter
# ---------------------------------------------------------------------------


def test_regime_on_when_uptrend():
    # 100d 우상향 → 마지막 close > SMA100 → risk-on
    candles = {"KRW-BTC": _monotone_df(150, 100.0, 0.005)}
    p = CsmomParams(regime_ma_window=100, regime_ticker="KRW-BTC")
    assert _is_risk_on(candles, p) is True


def test_regime_off_when_downtrend():
    # 150일 우하향 → 최근 close < SMA100
    candles = {"KRW-BTC": _monotone_df(150, 100.0, -0.005)}
    p = CsmomParams(regime_ma_window=100, regime_ticker="KRW-BTC")
    assert _is_risk_on(candles, p) is False


def test_regime_disabled_always_on():
    candles = {"KRW-BTC": _monotone_df(150, 100.0, -0.01)}
    p = CsmomParams(regime_enabled=False)
    assert _is_risk_on(candles, p) is True


def test_regime_missing_ticker_is_risk_off():
    """regime_ticker 데이터가 없으면 안전을 위해 risk-off."""
    candles = {"KRW-ETH": _monotone_df(150, 100.0, 0.01)}
    p = CsmomParams(regime_ticker="KRW-BTC", regime_ma_window=50)
    assert _is_risk_on(candles, p) is False


def test_regime_insufficient_data_is_risk_off():
    candles = {"KRW-BTC": _monotone_df(50, 100.0, 0.01)}  # < 100 + 1
    p = CsmomParams(regime_ma_window=100)
    assert _is_risk_on(candles, p) is False


# ---------------------------------------------------------------------------
# Signal behavior
# ---------------------------------------------------------------------------


def test_signal_picks_highest_momentum():
    """BTC 는 우상향(regime-on), ETH/XRP/SOL 중 SOL 이 가장 강한 momentum."""
    candles = _synth({
        "KRW-BTC": 0.005,
        "KRW-ETH": 0.002,
        "KRW-XRP": 0.001,
        "KRW-SOL": 0.010,   # 가장 강함
    }, n_days=150)
    params = CsmomParams(lookback_days=60, top_k=2, regime_ma_window=100)
    ctx = PortfolioContext(risk_budget=0.8, hold_N=3)
    signal = make_csmom_signal(params)

    weights = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert "KRW-SOL" in weights
    # SOL 다음으로 강한 BTC (BTC 자체도 momentum score 가 있음)
    # top_k=2 이므로 2 종목만
    assert len(weights) == 2
    # equal weight × risk_budget = 0.8 / 2 = 0.4 each
    for w in weights.values():
        assert w == pytest.approx(0.4)


def test_signal_regime_off_returns_empty():
    """BTC 가 하락세라 regime-off → 다른 ticker 가 강해도 전원 flat."""
    candles = _synth({
        "KRW-BTC": -0.010,   # 강한 하락 → regime off
        "KRW-ETH": 0.005,    # ETH 는 강해도 무시
        "KRW-XRP": 0.003,
    }, n_days=150)
    params = CsmomParams(lookback_days=60, top_k=2, regime_ma_window=100)
    ctx = PortfolioContext(risk_budget=0.8)
    signal = make_csmom_signal(params)

    weights = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert weights == {}


def test_signal_excludes_negative_momentum():
    """양(+) momentum 만 후보. 모두 음수면 전원 flat."""
    candles = _synth({
        "KRW-BTC": 0.005,     # regime-on 용
        "KRW-A": -0.001,
        "KRW-B": -0.002,
        "KRW-C": -0.0005,
    }, n_days=150)
    params = CsmomParams(
        lookback_days=60, top_k=3, regime_ma_window=100,
        regime_ticker="KRW-BTC",
    )
    ctx = PortfolioContext()
    signal = make_csmom_signal(params)

    weights = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    # BTC 자체는 양수 momentum 이므로 포함
    assert "KRW-BTC" in weights
    # 나머지 A/B/C 는 음수 momentum → 제외
    for t in ("KRW-A", "KRW-B", "KRW-C"):
        assert t not in weights


def test_signal_respects_top_k():
    """5개 중 2개만 보유 (top_k=2)."""
    candles = _synth({
        "KRW-BTC": 0.005,
        "KRW-A": 0.001,
        "KRW-B": 0.004,
        "KRW-C": 0.002,
        "KRW-D": 0.003,
    }, n_days=150)
    params = CsmomParams(lookback_days=60, top_k=2, regime_ma_window=100)
    ctx = PortfolioContext(hold_N=5)  # hold_N 이 크더라도 top_k 에 의해 2로 제한
    signal = make_csmom_signal(params)

    weights = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert len(weights) == 2
    # 가장 강한 둘: BTC(0.005), B(0.004)
    assert set(weights.keys()) == {"KRW-BTC", "KRW-B"}


def test_signal_context_hold_N_truncates_top_k():
    """ctx.hold_N 이 params.top_k 보다 작으면 min 이 적용된다."""
    candles = _synth({
        "KRW-BTC": 0.005, "KRW-A": 0.004, "KRW-B": 0.003, "KRW-C": 0.002,
    }, n_days=150)
    params = CsmomParams(lookback_days=60, top_k=4, regime_ma_window=100)
    ctx = PortfolioContext(hold_N=2)  # 2 로 제한
    signal = make_csmom_signal(params)

    weights = signal(candles, candles["KRW-BTC"].index[-1], ctx)
    assert len(weights) == 2


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_signal_and_context_overrides():
    """csmom_factory(params_dict) → (signal, overrides). Context 쪽 key 는 분리."""
    signal, overrides = csmom_factory({
        "lookback_days": 45,
        "top_k": 2,
        "rebal_days": 5,
        "regime_ma_window": 80,
    })
    assert callable(signal)
    assert overrides == {"rebal_days": 5, "lookback_days": 45}


def test_factory_validates_params():
    with pytest.raises(ValueError):
        csmom_factory({"lookback_days": 0})


# ---------------------------------------------------------------------------
# Integration with portfolio_backtest
# ---------------------------------------------------------------------------


def test_csmom_runs_through_portfolio_backtest():
    """크래시 없이 end-to-end 실행되는지만 확인."""
    candles = _synth({
        "KRW-BTC": 0.004,
        "KRW-ETH": 0.003,
        "KRW-XRP": -0.001,
        "KRW-SOL": 0.005,
        "KRW-DOGE": 0.002,
    }, n_days=200)
    params = CsmomParams(lookback_days=60, top_k=3, regime_ma_window=100)
    ctx = PortfolioContext(
        rebal_days=7, risk_budget=0.8, hold_N=3,
        active_strategy_group="csmom_v1",
    )
    signal = make_csmom_signal(params)

    r = portfolio_backtest(candles, signal, context=ctx, initial_krw=1_000_000)
    assert r.n_rebalances > 0
    assert r.n_trades > 0
    assert len(r.equity_curve) == 200
    assert len(r.benchmark_curve) == 200


def test_csmom_rank_rotation_happens_when_leaders_swap():
    """앞쪽 구간은 A 가 강한 momentum, 뒷쪽 구간은 B 가 강한 momentum.

    전환 경계는 60일 lookback 이 leader 를 바꾸는 지점. 작은 regime_ma_window(=30)
    로 빨리 risk-on 진입해 초반 A leader 구간을 확보한다.
    """
    n = 220
    # A: 앞 120일 강한 상승 → 뒤 100일 하락
    close_a = np.concatenate([
        np.linspace(100, 300, 120),   # 강한 상승
        np.linspace(300, 150, 100),   # 하락
    ])
    # B: 앞 120일 횡보 → 뒤 100일 강한 상승
    close_b = np.concatenate([
        np.full(120, 100.0),
        np.linspace(100, 400, 100),
    ])
    # BTC: 지속적으로 완만한 상승 (regime-on 초반부터 유지)
    close_btc = np.linspace(100, 180, n)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")

    def _df(close_arr):
        return pd.DataFrame({
            "open": close_arr, "high": close_arr * 1.01, "low": close_arr * 0.99,
            "close": close_arr, "volume": 1.0,
        }, index=idx)

    candles = {"KRW-A": _df(close_a), "KRW-B": _df(close_b), "KRW-BTC": _df(close_btc)}
    # 작은 regime_ma_window 로 초반부터 risk-on 진입
    params = CsmomParams(lookback_days=60, top_k=1, regime_ma_window=30,
                         regime_ticker="KRW-BTC")
    ctx = PortfolioContext(rebal_days=14, risk_budget=0.6, hold_N=1)
    signal = make_csmom_signal(params)

    r = portfolio_backtest(candles, signal, context=ctx, initial_krw=1_000_000)

    # 최소 rebal 수 (220일 / 14 ≈ 15)
    assert len(r.rebalance_events) >= 5
    leaders: list[str] = []
    for ev in r.rebalance_events:
        if ev.realized_weights:
            leader = max(ev.realized_weights.items(), key=lambda kv: kv[1])[0]
            leaders.append(leader)
    # 둘 다 등장해야 rotation 이 일어났다는 증거
    assert "KRW-A" in leaders, f"leaders={leaders}"
    assert "KRW-B" in leaders, f"leaders={leaders}"

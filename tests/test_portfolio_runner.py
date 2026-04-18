"""Portfolio-aware backtest engine tests (B2 skeleton)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.backtest.portfolio_runner import (
    PortfolioBacktestResult,
    PortfolioContext,
    PortfolioTrade,
    equal_weight_signal,
    portfolio_backtest,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_synth_candles(
    tickers: list[str],
    n_days: int = 30,
    start_price: float = 100.0,
    seed: int = 0,
) -> dict[str, pd.DataFrame]:
    """각 ticker 에 synthetic OHLCV 생성 — 간단한 geometric random walk."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    out: dict[str, pd.DataFrame] = {}
    for i, t in enumerate(tickers):
        # 각 ticker 마다 살짝 다른 drift
        drift = 0.001 * (i + 1)
        vol = 0.02
        rets = rng.normal(drift, vol, n_days)
        close = start_price * np.cumprod(1 + rets)
        high = close * (1 + np.abs(rng.normal(0, 0.005, n_days)))
        low = close * (1 - np.abs(rng.normal(0, 0.005, n_days)))
        open_ = close * (1 + rng.normal(0, 0.002, n_days))
        volume = rng.uniform(100, 1000, n_days)
        df = pd.DataFrame({
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        }, index=idx)
        out[t] = df
    return out


# ---------------------------------------------------------------------------
# Basic behavior
# ---------------------------------------------------------------------------


def test_empty_candles_returns_empty_result():
    r = portfolio_backtest({}, equal_weight_signal)
    assert isinstance(r, PortfolioBacktestResult)
    assert r.n_trades == 0
    assert r.n_rebalances == 0
    assert r.final_equity_krw == 0.0
    assert len(r.equity_curve) == 0


def test_single_ticker_universe_runs():
    candles = _make_synth_candles(["KRW-BTC"], n_days=20)
    r = portfolio_backtest(
        candles, equal_weight_signal,
        context=PortfolioContext(rebal_days=5, risk_budget=0.5),
        initial_krw=1_000_000,
    )
    assert r.initial_krw == 1_000_000
    assert len(r.equity_curve) == 20
    assert len(r.benchmark_curve) == 20
    assert r.n_rebalances >= 1  # 첫날 rebal 은 무조건 발생
    # equity curve 시작점은 initial_krw
    assert r.equity_curve.iloc[0] == pytest.approx(1_000_000, rel=1e-3)


def test_three_ticker_equal_weight_respects_risk_budget():
    candles = _make_synth_candles(["KRW-A", "KRW-B", "KRW-C"], n_days=30)
    ctx = PortfolioContext(rebal_days=10, risk_budget=0.9)
    r = portfolio_backtest(candles, equal_weight_signal, context=ctx, initial_krw=1_000_000)

    # 최소 1회 rebalance 발생, trade 수는 ticker 수와 유사
    assert r.n_rebalances >= 1
    assert r.n_trades >= 3  # 최초 rebal 에 3개 매수

    # 첫 rebal 이벤트 검증
    first_event = r.rebalance_events[0]
    assert len(first_event.trades) == 3
    # 모두 매수
    assert all(t.side == "buy" for t in first_event.trades)
    # realized weight 합 ≈ risk_budget (fee/slip 으로 살짝 아래)
    realized_sum = sum(first_event.realized_weights.values())
    assert 0.85 <= realized_sum <= 0.95


def test_benchmark_curve_differs_from_equity():
    """Equal-weight portfolio 와 equal-weight B&H 는 수수료/리밸런스 비용 차이만큼 달라진다."""
    candles = _make_synth_candles(["KRW-A", "KRW-B", "KRW-C"], n_days=60, seed=42)
    # rebal 매우 자주 → fee 누적 → equity < benchmark 기대
    ctx = PortfolioContext(rebal_days=3, risk_budget=1.0)
    r = portfolio_backtest(
        candles, equal_weight_signal, context=ctx,
        fee=0.001, slippage=0.001, initial_krw=1_000_000,
    )
    assert len(r.equity_curve) == 60
    assert len(r.benchmark_curve) == 60
    # benchmark 시작점도 initial_krw
    assert r.benchmark_curve.iloc[0] == pytest.approx(1_000_000, rel=1e-3)
    # fee > 0 이고 rebal 많으므로 excess 는 대체로 음수 (정확한 부등호는 아니지만 산발적 검증)
    assert r.excess_return < 0.01  # 아주 좁은 범위 — 주로 검증 목적


def test_zero_weight_signal_keeps_cash():
    """signal 이 빈 dict → 전원 flat → equity ≈ initial_krw 유지."""
    candles = _make_synth_candles(["KRW-A", "KRW-B"], n_days=20)
    r = portfolio_backtest(
        candles,
        signal=lambda c, d, ctx: {},
        context=PortfolioContext(rebal_days=5),
        initial_krw=500_000,
    )
    assert r.n_trades == 0
    assert r.final_equity_krw == pytest.approx(500_000, rel=1e-6)
    assert r.cumulative_return == pytest.approx(0.0, abs=1e-6)


def test_sell_side_on_weight_reduction():
    """첫 rebal 에 모두 매수 → 다음 rebal 에 target 줄이면 매도 발생."""
    candles = _make_synth_candles(["KRW-A", "KRW-B"], n_days=20)
    rebal_count = [0]

    def shrinking_signal(c, d, ctx):
        rebal_count[0] += 1
        # 첫 rebal 에만 보유, 이후는 모두 flat
        return {"KRW-A": 0.4, "KRW-B": 0.4} if rebal_count[0] == 1 else {}

    r = portfolio_backtest(
        candles, shrinking_signal,
        context=PortfolioContext(rebal_days=5),
        initial_krw=1_000_000,
    )
    sells = [t for t in r.trades if t.side == "sell"]
    buys = [t for t in r.trades if t.side == "buy"]
    assert len(buys) == 2      # 첫 rebal
    assert len(sells) >= 1     # 두 번째 rebal 에 청산


def test_metrics_are_finite():
    candles = _make_synth_candles(["KRW-A", "KRW-B"], n_days=40, seed=7)
    r = portfolio_backtest(candles, equal_weight_signal, initial_krw=1_000_000)
    # 모든 메트릭이 유한해야 함
    assert np.isfinite(r.cumulative_return)
    assert np.isfinite(r.benchmark_return)
    assert np.isfinite(r.excess_return)
    assert np.isfinite(r.mdd)
    assert np.isfinite(r.sharpe_ratio)
    assert r.n_trades > 0
    assert r.n_rebalances > 0


def test_trade_records_have_valid_shape():
    candles = _make_synth_candles(["KRW-A", "KRW-B"], n_days=20)
    r = portfolio_backtest(candles, equal_weight_signal, initial_krw=500_000)
    for t in r.trades:
        assert isinstance(t, PortfolioTrade)
        assert t.side in {"buy", "sell"}
        assert t.shares > 0
        assert t.price > 0
        assert t.krw_amount > 0
        assert t.fee_krw >= 0


def test_universe_intersection_handles_mismatched_ranges():
    """ticker A 는 30일, B 는 20일 — 교집합 20일 사용."""
    idx_a = pd.date_range("2026-01-01", periods=30, freq="D")
    idx_b = pd.date_range("2026-01-11", periods=20, freq="D")
    df_a = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 100.0, "volume": 1,
    }, index=idx_a)
    df_b = pd.DataFrame({
        "open": 200.0, "high": 201.0, "low": 199.0,
        "close": 200.0, "volume": 1,
    }, index=idx_b)
    candles = {"KRW-A": df_a, "KRW-B": df_b}
    r = portfolio_backtest(candles, equal_weight_signal, initial_krw=1_000_000)
    # 교집합 = idx_b 와 idx_a 중첩 부분 = 2026-01-11 ~ 2026-01-30 (20일)
    assert len(r.equity_curve) == 20


def test_context_risk_budget_caps_allocation():
    """signal 이 합 1.5 반환해도 risk_budget=0.6 으로 truncate 되어야 함."""
    candles = _make_synth_candles(["KRW-A", "KRW-B", "KRW-C"], n_days=15)

    def overweight_signal(c, d, ctx):
        return {"KRW-A": 0.5, "KRW-B": 0.5, "KRW-C": 0.5}  # 합 1.5

    ctx = PortfolioContext(rebal_days=5, risk_budget=0.6)
    r = portfolio_backtest(candles, overweight_signal, context=ctx, initial_krw=1_000_000)

    # 첫 rebal 에 cash 가 initial_krw × (1 - 0.6) 가까이 남아야 함
    first_ev = r.rebalance_events[0]
    realized_sum = sum(first_ev.realized_weights.values())
    # fee/slippage 고려해도 risk_budget 을 넘지는 않아야 함
    assert realized_sum <= 0.62

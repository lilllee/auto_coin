from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import enrich_daily
from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def _enriched(n: int = 10, k: float = 0.5, ma_window: int = 5) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    df = pd.DataFrame(
        {
            "open":   np.full(n, 100.0),
            "high":   np.full(n, 110.0),
            "low":    np.full(n, 90.0),
            "close":  np.full(n, 105.0),
            "volume": np.ones(n),
        },
        index=idx,
    )
    return enrich_daily(df, ma_window=ma_window, k=k)


def test_buy_when_price_above_target_and_ma():
    df = _enriched()
    # 마지막 행: target = 100 + 20*0.5 = 110, ma5 = mean of close[0..4] = 105
    s = VolatilityBreakout(k=0.5, ma_window=5)
    snap = MarketSnapshot(df=df, current_price=115.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_price_below_target():
    df = _enriched()
    s = VolatilityBreakout(k=0.5, ma_window=5)
    snap = MarketSnapshot(df=df, current_price=109.99, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_at_or_below_ma():
    df = _enriched()
    s = VolatilityBreakout(k=0.5, ma_window=5)
    # target=110 통과, ma5=105인데 current=105 (≤ ma) → HOLD
    snap = MarketSnapshot(df=df, current_price=110.0, has_position=False)
    # current_price >= target (110 >= 110) 통과, but current_price (110) > ma5 (105) → BUY
    assert s.generate_signal(snap) is Signal.BUY
    # ma 필터에 정확히 걸리는 케이스
    snap2 = MarketSnapshot(df=df, current_price=105.0, has_position=False)
    # 105 < target(110) 이므로 target에서 먼저 걸림
    assert s.generate_signal(snap2) is Signal.HOLD


def test_ma_filter_blocks_entry():
    """target은 통과하지만 ma 아래인 케이스를 강제로 만든다."""
    df = _enriched()
    # 마지막 행 ma5를 인위적으로 200으로 올려 필터를 강제 차단
    df.loc[df.index[-1], "ma5"] = 200.0
    s = VolatilityBreakout(k=0.5, ma_window=5)
    snap = MarketSnapshot(df=df, current_price=115.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_ma_filter_can_be_disabled():
    df = _enriched()
    df.loc[df.index[-1], "ma5"] = 200.0
    s = VolatilityBreakout(k=0.5, ma_window=5, require_ma_filter=False)
    snap = MarketSnapshot(df=df, current_price=115.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_already_in_position():
    df = _enriched()
    s = VolatilityBreakout(k=0.5, ma_window=5)
    snap = MarketSnapshot(df=df, current_price=999.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_target_is_nan():
    df = _enriched(n=2)  # 짧으면 ma5 NaN
    df.loc[df.index[-1], "target"] = np.nan
    s = VolatilityBreakout(k=0.5, ma_window=5)
    snap = MarketSnapshot(df=df, current_price=999.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_ma_is_nan():
    df = _enriched(n=3)  # ma5 NaN (5일 미달)
    s = VolatilityBreakout(k=0.5, ma_window=5)
    snap = MarketSnapshot(df=df, current_price=999.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_df_empty():
    s = VolatilityBreakout()
    snap = MarketSnapshot(df=pd.DataFrame(), current_price=100.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_invalid_params():
    with pytest.raises(ValueError):
        VolatilityBreakout(k=0)
    with pytest.raises(ValueError):
        VolatilityBreakout(k=1.5)
    with pytest.raises(ValueError):
        VolatilityBreakout(ma_window=0)


def test_strategy_is_pure_no_side_effects():
    """동일 입력은 동일 출력 — 호출이 df나 snapshot을 변형하지 않는다."""
    df = _enriched()
    df_snapshot = df.copy()
    s = VolatilityBreakout()
    snap = MarketSnapshot(df=df, current_price=115.0, has_position=False)
    s.generate_signal(snap)
    s.generate_signal(snap)
    pd.testing.assert_frame_equal(df, df_snapshot)

"""EMA+ADX+ATR Trend strategy unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.ema_adx_atr_trend import EmaAdxAtrTrendStrategy


def _make_df(
    ema_fast: float = 50000.0,
    ema_slow: float = 49000.0,
    adx: float = 20.0,
    ema_fast_w: int = 27,
    ema_slow_w: int = 125,
    adx_w: int = 90,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            f"ema{ema_fast_w}": [ema_fast],
            f"ema{ema_slow_w}": [ema_slow],
            f"adx{adx_w}": [adx],
        }
    )


def test_buy_when_ema_cross_and_adx_above_threshold():
    """Golden cross + ADX >= 14 -> BUY."""
    df = _make_df(ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_ema_cross_but_adx_below():
    """Golden cross but ADX < 14 -> HOLD."""
    df = _make_df(ema_fast=50000.0, ema_slow=49000.0, adx=10.0)
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_adx_above_but_no_cross():
    """ADX ok but ema_fast <= ema_slow -> HOLD."""
    df = _make_df(ema_fast=48000.0, ema_slow=49000.0, adx=20.0)
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_in_position():
    """has_position -> HOLD."""
    df = _make_df(ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_columns_missing():
    """Missing ema/adx columns -> HOLD."""
    df = pd.DataFrame(
        {
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
        }
    )
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_nan():
    """NaN values -> HOLD."""
    df = _make_df()
    df["ema27"] = np.nan
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_adx_nan():
    """ADX NaN -> HOLD."""
    df = _make_df()
    df["adx90"] = np.nan
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_df_empty():
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=pd.DataFrame(), current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_zero():
    df = _make_df()
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_negative():
    df = _make_df()
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=-1, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_when_enabled_dead_cross():
    """allow_sell_signal=True, has_position, ema_fast <= ema_slow -> SELL."""
    df = _make_df(ema_fast=48000.0, ema_slow=49000.0, adx=20.0)
    s = EmaAdxAtrTrendStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_sell_hold_when_still_golden_cross():
    """allow_sell_signal=True, holding, ema_fast > ema_slow -> HOLD (keep position)."""
    df = _make_df(ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = EmaAdxAtrTrendStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_no_sell_when_disabled():
    """allow_sell_signal=False, dead cross, has_position -> HOLD."""
    df = _make_df(ema_fast=48000.0, ema_slow=49000.0, adx=20.0)
    s = EmaAdxAtrTrendStrategy(allow_sell_signal=False)
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_buy_at_exact_threshold():
    """ADX exactly at threshold -> BUY."""
    df = _make_df(ema_fast=50000.0, ema_slow=49000.0, adx=14.0)
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_custom_params():
    s = EmaAdxAtrTrendStrategy(
        ema_fast_window=10, ema_slow_window=50, adx_window=30, adx_threshold=20.0
    )
    assert s.ema_fast_window == 10
    assert s.ema_slow_window == 50
    assert s.adx_window == 30
    assert s.adx_threshold == 20.0
    assert s.name == "ema_adx_atr_trend"

    # Use custom windows in signal generation
    df = _make_df(ema_fast=100.0, ema_slow=90.0, adx=25.0, ema_fast_w=10, ema_slow_w=50, adx_w=30)
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_invalid_params_fast_gte_slow():
    """ema_fast >= ema_slow -> ValueError."""
    with pytest.raises(ValueError, match="ema_slow_window must be > ema_fast_window"):
        EmaAdxAtrTrendStrategy(ema_fast_window=50, ema_slow_window=50)
    with pytest.raises(ValueError, match="ema_slow_window must be > ema_fast_window"):
        EmaAdxAtrTrendStrategy(ema_fast_window=100, ema_slow_window=50)


def test_invalid_params():
    with pytest.raises(ValueError, match="ema_fast_window must be >= 1"):
        EmaAdxAtrTrendStrategy(ema_fast_window=0)
    with pytest.raises(ValueError, match="adx_window must be >= 1"):
        EmaAdxAtrTrendStrategy(adx_window=0)
    with pytest.raises(ValueError, match="adx_threshold must be >= 0"):
        EmaAdxAtrTrendStrategy(adx_threshold=-1.0)


def test_purity():
    """Calling twice with the same input gives same output, df is not mutated."""
    df = _make_df(ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    df_snapshot = df.copy()
    s = EmaAdxAtrTrendStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    result1 = s.generate_signal(snap)
    result2 = s.generate_signal(snap)
    assert result1 is result2 is Signal.BUY
    pd.testing.assert_frame_equal(df, df_snapshot)

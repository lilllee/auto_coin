"""ATR Channel Breakout strategy unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.strategy.atr_channel_breakout import AtrChannelBreakoutStrategy
from auto_coin.strategy.base import MarketSnapshot, Signal


def _make_df(
    upper: float = 50000.0,
    lower: float = 48000.0,
    atr: float = 1000.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [49000.0],
            "high": [51000.0],
            "low": [48500.0],
            "close": [50000.0],
            "volume": [100.0],
            "atr14": [atr],
            "upper_channel": [upper],
            "lower_channel": [lower],
        }
    )


def test_buy_when_price_above_upper_channel():
    df = _make_df(upper=50000.0)
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=50001.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_price_below_upper_channel():
    df = _make_df(upper=50000.0)
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=49999.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_equal_upper_channel():
    """Price exactly at upper_channel boundary -> HOLD (must exceed, not equal)."""
    df = _make_df(upper=50000.0)
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=50000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_in_position():
    df = _make_df(upper=50000.0)
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=99999.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_upper_channel_nan():
    df = _make_df()
    df["upper_channel"] = np.nan
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=51000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_df_empty():
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=pd.DataFrame(), current_price=51000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_zero():
    df = _make_df(upper=50000.0)
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_negative():
    df = _make_df(upper=50000.0)
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=-1, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_when_enabled_below_lower():
    df = _make_df(upper=50000.0, lower=48000.0)
    s = AtrChannelBreakoutStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=47000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_sell_hold_when_above_lower():
    """allow_sell_signal=True, holding, but price >= lower -> HOLD (keep position)."""
    df = _make_df(upper=50000.0, lower=48000.0)
    s = AtrChannelBreakoutStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=49000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_no_sell_when_disabled():
    df = _make_df(upper=50000.0, lower=48000.0)
    s = AtrChannelBreakoutStrategy(allow_sell_signal=False)
    snap = MarketSnapshot(df=df, current_price=47000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_hold_when_lower_nan():
    """allow_sell_signal=True but lower_channel is NaN -> HOLD."""
    df = _make_df(upper=50000.0)
    df["lower_channel"] = np.nan
    s = AtrChannelBreakoutStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=40000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_custom_params():
    s = AtrChannelBreakoutStrategy(atr_window=20, channel_multiplier=2.0)
    assert s.atr_window == 20
    assert s.channel_multiplier == 2.0
    assert s.name == "atr_channel_breakout"


def test_invalid_params():
    with pytest.raises(ValueError, match="atr_window must be >= 1"):
        AtrChannelBreakoutStrategy(atr_window=0)
    with pytest.raises(ValueError, match="channel_multiplier must be > 0"):
        AtrChannelBreakoutStrategy(channel_multiplier=0)
    with pytest.raises(ValueError, match="channel_multiplier must be > 0"):
        AtrChannelBreakoutStrategy(channel_multiplier=-0.5)


def test_purity():
    """Calling twice with the same input gives same output, df is not mutated."""
    df = _make_df(upper=50000.0)
    df_snapshot = df.copy()
    s = AtrChannelBreakoutStrategy()
    snap = MarketSnapshot(df=df, current_price=50001.0, has_position=False)
    result1 = s.generate_signal(snap)
    result2 = s.generate_signal(snap)
    assert result1 is result2 is Signal.BUY
    pd.testing.assert_frame_equal(df, df_snapshot)

"""AdTurtle (개선형 Turtle) strategy unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.strategy.ad_turtle import AdTurtleStrategy
from auto_coin.strategy.base import MarketSnapshot, Signal


def _make_df(
    donchian_high: float = 51000.0,
    donchian_low: float = 48000.0,
    entry_w: int = 20,
    exit_w: int = 10,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            f"donchian_high_{entry_w}": [donchian_high],
            f"donchian_low_{exit_w}": [donchian_low],
        }
    )


def test_buy_above_donchian_high():
    df = _make_df(donchian_high=51000.0)
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=51001.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_below_donchian_high():
    df = _make_df(donchian_high=51000.0)
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=50999.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_at_boundary():
    """Price exactly at donchian_high boundary -> HOLD (must exceed, not equal)."""
    df = _make_df(donchian_high=51000.0)
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=51000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_in_position():
    df = _make_df(donchian_high=51000.0)
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=99999.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_donchian_nan():
    df = _make_df()
    df["donchian_high_20"] = np.nan
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=52000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_df_empty():
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=pd.DataFrame(), current_price=52000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_zero():
    df = _make_df(donchian_high=51000.0)
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_when_enabled_below_low():
    df = _make_df(donchian_high=51000.0, donchian_low=48000.0)
    s = AdTurtleStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=47000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_no_sell_when_disabled():
    df = _make_df(donchian_high=51000.0, donchian_low=48000.0)
    s = AdTurtleStrategy(allow_sell_signal=False)
    snap = MarketSnapshot(df=df, current_price=47000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_hold_when_above_low():
    """allow_sell_signal=True, holding, but price >= donchian_low -> HOLD."""
    df = _make_df(donchian_high=51000.0, donchian_low=48000.0)
    s = AdTurtleStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=49000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_hold_when_low_nan():
    """allow_sell_signal=True but donchian_low is NaN -> HOLD."""
    df = _make_df(donchian_high=51000.0)
    df["donchian_low_10"] = np.nan
    s = AdTurtleStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=40000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_custom_windows():
    df = _make_df(donchian_high=51000.0, donchian_low=48000.0, entry_w=30, exit_w=15)
    s = AdTurtleStrategy(entry_window=30, exit_window=15)
    assert s.entry_window == 30
    assert s.exit_window == 15
    assert s.name == "ad_turtle"
    snap = MarketSnapshot(df=df, current_price=51001.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_invalid_entry_window():
    with pytest.raises(ValueError, match="entry_window must be >= 2"):
        AdTurtleStrategy(entry_window=1)


def test_invalid_exit_window():
    with pytest.raises(ValueError, match="exit_window must be >= 1"):
        AdTurtleStrategy(exit_window=0)


def test_invalid_exit_gte_entry():
    with pytest.raises(ValueError, match="exit_window must be < entry_window"):
        AdTurtleStrategy(entry_window=10, exit_window=10)
    with pytest.raises(ValueError, match="exit_window must be < entry_window"):
        AdTurtleStrategy(entry_window=10, exit_window=15)


def test_purity():
    """Calling twice with the same input gives same output, df is not mutated."""
    df = _make_df(donchian_high=51000.0)
    df_snapshot = df.copy()
    s = AdTurtleStrategy()
    snap = MarketSnapshot(df=df, current_price=51001.0, has_position=False)
    result1 = s.generate_signal(snap)
    result2 = s.generate_signal(snap)
    assert result1 is result2 is Signal.BUY
    pd.testing.assert_frame_equal(df, df_snapshot)

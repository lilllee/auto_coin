"""SMA200 Regime strategy unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.sma200_regime import Sma200RegimeStrategy


def _make_df(sma_value: float = 50000.0, ma_window: int = 200) -> pd.DataFrame:
    """Create a minimal DataFrame with sma column."""
    df = pd.DataFrame(
        {
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            f"sma{ma_window}": [sma_value],
        }
    )
    return df


def test_buy_when_price_above_sma():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=51000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_price_below_sma():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=49000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_already_in_position():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=99999.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_sma_is_nan():
    df = _make_df(sma_value=np.nan)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=51000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_df_empty():
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=pd.DataFrame(), current_price=51000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_zero():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_buffer_pct_raises_threshold():
    """With buffer_pct=0.02, the threshold becomes sma * 1.02 = 51000."""
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy(buffer_pct=0.02)
    # 50999 < 51000 threshold → HOLD
    snap_below = MarketSnapshot(df=df, current_price=50999.0, has_position=False)
    assert s.generate_signal(snap_below) is Signal.HOLD
    # 51000 = threshold → BUY
    snap_at = MarketSnapshot(df=df, current_price=51000.0, has_position=False)
    assert s.generate_signal(snap_at) is Signal.BUY
    # 52000 > threshold → BUY
    snap_above = MarketSnapshot(df=df, current_price=52000.0, has_position=False)
    assert s.generate_signal(snap_above) is Signal.BUY


def test_sell_signal_when_enabled_and_below_sma():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=49000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_sell_signal_hold_when_above_sma():
    """allow_sell_signal=True but price >= sma → HOLD (keep position)."""
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy(allow_sell_signal=True)
    snap = MarketSnapshot(df=df, current_price=51000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_no_sell_when_disabled():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy(allow_sell_signal=False)
    snap = MarketSnapshot(df=df, current_price=49000.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_invalid_params():
    with pytest.raises(ValueError, match="ma_window must be >= 2"):
        Sma200RegimeStrategy(ma_window=1)
    with pytest.raises(ValueError, match="buffer_pct must be >= 0"):
        Sma200RegimeStrategy(buffer_pct=-0.01)


def test_purity():
    """Calling twice with the same input gives same output, df is not mutated."""
    df = _make_df(sma_value=50000.0)
    df_snapshot = df.copy()
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=51000.0, has_position=False)
    result1 = s.generate_signal(snap)
    result2 = s.generate_signal(snap)
    assert result1 is result2 is Signal.BUY
    pd.testing.assert_frame_equal(df, df_snapshot)


def test_custom_ma_window():
    """Strategy with custom ma_window=50 checks sma50 column."""
    df = pd.DataFrame(
        {
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            "sma50": [48000.0],
        }
    )
    s = Sma200RegimeStrategy(ma_window=50)
    snap = MarketSnapshot(df=df, current_price=49000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_price_negative():
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=-1, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_buy_at_exact_sma():
    """Price exactly equal to SMA (no buffer) → BUY."""
    df = _make_df(sma_value=50000.0)
    s = Sma200RegimeStrategy()
    snap = MarketSnapshot(df=df, current_price=50000.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY

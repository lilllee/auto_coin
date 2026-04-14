"""SMA200 + EMA+ADX Composite strategy unit tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.sma200_ema_adx_composite import Sma200EmaAdxCompositeStrategy


def _make_df(
    sma: float = 50000.0,
    ema_fast: float = 50000.0,
    ema_slow: float = 49000.0,
    adx: float = 20.0,
    sma_w: int = 200,
    ema_f_w: int = 27,
    ema_s_w: int = 125,
    adx_w: int = 90,
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [49000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            f"sma{sma_w}": [sma],
            f"ema{ema_f_w}": [ema_fast],
            f"ema{ema_s_w}": [ema_slow],
            f"adx{adx_w}": [adx],
        }
    )


# --- Risk-on + entry conditions met ---


def test_buy_risk_on_golden_cross_adx_ok():
    """price > sma, ema_fast > ema_slow, adx >= 14 -> BUY."""
    df = _make_df(sma=48000.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


# --- Risk-on but entry conditions NOT met ---


def test_hold_risk_on_no_cross():
    """price > sma, ema_fast <= ema_slow -> HOLD."""
    df = _make_df(sma=48000.0, ema_fast=48000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_risk_on_adx_below():
    """price > sma, cross ok, adx < 14 -> HOLD."""
    df = _make_df(sma=48000.0, ema_fast=50000.0, ema_slow=49000.0, adx=10.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_risk_on_in_position():
    """price > sma, has_position=True -> HOLD (let it ride)."""
    df = _make_df(sma=48000.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


# --- Risk-off (price < SMA200) ---


def test_sell_risk_off_with_position():
    """price < sma, has_position=True -> SELL (key behavior: close existing)."""
    df = _make_df(sma=52000.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_hold_risk_off_no_position():
    """price < sma, has_position=False -> HOLD (stay out)."""
    df = _make_df(sma=52000.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


# --- Edge cases ---


def test_hold_when_sma_nan():
    """SMA is NaN -> HOLD."""
    df = _make_df(sma=np.nan)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_ema_nan():
    """EMA fast is NaN -> HOLD."""
    df = _make_df(sma=48000.0, ema_fast=np.nan)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_ema_slow_nan():
    """EMA slow is NaN -> HOLD."""
    df = _make_df(sma=48000.0, ema_slow=np.nan)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_adx_nan():
    """ADX is NaN -> HOLD."""
    df = _make_df(sma=48000.0, adx=np.nan)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_df_empty():
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=pd.DataFrame(), current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_zero():
    df = _make_df()
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_negative():
    df = _make_df()
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=-1, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_invalid_params():
    with pytest.raises(ValueError, match="sma_window must be >= 2"):
        Sma200EmaAdxCompositeStrategy(sma_window=1)
    with pytest.raises(ValueError, match="ema_fast_window must be >= 1"):
        Sma200EmaAdxCompositeStrategy(ema_fast_window=0)
    with pytest.raises(ValueError, match="ema_slow_window must be > ema_fast_window"):
        Sma200EmaAdxCompositeStrategy(ema_fast_window=50, ema_slow_window=50)
    with pytest.raises(ValueError, match="ema_slow_window must be > ema_fast_window"):
        Sma200EmaAdxCompositeStrategy(ema_fast_window=130, ema_slow_window=50)
    with pytest.raises(ValueError, match="adx_window must be >= 1"):
        Sma200EmaAdxCompositeStrategy(adx_window=0)
    with pytest.raises(ValueError, match="adx_threshold must be >= 0"):
        Sma200EmaAdxCompositeStrategy(adx_threshold=-1.0)


def test_purity():
    """Calling twice with the same input gives same output, df is not mutated."""
    df = _make_df(sma=48000.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    df_snapshot = df.copy()
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    result1 = s.generate_signal(snap)
    result2 = s.generate_signal(snap)
    assert result1 is result2 is Signal.BUY
    pd.testing.assert_frame_equal(df, df_snapshot)


# --- Composite behavior specifics ---


def test_risk_off_overrides_entry_signal():
    """Even if EMA cross + ADX ok, price < sma -> no BUY (HOLD, not in position)."""
    df = _make_df(sma=52000.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    # Even though EMA cross and ADX are perfect for entry, SMA regime says risk-off
    assert s.generate_signal(snap) is Signal.HOLD


def test_sma_boundary_exact():
    """price == sma -> risk-on (>= check), entry logic proceeds."""
    df = _make_df(sma=50500.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    # price == sma passes the >= check, entry conditions met
    assert s.generate_signal(snap) is Signal.BUY


def test_sma_boundary_just_below():
    """price just below sma -> risk-off."""
    df = _make_df(sma=50501.0, ema_fast=50000.0, ema_slow=49000.0, adx=20.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_adx_exact_threshold():
    """ADX exactly at threshold -> BUY (>= check)."""
    df = _make_df(sma=48000.0, ema_fast=50000.0, ema_slow=49000.0, adx=14.0)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_adx_just_below_threshold():
    """ADX just below threshold -> HOLD."""
    df = _make_df(sma=48000.0, ema_fast=50000.0, ema_slow=49000.0, adx=13.9)
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_custom_params():
    """Strategy with custom parameters uses correct column names."""
    s = Sma200EmaAdxCompositeStrategy(
        sma_window=100, ema_fast_window=10, ema_slow_window=50,
        adx_window=30, adx_threshold=20.0,
    )
    assert s.sma_window == 100
    assert s.ema_fast_window == 10
    assert s.ema_slow_window == 50
    assert s.adx_window == 30
    assert s.adx_threshold == 20.0
    assert s.name == "sma200_ema_adx_composite"

    df = _make_df(
        sma=90.0, ema_fast=100.0, ema_slow=90.0, adx=25.0,
        sma_w=100, ema_f_w=10, ema_s_w=50, adx_w=30,
    )
    snap = MarketSnapshot(df=df, current_price=100.0, has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_sma_column_missing_returns_hold():
    """If sma column is entirely absent (None from .get()), HOLD."""
    df = pd.DataFrame(
        {
            "open": [49000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            "ema27": [50000.0],
            "ema125": [49000.0],
            "adx90": [20.0],
        }
    )
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_ema_columns_missing_returns_hold():
    """If EMA/ADX columns are absent but SMA passes -> HOLD."""
    df = pd.DataFrame(
        {
            "open": [49000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            "sma200": [48000.0],
        }
    )
    s = Sma200EmaAdxCompositeStrategy()
    snap = MarketSnapshot(df=df, current_price=50500.0, has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD

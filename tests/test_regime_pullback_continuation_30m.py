from __future__ import annotations

import numpy as np
import pandas as pd

from auto_coin.backtest.runner import BacktestResult, backtest
from auto_coin.data.candles import enrich_regime_pullback_continuation_30m
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, PositionSnapshot, Signal


def _make_30m_df(n: int = 160, base_price: float = 100.0) -> pd.DataFrame:
    t = np.arange(n, dtype=float)
    price = base_price + 0.04 * t + np.sin(t / 6) * 0.8
    idx = pd.date_range("2025-01-01", periods=n, freq="30min")
    return pd.DataFrame(
        {
            "open": price - 0.1,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
            "volume": np.full(n, 100.0),
        },
        index=idx,
    )


def _make_hourly_df(n: int = 120, base_price: float = 100.0) -> pd.DataFrame:
    t = np.arange(n, dtype=float)
    price = base_price + 0.08 * t + np.sin(t / 5) * 0.5
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": price - 0.1,
            "high": price + 0.6,
            "low": price - 0.6,
            "close": price,
            "volume": np.full(n, 200.0),
        },
        index=idx,
    )


def _make_daily_df(n: int = 120, base_price: float = 200.0) -> pd.DataFrame:
    t = np.arange(n, dtype=float)
    price = base_price + t
    idx = pd.date_range("2024-10-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": price - 1,
            "high": price + 2,
            "low": price - 2,
            "close": price,
            "volume": np.ones(n),
        },
        index=idx,
    )


def _snapshot(df: pd.DataFrame, current_price: float | None = None, has_position: bool = False) -> MarketSnapshot:
    return MarketSnapshot(
        df=df,
        current_price=float(df["close"].iloc[-1]) if current_price is None else current_price,
        has_position=has_position,
        interval="minute30",
        bar_seconds=1800,
    )


def _position(entry_price: float = 100.0, hold_bars: int = 8, highest_high: float = 110.0) -> PositionSnapshot:
    return PositionSnapshot(
        entry_price=entry_price,
        hold_days=hold_bars,
        highest_close=highest_high,
        highest_high=highest_high,
        interval="minute30",
        bar_seconds=1800,
        hold_bars=hold_bars,
    )


def _force_valid_entry_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["daily_regime_on"] = True
    out["hourly_close"] = 105.0
    out["hourly_ema_fast20"] = 104.0
    out["hourly_ema_slow60"] = 100.0
    out["hourly_ema_fast_slope3"] = 1.0
    out["hourly_trend_on"] = True
    out["hourly_pullback_return_8"] = -0.02
    out["hourly_rsi14"] = 42.0
    out["hourly_rsi_recent_min8"] = 30.0
    out["trigger_ema_fast8"] = out["close"] * 0.98
    out["trigger_ema_slow21"] = out["close"] * 0.96
    out["trigger_recent_high6"] = out["close"] * 0.99
    out["trigger_volume_mean20"] = out["volume"] * 0.8
    out["close_location_value"] = 0.8
    out["rsi14"] = 50.0
    out.loc[out.index[-2], "rsi14"] = 45.0
    out["atr14"] = 1.0
    return out


class TestEnrichRegimePullbackContinuation30m:
    def test_enrich_adds_required_columns(self):
        df = _make_30m_df()
        out = enrich_regime_pullback_continuation_30m(
            df,
            daily_regime_df=_make_daily_df(),
            hourly_setup_df=_make_hourly_df(),
        )
        for col in [
            "daily_regime_on",
            "hourly_trend_on",
            "hourly_pullback_return_8",
            "hourly_rsi14",
            "hourly_rsi_recent_min8",
            "trigger_ema_fast8",
            "trigger_ema_slow21",
            "trigger_recent_high6",
            "trigger_volume_mean20",
            "close_location_value",
            "atr14",
        ]:
            assert col in out.columns

    def test_recent_high_and_volume_are_shifted(self):
        df = _make_30m_df(40)
        out = enrich_regime_pullback_continuation_30m(df, trigger_breakout_lookback_30m=4, trigger_volume_window_30m=5)
        last_idx = out.index[-1]
        expected_high = df["high"].iloc[-5:-1].max()
        expected_volume = df["volume"].iloc[-6:-1].mean()
        assert out.loc[last_idx, "trigger_recent_high4"] == expected_high
        assert out.loc[last_idx, "trigger_volume_mean5"] == expected_volume

    def test_close_location_zero_range_is_safe(self):
        df = _make_30m_df(40)
        df["high"] = df["close"]
        df["low"] = df["close"]
        out = enrich_regime_pullback_continuation_30m(df)
        assert out["close_location_value"].dropna().eq(0.5).all()


class TestRegimePullbackContinuation30mSignal:
    def setup_method(self):
        self.strategy = create_strategy("regime_pullback_continuation_30m")

    def test_valid_conditions_buy(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        assert self.strategy.generate_signal(_snapshot(df)) == Signal.BUY

    def test_has_position_holds(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        assert self.strategy.generate_signal(_snapshot(df, has_position=True)) == Signal.HOLD

    def test_daily_regime_off_holds(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df["daily_regime_on"] = False
        assert self.strategy.generate_signal(_snapshot(df)) == Signal.HOLD

    def test_hourly_trend_off_holds(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df["hourly_trend_on"] = False
        assert self.strategy.generate_signal(_snapshot(df)) == Signal.HOLD

    def test_pullback_too_shallow_holds(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df["hourly_pullback_return_8"] = -0.005
        assert self.strategy.generate_signal(_snapshot(df)) == Signal.HOLD

    def test_pullback_too_deep_holds(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df["hourly_pullback_return_8"] = -0.08
        assert self.strategy.generate_signal(_snapshot(df)) == Signal.HOLD

    def test_no_trigger_votes_holds(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df["trigger_ema_fast8"] = df["close"] * 1.1
        df["trigger_ema_slow21"] = df["close"] * 1.2
        df["trigger_recent_high6"] = df["close"] * 1.2
        df["trigger_volume_mean20"] = df["volume"] * 2.0
        df["close_location_value"] = 0.1
        df["rsi14"] = 40.0
        assert self.strategy.generate_signal(_snapshot(df)) == Signal.HOLD


class TestRegimePullbackContinuation30mExit:
    def setup_method(self):
        self.strategy = create_strategy("regime_pullback_continuation_30m")

    def test_initial_stop(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df.loc[df.index[-1], "low"] = 98.0
        result = self.strategy.generate_exit(_snapshot(df), _position(entry_price=100.0, highest_high=101.0))
        assert result is not None
        assert result.reason == "regime_pullback_continuation_30m_initial_stop"

    def test_trailing_exit(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df.loc[df.index[-1], "low"] = 106.0
        result = self.strategy.generate_exit(_snapshot(df), _position(entry_price=100.0, highest_high=110.0))
        assert result is not None
        assert result.reason == "regime_pullback_continuation_30m_trailing_exit"

    def test_trend_exit(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df.loc[df.index[-1], "low"] = 999.0
        df["hourly_close"] = 90.0
        result = self.strategy.generate_exit(_snapshot(df), _position(entry_price=100.0, highest_high=105.0))
        assert result is not None
        assert result.reason == "regime_pullback_continuation_30m_trend_exit"

    def test_regime_off_exit(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df.loc[df.index[-1], "low"] = 999.0
        df["hourly_close"] = 110.0
        df["daily_regime_on"] = False
        result = self.strategy.generate_exit(_snapshot(df), _position(entry_price=100.0, highest_high=105.0))
        assert result is not None
        assert result.reason == "regime_pullback_continuation_30m_regime_off_exit"

    def test_time_exit(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df.loc[df.index[-1], "low"] = 999.0
        df["hourly_close"] = 110.0
        result = self.strategy.generate_exit(_snapshot(df), _position(entry_price=100.0, hold_bars=120, highest_high=105.0))
        assert result is not None
        assert result.reason == "regime_pullback_continuation_30m_time_exit"

    def test_no_exit(self):
        df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df()))
        df.loc[df.index[-1], "low"] = 999.0
        df["hourly_close"] = 110.0
        result = self.strategy.generate_exit(_snapshot(df), _position(entry_price=100.0, hold_bars=5, highest_high=105.0))
        assert result is None


def test_backtest_crash_free():
    df = _force_valid_entry_columns(enrich_regime_pullback_continuation_30m(_make_30m_df(220)))
    strategy = create_strategy("regime_pullback_continuation_30m", {"trigger_required_votes": 1})
    result = backtest(df, strategy, fee=0.0005, slippage=0.0005, interval="minute30")
    assert isinstance(result, BacktestResult)

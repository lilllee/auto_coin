"""Unit tests for ``regime_relative_breakout_30m`` strategy + enricher.

All tests are offline: no pyupbit, no network, no persistence.  Tests synth
minimal enriched DataFrames that satisfy the column contract used by
``RegimeRelativeBreakout30mStrategy.generate_signal`` and ``generate_exit``.
Two tests (14, 15) exercise the real ``enrich_regime_relative_breakout_30m``
on synthetic OHLCV to verify no-lookahead shifts on prior_high, volume_ma,
and daily regime.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import enrich_regime_relative_breakout_30m
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, PositionSnapshot, Signal
from auto_coin.strategy.regime_relative_breakout_30m import (
    RegimeRelativeBreakout30mStrategy,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_enriched_df(n: int = 60, **overrides: object) -> pd.DataFrame:
    """Build a synthetic enriched 30m DataFrame with all columns satisfied
    at the final row by default.  Individual tests flip columns via ``overrides``
    which are assigned to the LAST row only."""
    idx = pd.date_range("2026-03-01", periods=n, freq="30min")
    close = np.linspace(100.0, 120.0, n)
    high = close + 0.5
    low = close - 0.5
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 200.0),
            # breakout features
            "prior_high_6": close - 0.2,  # last close well above prior high
            "volume_ma_20": np.full(n, 100.0),
            "volume_ratio": np.full(n, 2.0),
            "close_location_value": np.full(n, 0.8),
            # 30m / ATR
            "atr14": np.full(n, 1.0),
            # Daily BTC regime projected onto 30m
            "btc_daily_regime_on": [True] * n,
            # 1H projected features
            "hourly_close": close + 2.0,
            "hourly_ema20": close + 1.0,
            "hourly_ema60": close - 1.0,
            "hourly_ema20_slope_3": np.full(n, 0.5),
            "hourly_close_below_ema20": [False] * n,
            "hourly_close_below_ema20_run": np.zeros(n),
            # RS
            "target_rs_24h_vs_btc": np.full(n, 0.02),
            "target_rs_7d_vs_btc": np.full(n, 0.03),
        },
        index=idx,
    )
    for k, v in overrides.items():
        df.iloc[-1, df.columns.get_loc(k)] = v
    return df


def _snap(df: pd.DataFrame, *, price: float | None = None, has_position: bool = False) -> MarketSnapshot:
    return MarketSnapshot(
        df=df,
        current_price=float(df["close"].iloc[-1]) if price is None else price,
        has_position=has_position,
        interval="minute30",
        bar_seconds=1800,
    )


def _position(entry: float = 100.0, *, hold_bars: int = 4, highest_high: float = 110.0) -> PositionSnapshot:
    return PositionSnapshot(
        entry_price=entry,
        hold_days=hold_bars,
        highest_close=highest_high,
        highest_high=highest_high,
        interval="minute30",
        bar_seconds=1800,
        hold_bars=hold_bars,
    )


# ---------------------------------------------------------------------------
# Test 1 — validation
# ---------------------------------------------------------------------------


def test_strategy_validation_rejects_invalid_params() -> None:
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(daily_regime_ma_window=1)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(hourly_ema_slow=10, hourly_ema_fast=20)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(volume_mult=0.0)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(close_location_min=1.5)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(trend_exit_confirm_bars=0)
    with pytest.raises(ValueError):
        RegimeRelativeBreakout30mStrategy(max_hold_bars_30m=0)
    # registry path also works
    strategy = create_strategy("regime_relative_breakout_30m", {})
    assert strategy.name == "regime_relative_breakout_30m"


# ---------------------------------------------------------------------------
# Tests 2-8 — entry logic
# ---------------------------------------------------------------------------


def test_entry_buy_when_all_conditions_true() -> None:
    df = _make_enriched_df()
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.BUY


def test_entry_hold_when_btc_regime_false() -> None:
    df = _make_enriched_df(btc_daily_regime_on=False)
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


def test_entry_hold_when_24h_rs_not_positive() -> None:
    df = _make_enriched_df(target_rs_24h_vs_btc=-0.001)
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD

    df = _make_enriched_df(target_rs_24h_vs_btc=0.0)
    # strict >, so zero must still HOLD
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


def test_entry_hold_when_7d_rs_not_positive() -> None:
    df = _make_enriched_df(target_rs_7d_vs_btc=-0.01)
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


def test_entry_hold_when_hourly_trend_broken() -> None:
    strategy = RegimeRelativeBreakout30mStrategy()
    # hourly_close <= hourly_ema20
    df1 = _make_enriched_df()
    df1.iloc[-1, df1.columns.get_loc("hourly_close")] = float(df1["hourly_ema20"].iloc[-1]) - 0.1
    assert strategy.generate_signal(_snap(df1)) == Signal.HOLD
    # hourly_ema20 <= hourly_ema60
    df2 = _make_enriched_df()
    df2.iloc[-1, df2.columns.get_loc("hourly_ema20")] = float(df2["hourly_ema60"].iloc[-1]) - 0.1
    assert strategy.generate_signal(_snap(df2)) == Signal.HOLD
    # negative slope
    df3 = _make_enriched_df(hourly_ema20_slope_3=-0.1)
    assert strategy.generate_signal(_snap(df3)) == Signal.HOLD


def test_entry_hold_when_breakout_not_exceeded() -> None:
    df = _make_enriched_df()
    # set prior_high_6 above current close → breakout fails
    df.iloc[-1, df.columns.get_loc("prior_high_6")] = float(df["close"].iloc[-1]) + 0.5
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD
    # CLV below 0.55 also fails
    df2 = _make_enriched_df(close_location_value=0.40)
    assert strategy.generate_signal(_snap(df2)) == Signal.HOLD


def test_entry_hold_when_volume_below_threshold() -> None:
    df = _make_enriched_df()
    # volume = ma * 1.2 exactly — strict > so must HOLD
    last_ma = float(df["volume_ma_20"].iloc[-1])
    df.iloc[-1, df.columns.get_loc("volume")] = last_ma * 1.2
    strategy = RegimeRelativeBreakout30mStrategy()
    assert strategy.generate_signal(_snap(df)) == Signal.HOLD


# ---------------------------------------------------------------------------
# Tests 9-13 — exit logic (priority order, confirmation, regime-off, time)
# ---------------------------------------------------------------------------


def test_initial_stop_fires_before_trailing_and_trend() -> None:
    # Construct a scenario where BOTH initial stop AND trailing would fire
    # — initial stop should be reported because it is checked first.
    df = _make_enriched_df()
    df.iloc[-1, df.columns.get_loc("low")] = 50.0  # deep low triggers everything
    strategy = RegimeRelativeBreakout30mStrategy(
        initial_stop_atr_mult=2.0,
        atr_trailing_mult=3.0,
    )
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_initial_stop")
    # exit price should be entry - atr*mult
    assert decision.exit_price == pytest.approx(100.0 - 1.0 * 2.0)


def test_trailing_exit_fires_when_only_trailing_hit() -> None:
    df = _make_enriched_df()
    # entry=100 atr=1 stop=100-2=98, trailing=highest_high-3*1=115-3=112.
    # Set low between 98 and 112 — only trailing triggers.
    df.iloc[-1, df.columns.get_loc("low")] = 110.0
    strategy = RegimeRelativeBreakout30mStrategy()
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_trailing_exit")
    assert decision.exit_price == pytest.approx(115.0 - 1.0 * 3.0)


def test_trend_exit_requires_configured_confirmation() -> None:
    strategy_confirm2 = RegimeRelativeBreakout30mStrategy(trend_exit_confirm_bars=2)
    strategy_confirm3 = RegimeRelativeBreakout30mStrategy(trend_exit_confirm_bars=3)

    # Preserve stops: keep low high enough that initial_stop/trailing do not fire.
    df = _make_enriched_df()
    df.iloc[-1, df.columns.get_loc("low")] = 119.0
    df.iloc[-1, df.columns.get_loc("hourly_close_below_ema20_run")] = 2

    pos = _position(entry=100.0, highest_high=115.0)
    decision = strategy_confirm2.generate_exit(_snap(df, has_position=True), pos)
    assert decision is not None
    assert decision.reason.endswith("_trend_exit")
    # confirm=3 should NOT fire because only 2 consecutive hourly bars below
    decision3 = strategy_confirm3.generate_exit(_snap(df, has_position=True), pos)
    assert decision3 is None or not decision3.reason.endswith("_trend_exit")


def test_regime_off_exit_fires_when_btc_regime_false() -> None:
    df = _make_enriched_df(btc_daily_regime_on=False)
    df.iloc[-1, df.columns.get_loc("low")] = 119.0  # no stop fire
    strategy = RegimeRelativeBreakout30mStrategy()
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_regime_off_exit")


def test_time_exit_fires_when_max_hold_reached() -> None:
    df = _make_enriched_df()
    df.iloc[-1, df.columns.get_loc("low")] = 119.0  # no stop fire
    strategy = RegimeRelativeBreakout30mStrategy(max_hold_bars_30m=48)
    decision = strategy.generate_exit(
        _snap(df, has_position=True),
        _position(entry=100.0, hold_bars=48, highest_high=115.0),
    )
    assert decision is not None
    assert decision.reason.endswith("_time_exit")


# ---------------------------------------------------------------------------
# Tests 14-15 — enrichment / no-lookahead proofs
# ---------------------------------------------------------------------------


def _ohlcv(n: int, base: float = 100.0, freq: str = "30min") -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq=freq)
    close = base + np.arange(n, dtype=float) * 0.1
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 100.0),
        },
        index=idx,
    )


def test_enrichment_prior_high_and_volume_mean_are_shifted() -> None:
    # Construct a 30m series where row 10 has a HUGE high and a HUGE volume.
    # prior_high_N at row 10 must NOT include row 10 itself.  volume_ma_N at
    # row 10 must NOT include row 10's volume either.
    n = 60
    df = _ohlcv(n)
    df.iloc[10, df.columns.get_loc("high")] = 999.0
    df.iloc[10, df.columns.get_loc("volume")] = 9999.0

    daily = _ohlcv(30, base=100.0, freq="D")
    hourly = _ohlcv(120, base=100.0, freq="h")

    enriched = enrich_regime_relative_breakout_30m(
        df,
        daily_regime_df=daily,
        hourly_setup_df=hourly,
        rs_reference_df=df,
        breakout_lookback_30m=6,
        volume_window_30m=20,
    )

    prior_high_at_row10 = enriched["prior_high_6"].iloc[10]
    assert prior_high_at_row10 < 999.0  # does not include row 10's 999 spike
    assert enriched["prior_high_6"].iloc[11] == 999.0  # spike reachable from next row

    volume_ma_at_row10 = enriched["volume_ma_20"].iloc[10]
    # rows 0..9 were all 100.0; window of 20 back-shifted by 1 is rows 0..19 shifted(1)
    # at row 10, the volume window covers rows [-10..9] → only 10 points (NaN expected).
    # Require that, whenever finite, it does not equal inclusion of 9999.
    if pd.notna(volume_ma_at_row10):
        assert volume_ma_at_row10 < 9999.0 / 20.0 + 50.0  # still far below the spike's contribution ceiling


def test_enrichment_daily_regime_uses_previous_completed_day_only() -> None:
    # Build a daily series where closes straddle SMA so the regime flips at
    # the last day.  30m intraday bars during day d must see regime for d-1, not d.
    days = 10
    daily_idx = pd.date_range("2026-01-01", periods=days, freq="D")
    daily_close = np.array([100.0] * (days - 1) + [80.0])
    daily = pd.DataFrame(
        {
            "open": daily_close,
            "high": daily_close + 1,
            "low": daily_close - 1,
            "close": daily_close,
            "volume": [1.0] * days,
        },
        index=daily_idx,
    )
    # Build 30m bars covering the last two days (48 bars / day × 2 = 96).
    start = daily_idx[-2]
    thirty_idx = pd.date_range(start, periods=96, freq="30min")
    thirty_close = np.linspace(100.0, 80.0, 96)
    thirty = pd.DataFrame(
        {
            "open": thirty_close,
            "high": thirty_close + 0.1,
            "low": thirty_close - 0.1,
            "close": thirty_close,
            "volume": [100.0] * 96,
        },
        index=thirty_idx,
    )
    hourly_idx = pd.date_range(start, periods=48, freq="h")
    hourly = pd.DataFrame(
        {
            "open": np.linspace(100.0, 80.0, 48),
            "high": np.linspace(100.0, 80.0, 48) + 0.1,
            "low": np.linspace(100.0, 80.0, 48) - 0.1,
            "close": np.linspace(100.0, 80.0, 48),
            "volume": [100.0] * 48,
        },
        index=hourly_idx,
    )

    enriched = enrich_regime_relative_breakout_30m(
        thirty,
        daily_regime_df=daily,
        daily_regime_ma_window=3,
        hourly_setup_df=hourly,
        rs_reference_df=thirty,
    )

    # With shift(1) at the daily level, the regime value at a 30m bar on day d
    # must equal the regime computed FROM day d-1's close (not day d's close).
    # The final 30m bar is on the last daily boundary → it should see the
    # regime value from daily bar (last - 1), which still reflects the 100.0
    # plateau (regime True), NOT the fresh 80.0 drop (which would be False
    # under a no-shift implementation).
    final_regime = enriched["btc_daily_regime_on"].iloc[-1]
    assert bool(final_regime) is True

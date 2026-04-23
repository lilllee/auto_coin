"""Offline unit tests for scripts/regime_relative_strength_event_study.py.

These tests must not hit the network or touch pyupbit.  They exercise the pure
feature helpers, the event-dedupe cooldown, the summary-stats shape, and the
PASS/HOLD/STOP verdict classifier.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import regime_relative_strength_event_study as es  # noqa: E402


def _ohlcv(
    closes: list[float],
    *,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="30min")
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs if highs is not None else [c + 0.5 for c in closes],
            "low": lows if lows is not None else [c - 0.5 for c in closes],
            "close": closes,
            "volume": volumes if volumes is not None else [100.0] * n,
        },
        index=idx,
    )


def test_close_location_zero_range_safe() -> None:
    # high == low for every row → range is zero; CLV should collapse to 0.5, not NaN/inf.
    df = pd.DataFrame(
        {
            "open": [10.0, 10.0, 10.0],
            "high": [10.0, 10.0, 10.0],
            "low": [10.0, 10.0, 10.0],
            "close": [10.0, 10.0, 10.0],
            "volume": [1.0, 1.0, 1.0],
        }
    )
    clv = es.compute_close_location_value(df)
    assert list(clv) == [0.5, 0.5, 0.5]
    assert np.isfinite(clv).all()


def test_breakout_features_are_shifted() -> None:
    # prior_high_N must exclude the current candle; same for volume_ma_N.
    highs = [1.0, 2.0, 3.0, 100.0, 5.0, 6.0]
    volumes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    df = _ohlcv([h - 0.1 for h in highs], highs=highs, volumes=volumes)

    prior_high_3 = es.compute_prior_high(df["high"], 3)
    # At position 3 (the giant 100.0 candle), the prior-high window [0..2] is 3, not 100.
    assert prior_high_3.iloc[3] == 3.0
    # At position 4, the window [1..3] still excludes current row 4 (5.0) but includes 100.
    assert prior_high_3.iloc[4] == 100.0
    # Early rows must be NaN (insufficient lookback).
    assert pd.isna(prior_high_3.iloc[0])
    assert pd.isna(prior_high_3.iloc[2])

    volumes2 = [100.0, 100.0, 100.0, 9999.0, 100.0, 100.0]
    df2 = _ohlcv([10.0] * 6, volumes=volumes2)
    vol_ma_3 = es.compute_volume_ma(df2["volume"], 3)
    # At position 3, volume_ma_3 must not include the 9999 spike at row 3.
    assert vol_ma_3.iloc[3] == 100.0
    # At position 4, the window [1..3] includes the spike.
    assert vol_ma_3.iloc[4] == (100 + 100 + 9999) / 3


def test_forward_returns_no_lookahead_in_event_condition() -> None:
    # condition_masks must operate on feature columns only; passing a DataFrame
    # that lacks any fwd_ret_*/fwd_excess_ret_* columns should still work.
    n = 30
    idx = pd.date_range("2026-01-01", periods=n, freq="30min")
    df = pd.DataFrame(
        {
            "close": np.linspace(100.0, 110.0, n),
            "prior_high_6": np.linspace(99.0, 109.0, n),
            "close_location_value": np.full(n, 0.8),
            "btc_daily_regime_on": [True] * n,
            "target_rs_24h_vs_btc": np.full(n, 0.01),
            "target_rs_7d_vs_btc": np.full(n, 0.02),
            "volume": np.full(n, 200.0),
            "volume_ma20": np.full(n, 100.0),
            "hourly_close": np.full(n, 110.0),
            "hourly_ema20": np.full(n, 108.0),
            "hourly_ema60": np.full(n, 105.0),
            "hourly_ema20_slope_3": np.full(n, 0.5),
            "hourly_pullback_return_8": np.full(n, -0.02),
            "rsi14": np.full(n, 55.0),
        },
        index=idx,
    )
    masks = es.condition_masks(df)
    assert set(masks.keys()) == set(es.CONDITION_SET_NAMES)
    # Each mask must be aligned to df.index and boolean.
    for name, mask in masks.items():
        assert mask.index.equals(df.index), name
        assert mask.dtype == bool, name
    # Most restrictive set fires because all gating conditions are satisfied.
    assert masks["regime_rs_pullback_rebreakout"].any()


def test_relative_strength_vs_btc() -> None:
    # 24h at 30m = 48 bars; construct a series where target pumps 10 % over 48
    # bars while BTC is flat, so RS_24h should be exactly +0.10 at the right row.
    n = 60
    idx = pd.date_range("2026-01-01", periods=n, freq="30min")
    target_close = pd.Series([100.0] * 48 + [110.0] * (n - 48), index=idx)
    btc_close = pd.Series([200.0] * n, index=idx)
    rs_24h = es.compute_relative_strength(target_close, btc_close, 48)
    # At position 48, target return = 110/100 - 1 = 0.10; btc return = 0.
    assert abs(float(rs_24h.iloc[48]) - 0.10) < 1e-9
    # Before the 48-bar mark, RS is NaN (shift not yet available).
    assert pd.isna(rs_24h.iloc[47])


def test_dedupe_events_applies_cooldown() -> None:
    n = 25
    idx = pd.date_range("2026-01-01", periods=n, freq="30min")
    mask = pd.Series([False] * n, index=idx)
    mask.iloc[10] = True
    mask.iloc[11] = True
    mask.iloc[12] = True
    mask.iloc[19] = True
    deduped = es.dedupe_events(mask, cooldown=8)
    accepted_positions = [i for i, v in enumerate(deduped.to_numpy()) if v]
    # t=10 accepted, t=11 and t=12 clustered, t=19 accepted (diff = 9 > 8).
    assert accepted_positions == [10, 19]


def test_summary_stats_handles_empty_events() -> None:
    empty_df = pd.DataFrame()
    summary = es.summarize_events(empty_df, raw_count=0)
    assert summary["raw_event_count"] == 0
    assert summary["event_count"] == 0
    assert set(summary["horizons"].keys()) == {"4", "8", "16", "24", "48"}
    for h in summary["horizons"].values():
        assert h["avg_return"] == 0.0
        assert h["median_return"] == 0.0
        assert h["win_rate"] == 0.0
        assert h["avg_excess_return"] == 0.0
        assert h["median_excess_return"] == 0.0
        assert h["excess_win_rate"] == 0.0
    assert set(summary["path"].keys()) == {"16", "24", "48"}
    for p in summary["path"].values():
        assert p["avg_mfe"] == 0.0
        assert p["median_mfe"] == 0.0
        assert p["avg_mae"] == 0.0
        assert p["median_mae"] == 0.0
    # A non-zero raw count with zero accepted events must still produce a stable schema.
    summary2 = es.summarize_events(empty_df, raw_count=42)
    assert summary2["raw_event_count"] == 42
    assert summary2["event_count"] == 0


def _gates(**overrides: bool) -> dict[str, bool]:
    base = {
        "alt_events_ge_50": True,
        "eth_events_ge_15": True,
        "xrp_events_ge_15": True,
        "avg_excess_16_positive": True,
        "avg_excess_24_positive": True,
        "median_excess_16_non_negative": True,
        "median_excess_24_non_negative": True,
        "excess_win_rate_16_ge_52pct": True,
        "mae_24_not_extreme": True,
    }
    base.update(overrides)
    return base


def test_verdict_pass_hold_stop_paths() -> None:
    pass_stats = {
        "alt_event_count": 80,
        "h16_avg_excess": 0.01,
        "h24_avg_excess": 0.012,
        "h16_median_excess": 0.005,
        "h24_median_excess": 0.004,
    }
    assert es.classify_verdict(_gates(), pass_stats) == "PASS"

    # HOLD: event-count gates fail; not STOP because edge isn't uniformly negative.
    hold_stats = {
        "alt_event_count": 10,
        "h16_avg_excess": 0.001,
        "h24_avg_excess": -0.001,
        "h16_median_excess": 0.0,
        "h24_median_excess": 0.0,
    }
    hold_gates = _gates(
        alt_events_ge_50=False,
        eth_events_ge_15=False,
        xrp_events_ge_15=False,
    )
    assert es.classify_verdict(hold_gates, hold_stats) == "HOLD"

    # STOP: enough events but both 16/24 avg and median excess are negative.
    stop_stats = {
        "alt_event_count": 120,
        "h16_avg_excess": -0.01,
        "h24_avg_excess": -0.008,
        "h16_median_excess": -0.005,
        "h24_median_excess": -0.006,
    }
    stop_gates = _gates(
        avg_excess_16_positive=False,
        avg_excess_24_positive=False,
        median_excess_16_non_negative=False,
        median_excess_24_non_negative=False,
        excess_win_rate_16_ge_52pct=False,
    )
    assert es.classify_verdict(stop_gates, stop_stats) == "STOP"

    # REVISE: event-count gates pass, 1-3 edge gates fail, not all-negative.
    revise_stats = {
        "alt_event_count": 80,
        "h16_avg_excess": 0.005,
        "h24_avg_excess": -0.001,
        "h16_median_excess": 0.001,
        "h24_median_excess": -0.001,
    }
    revise_gates = _gates(
        avg_excess_24_positive=False,
        median_excess_24_non_negative=False,
    )
    assert es.classify_verdict(revise_gates, revise_stats) == "REVISE"



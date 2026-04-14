from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import (
    enrich_atr_channel,
    enrich_daily,
    enrich_donchian,
    enrich_ema_adx,
    enrich_for_strategy,
    enrich_sma,
    fetch_daily,
)
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError


def _sample_df(n: int = 10) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open":   np.arange(100, 100 + n, dtype=float),
            "high":   np.arange(110, 110 + n, dtype=float),
            "low":    np.arange(90,  90  + n, dtype=float),
            "close":  np.arange(105, 105 + n, dtype=float),
            "volume": np.ones(n),
        },
        index=idx,
    )


def test_enrich_daily_adds_columns():
    df = _sample_df(10)
    out = enrich_daily(df, ma_window=5, k=0.5)
    assert "range" in out.columns
    assert "target" in out.columns
    assert "ma5" in out.columns
    # 첫 행은 전일 값이 없으므로 range/target NaN
    assert pd.isna(out["range"].iloc[0])
    assert pd.isna(out["target"].iloc[0])
    # 두 번째 행: range = 전일(110-90) = 20, target = open(101) + 20*0.5 = 111
    assert out["range"].iloc[1] == 20.0
    assert out["target"].iloc[1] == 111.0


def test_enrich_daily_ma_uses_prior_closes_only():
    df = _sample_df(10)
    out = enrich_daily(df, ma_window=5, k=0.5)
    # ma5는 shift(1) 적용 — 인덱스 5의 ma5 = mean(close[0..4])
    expected = df["close"].iloc[0:5].mean()
    assert out["ma5"].iloc[5] == expected


def test_enrich_daily_missing_columns():
    df = pd.DataFrame({"open": [1.0], "high": [2.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        enrich_daily(df)


def test_enrich_daily_invalid_params():
    df = _sample_df()
    with pytest.raises(ValueError):
        enrich_daily(df, k=0)
    with pytest.raises(ValueError):
        enrich_daily(df, ma_window=0)


def test_fetch_daily_uses_pyupbit(mocker):
    df = _sample_df(20)
    mocker.patch("auto_coin.data.candles.pyupbit.get_ohlcv", return_value=df)
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)
    out = fetch_daily(client, "KRW-BTC", count=20, ma_window=5, k=0.5)
    assert "target" in out.columns
    assert len(out) == 20


def test_fetch_daily_empty_raises(mocker):
    mocker.patch("auto_coin.data.candles.pyupbit.get_ohlcv", return_value=None)
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)
    with pytest.raises(UpbitError):
        fetch_daily(client, "KRW-BTC")


# --- enrich_sma tests ---


def test_enrich_sma_adds_column():
    df = _sample_df(250)
    out = enrich_sma(df, window=200)
    assert "sma200" in out.columns
    # rolling(200) first non-NaN at index 199; shift(1) moves it to index 200
    assert pd.isna(out["sma200"].iloc[199])
    assert not pd.isna(out["sma200"].iloc[200])


def test_enrich_sma_shift():
    """Verify shift(1) is applied — sma at index i uses closes up to i-1."""
    df = _sample_df(210)
    out = enrich_sma(df, window=200)
    # rolling(200) at index 199 = mean(close[0:200]), shift(1) puts it at index 200
    expected = df["close"].iloc[0:200].mean()
    assert abs(out["sma200"].iloc[200] - expected) < 1e-10


def test_enrich_sma_missing_columns():
    df = pd.DataFrame({"open": [1.0], "high": [2.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        enrich_sma(df, window=200)


def test_enrich_sma_invalid_window():
    df = _sample_df()
    with pytest.raises(ValueError, match="window must be >= 2"):
        enrich_sma(df, window=1)


def test_enrich_sma_does_not_overwrite_existing():
    """If sma column already exists, enrich_sma should not overwrite it."""
    df = _sample_df(10)
    df["sma200"] = 999.0
    out = enrich_sma(df, window=200)
    assert (out["sma200"] == 999.0).all()


# --- enrich_for_strategy tests ---


def test_enrich_for_strategy_vb():
    df = _sample_df(10)
    out = enrich_for_strategy(df, "volatility_breakout", {}, ma_window=5, k=0.5)
    assert "target" in out.columns
    assert "range" in out.columns
    assert "ma5" in out.columns


def test_enrich_for_strategy_sma200():
    df = _sample_df(250)
    out = enrich_for_strategy(
        df, "sma200_regime", {"ma_window": 200}, ma_window=5, k=0.5
    )
    # Should have both VB columns and sma column
    assert "target" in out.columns
    assert "range" in out.columns
    assert "sma200" in out.columns


def test_enrich_for_strategy_sma200_custom_window():
    df = _sample_df(100)
    out = enrich_for_strategy(
        df, "sma200_regime", {"ma_window": 50}, ma_window=5, k=0.5
    )
    assert "sma50" in out.columns


def test_enrich_for_strategy_unknown_defaults_to_vb():
    df = _sample_df(10)
    out = enrich_for_strategy(df, "unknown_strategy", {}, ma_window=5, k=0.5)
    assert "target" in out.columns
    assert "range" in out.columns


# --- enrich_atr_channel tests ---


def test_enrich_atr_channel_adds_columns():
    df = _sample_df(30)
    out = enrich_atr_channel(df, atr_window=14, channel_multiplier=1.0)
    assert "atr14" in out.columns
    assert "upper_channel" in out.columns
    assert "lower_channel" in out.columns


def test_enrich_atr_channel_shift():
    """Verify shift(1) is applied — ATR at index i uses data up to i-1."""
    df = _sample_df(30)
    out = enrich_atr_channel(df, atr_window=14, channel_multiplier=1.0)
    # TR at index 0 = max(high-low, NaN, NaN) = 20.0 (high-low dominates)
    # rolling(14) first non-NaN at index 13; shift(1) moves atr to index 14
    assert pd.isna(out["atr14"].iloc[13])
    assert not pd.isna(out["atr14"].iloc[14])
    # upper_channel = (low + atr*mult).shift(1)
    # atr14 at index 14 valid; upper_channel at 14 uses low[13]+atr14[13]=NaN
    # upper_channel first non-NaN at index 15
    assert pd.isna(out["upper_channel"].iloc[14])
    assert not pd.isna(out["upper_channel"].iloc[15])


def test_enrich_atr_channel_missing_columns():
    df = pd.DataFrame({"open": [1.0], "high": [2.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        enrich_atr_channel(df)


def test_enrich_atr_channel_invalid_params():
    df = _sample_df()
    with pytest.raises(ValueError, match="atr_window must be >= 1"):
        enrich_atr_channel(df, atr_window=0)
    with pytest.raises(ValueError, match="channel_multiplier must be > 0"):
        enrich_atr_channel(df, channel_multiplier=0)


def test_enrich_for_strategy_atr_channel():
    df = _sample_df(30)
    out = enrich_for_strategy(
        df,
        "atr_channel_breakout",
        {"atr_window": 14, "channel_multiplier": 1.5},
        ma_window=5,
        k=0.5,
    )
    # Should have both VB columns and ATR channel columns
    assert "target" in out.columns
    assert "range" in out.columns
    assert "atr14" in out.columns
    assert "upper_channel" in out.columns
    assert "lower_channel" in out.columns


# --- enrich_ema_adx tests ---


def test_enrich_ema_adx_adds_columns():
    df = _sample_df(200)
    out = enrich_ema_adx(df, ema_fast=27, ema_slow=125, adx_window=90)
    assert "ema27" in out.columns
    assert "ema125" in out.columns
    assert "adx90" in out.columns
    # EMA uses ewm so values appear early; shift(1) means first row is NaN
    assert pd.isna(out["ema27"].iloc[0])
    assert pd.isna(out["ema125"].iloc[0])
    assert pd.isna(out["adx90"].iloc[0])
    # Later rows should have values
    assert not pd.isna(out["ema27"].iloc[50])
    assert not pd.isna(out["ema125"].iloc[150])
    assert not pd.isna(out["adx90"].iloc[100])


def test_enrich_ema_adx_missing_columns():
    df = pd.DataFrame({"open": [1.0], "high": [2.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        enrich_ema_adx(df)


def test_enrich_for_strategy_ema_adx():
    df = _sample_df(200)
    out = enrich_for_strategy(
        df,
        "ema_adx_atr_trend",
        {"ema_fast_window": 27, "ema_slow_window": 125, "adx_window": 90},
        ma_window=5,
        k=0.5,
    )
    # Should have both VB columns and EMA/ADX columns
    assert "target" in out.columns
    assert "range" in out.columns
    assert "ema27" in out.columns
    assert "ema125" in out.columns
    assert "adx90" in out.columns


# --- enrich_donchian tests ---


def test_enrich_donchian_adds_columns():
    df = _sample_df(30)
    out = enrich_donchian(df, entry_window=20, exit_window=10)
    assert "donchian_high_20" in out.columns
    assert "donchian_low_10" in out.columns


def test_enrich_donchian_shift():
    """Verify shift(1) is applied — donchian at index i uses data up to i-1."""
    df = _sample_df(30)
    out = enrich_donchian(df, entry_window=20, exit_window=10)
    # rolling(20).max() first non-NaN at index 19; shift(1) moves to index 20
    assert pd.isna(out["donchian_high_20"].iloc[19])
    assert not pd.isna(out["donchian_high_20"].iloc[20])
    # rolling(10).min() first non-NaN at index 9; shift(1) moves to index 10
    assert pd.isna(out["donchian_low_10"].iloc[9])
    assert not pd.isna(out["donchian_low_10"].iloc[10])
    # Value check: donchian_high at index 20 = max(high[0:20]) via shift(1)
    expected_high = df["high"].iloc[0:20].max()
    assert out["donchian_high_20"].iloc[20] == expected_high
    expected_low = df["low"].iloc[0:10].min()
    assert out["donchian_low_10"].iloc[10] == expected_low


def test_enrich_donchian_missing_columns():
    df = pd.DataFrame({"open": [1.0], "high": [2.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        enrich_donchian(df)


def test_enrich_donchian_invalid_params():
    df = _sample_df()
    with pytest.raises(ValueError, match="entry_window must be >= 2"):
        enrich_donchian(df, entry_window=1)
    with pytest.raises(ValueError, match="exit_window must be >= 1"):
        enrich_donchian(df, exit_window=0)


def test_enrich_for_strategy_ad_turtle():
    df = _sample_df(30)
    out = enrich_for_strategy(
        df,
        "ad_turtle",
        {"entry_window": 20, "exit_window": 10},
        ma_window=5,
        k=0.5,
    )
    # Should have both VB columns and Donchian columns
    assert "target" in out.columns
    assert "range" in out.columns
    assert "donchian_high_20" in out.columns
    assert "donchian_low_10" in out.columns

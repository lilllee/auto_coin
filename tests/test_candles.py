from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import (
    candle_bar_seconds,
    enrich_atr_channel,
    enrich_daily,
    enrich_donchian,
    enrich_ema_adx,
    enrich_for_strategy,
    enrich_rcdb,
    enrich_rcdb_v2,
    enrich_regime_reclaim_30m,
    enrich_sma,
    fetch_candles,
    fetch_daily,
    history_days_to_candles,
    normalize_candle_interval,
    project_features,
    project_higher_timeframe_features,
    recommended_history_days,
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
    get_ohlcv = mocker.patch("auto_coin.data.candles.pyupbit.get_ohlcv", return_value=df)
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)
    out = fetch_daily(client, "KRW-BTC", count=20, ma_window=5, k=0.5)
    assert "target" in out.columns
    assert len(out) == 20
    get_ohlcv.assert_called_once_with("KRW-BTC", interval="day", count=20, to=None)


def test_fetch_daily_forwards_to_param(mocker):
    df = _sample_df(20)
    get_ohlcv = mocker.patch("auto_coin.data.candles.pyupbit.get_ohlcv", return_value=df)
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)

    out = fetch_daily(client, "KRW-BTC", count=20, to="2026-04-15", ma_window=5, k=0.5)

    assert len(out) == 20
    get_ohlcv.assert_called_once_with("KRW-BTC", interval="day", count=20, to="2026-04-15")


def test_fetch_candles_supports_minute60_interval(mocker):
    df = _sample_df(48)
    get_ohlcv = mocker.patch("auto_coin.data.candles.pyupbit.get_ohlcv", return_value=df)
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)

    out = fetch_candles(client, "KRW-BTC", count=48, interval="1h", ma_window=5, k=0.5)

    assert len(out) == 48
    assert "target" in out.columns
    get_ohlcv.assert_called_once_with("KRW-BTC", interval="minute60", count=48, to=None)


def test_fetch_daily_empty_raises(mocker):
    mocker.patch("auto_coin.data.candles.pyupbit.get_ohlcv", return_value=None)
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)
    with pytest.raises(UpbitError):
        fetch_daily(client, "KRW-BTC")


def test_fetch_daily_retries_when_pyupbit_returns_none_then_succeeds(mocker):
    df = _sample_df(20)
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv",
        side_effect=[None, df],
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=2,
                         backoff_base=0.0, min_request_interval=0.0)

    out = fetch_daily(client, "KRW-BTC", count=20, ma_window=5, k=0.5)

    assert "target" in out.columns
    assert len(out) == 20
    assert get_ohlcv.call_count == 2


def test_fetch_daily_retry_exhausted_preserves_no_candles_message(mocker):
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv",
        side_effect=[None, None],
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=2,
                         backoff_base=0.0, min_request_interval=0.0)

    with pytest.raises(UpbitError, match="no candles returned for KRW-BTC"):
        fetch_daily(client, "KRW-BTC")

    assert get_ohlcv.call_count == 2


def test_fetch_daily_retry_exhausted_on_empty_dataframe(mocker):
    empty = pd.DataFrame()
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv",
        side_effect=[empty, empty],
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=2,
                         backoff_base=0.0, min_request_interval=0.0)

    with pytest.raises(UpbitError, match="no candles returned for KRW-BTC"):
        fetch_daily(client, "KRW-BTC")

    assert get_ohlcv.call_count == 2


def test_recommended_history_days_composite_is_conservative():
    days = recommended_history_days(
        "sma200_ema_adx_composite",
        {
            "sma_window": 200,
            "ema_fast_window": 27,
            "ema_slow_window": 125,
            "adx_window": 90,
            "adx_threshold": 14.0,
        },
        ma_window=5,
    )
    assert days == 250


def test_recommended_history_days_volatility_breakout_uses_safe_minimum():
    days = recommended_history_days(
        "volatility_breakout",
        {"k": 0.5, "ma_window": 5, "require_ma_filter": True},
        ma_window=5,
    )
    assert days == 60


def test_recommended_history_days_unknown_strategy_falls_back_to_safe_minimum():
    days = recommended_history_days("unknown_strategy", {}, ma_window=5)
    assert days == 60


def test_history_days_to_candles_respects_interval():
    assert history_days_to_candles(10, "day") == 10
    assert history_days_to_candles(10, "minute60") == 240
    assert history_days_to_candles(2, "1h") == 48
    assert candle_bar_seconds("minute60") == 3600


def test_project_higher_timeframe_features_forward_fills_to_hourly():
    regime_idx = pd.date_range("2026-01-01", periods=2, freq="D")
    regime = pd.DataFrame(
        {
            "regime_on": [False, True],
            "regime_sma120": [100.0, 101.0],
        },
        index=regime_idx,
    )
    target_idx = pd.date_range("2026-01-01", periods=48, freq="h")

    projected = project_higher_timeframe_features(
        regime,
        target_idx,
        columns=["regime_on", "regime_sma120"],
    )

    assert list(projected.columns) == ["regime_on", "regime_sma120"]
    assert projected.loc["2026-01-01 12:00:00", "regime_on"] == False  # noqa: E712
    assert projected.loc["2026-01-02 12:00:00", "regime_on"] == True  # noqa: E712
    assert projected.loc["2026-01-02 03:00:00", "regime_sma120"] == pytest.approx(101.0)


def test_recommended_history_days_rcdb_uses_regime_window():
    days = recommended_history_days(
        "rcdb",
        {
            "regime_ma_window": 120,
            "dip_lookback_days": 5,
            "rsi_window": 14,
            "atr_window": 14,
        },
        ma_window=5,
    )
    assert days == 170


def test_recommended_history_days_rcdb_v2_uses_all_windows():
    days = recommended_history_days(
        "rcdb_v2",
        {
            "regime_ma_window": 120,
            "dip_lookback_days": 5,
            "vol_window": 20,
            "rsi_window": 14,
            "reversal_ema_window": 5,
            "atr_window": 14,
        },
        ma_window=5,
    )
    assert days == 170


def test_recommended_history_days_regime_reclaim_1h_uses_daily_regime_window():
    days = recommended_history_days(
        "regime_reclaim_1h",
        {
            "daily_regime_ma_window": 120,
            "dip_lookback_bars": 8,
            "rsi_window": 14,
            "reclaim_ema_window": 6,
            "atr_window": 14,
        },
        ma_window=5,
    )
    assert days == 170


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


def test_enrich_rcdb_adds_columns():
    df = _sample_df(200)
    out = enrich_rcdb(
        df,
        regime_ma_window=120,
        dip_lookback_days=5,
        rsi_window=14,
        atr_window=14,
    )
    assert "regime_close" in out.columns
    assert "regime_sma120" in out.columns
    assert "regime_on" in out.columns
    assert "dip_return_5" in out.columns
    assert "rsi14" in out.columns
    assert "atr14" in out.columns


def test_enrich_for_strategy_rcdb():
    df = _sample_df(200)
    out = enrich_for_strategy(
        df,
        "rcdb",
        {
            "regime_ma_window": 120,
            "dip_lookback_days": 5,
            "rsi_window": 14,
            "atr_window": 14,
        },
        ma_window=5,
        k=0.5,
    )
    assert "target" in out.columns
    assert "range" in out.columns
    assert "regime_sma120" in out.columns
    assert "dip_return_5" in out.columns
    assert "rsi14" in out.columns
    assert "atr14" in out.columns


def test_enrich_rcdb_v2_adds_columns():
    df = _sample_df(200)
    out = enrich_rcdb_v2(
        df,
        regime_ma_window=120,
        dip_lookback_days=5,
        vol_window=20,
        rsi_window=14,
        reversal_ema_window=5,
        atr_window=14,
    )
    assert "regime_close" in out.columns
    assert "regime_sma120" in out.columns
    assert "regime_on" in out.columns
    assert "lookback_return_5" in out.columns
    assert "realized_vol_20" in out.columns
    assert "dip_score_5_20" in out.columns
    assert "rsi14" in out.columns
    assert "reversal_ema5" in out.columns
    assert "atr14" in out.columns


def test_enrich_for_strategy_rcdb_v2():
    df = _sample_df(200)
    out = enrich_for_strategy(
        df,
        "rcdb_v2",
        {
            "regime_ma_window": 120,
            "dip_lookback_days": 5,
            "vol_window": 20,
            "rsi_window": 14,
            "reversal_ema_window": 5,
            "atr_window": 14,
        },
        ma_window=5,
        k=0.5,
    )
    assert "target" in out.columns
    assert "range" in out.columns
    assert "regime_sma120" in out.columns
    assert "lookback_return_5" in out.columns
    assert "realized_vol_20" in out.columns
    assert "dip_score_5_20" in out.columns
    assert "rsi14" in out.columns
    assert "reversal_ema5" in out.columns
    assert "atr14" in out.columns


def test_fetch_daily_rcdb_fetches_regime_reference_when_ticker_differs(mocker):
    asset_df = _sample_df(200)
    regime_df = _sample_df(200)
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv",
        side_effect=[asset_df, regime_df],
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)

    out = fetch_daily(
        client,
        "KRW-ETH",
        count=200,
        strategy_name="rcdb",
        strategy_params={
            "regime_ticker": "KRW-BTC",
            "regime_ma_window": 120,
            "dip_lookback_days": 5,
            "rsi_window": 14,
            "atr_window": 14,
        },
    )

    assert "regime_close" in out.columns
    assert get_ohlcv.call_count == 2
    first_call = get_ohlcv.call_args_list[0]
    second_call = get_ohlcv.call_args_list[1]
    assert first_call.kwargs["count"] == 200
    assert second_call.args[0] == "KRW-BTC"


def test_fetch_daily_rcdb_v2_fetches_regime_reference_when_ticker_differs(mocker):
    asset_df = _sample_df(200)
    regime_df = _sample_df(200)
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv",
        side_effect=[asset_df, regime_df],
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)

    out = fetch_daily(
        client,
        "KRW-ETH",
        count=200,
        strategy_name="rcdb_v2",
        strategy_params={
            "regime_ticker": "KRW-BTC",
            "regime_ma_window": 120,
            "dip_lookback_days": 5,
            "vol_window": 20,
            "rsi_window": 14,
            "reversal_ema_window": 5,
            "atr_window": 14,
        },
    )

    assert "regime_close" in out.columns
    assert "dip_score_5_20" in out.columns
    assert get_ohlcv.call_count == 2


def test_fetch_candles_regime_reclaim_1h_fetches_daily_regime_even_for_same_ticker(mocker):
    hourly_df = _sample_df(48)
    daily_df = _sample_df(200)
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv",
        side_effect=[hourly_df, daily_df],
    )
    client = UpbitClient(access_key="", secret_key="", max_retries=1,
                         backoff_base=0.0, min_request_interval=0.0)

    out = fetch_candles(
        client,
        "KRW-BTC",
        count=48,
        interval="minute60",
        strategy_name="regime_reclaim_1h",
        strategy_params={
            "regime_ticker": "KRW-BTC",
            "regime_interval": "day",
            "daily_regime_ma_window": 120,
            "dip_lookback_bars": 8,
            "pullback_threshold_pct": -0.025,
            "rsi_window": 14,
            "reclaim_ema_window": 6,
            "atr_window": 14,
        },
    )

    assert "daily_regime_on" in out.columns
    assert get_ohlcv.call_count == 2
    assert get_ohlcv.call_args_list[0].kwargs["interval"] == "minute60"
    assert get_ohlcv.call_args_list[1].kwargs["interval"] == "day"


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
    out = enrich_ema_adx(df, ema_fast=27, ema_slow=125, adx_window=90, atr_window=14)
    assert "ema27" in out.columns
    assert "ema125" in out.columns
    assert "adx90" in out.columns
    assert "atr14" in out.columns
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


def test_enrich_ema_adx_invalid_params():
    df = _sample_df(200)
    with pytest.raises(ValueError, match="ema_fast must be >= 1"):
        enrich_ema_adx(df, ema_fast=0)
    with pytest.raises(ValueError, match="ema_slow must be > ema_fast"):
        enrich_ema_adx(df, ema_fast=20, ema_slow=20)
    with pytest.raises(ValueError, match="adx_window must be >= 1"):
        enrich_ema_adx(df, adx_window=0)
    with pytest.raises(ValueError, match="atr_window must be >= 1"):
        enrich_ema_adx(df, atr_window=0)


def test_enrich_for_strategy_ema_adx():
    df = _sample_df(200)
    out = enrich_for_strategy(
        df,
        "ema_adx_atr_trend",
        {"ema_fast_window": 27, "ema_slow_window": 125, "adx_window": 90, "atr_window": 14},
        ma_window=5,
        k=0.5,
    )
    # Should have both VB columns and EMA/ADX columns
    assert "target" in out.columns
    assert "range" in out.columns
    assert "ema27" in out.columns
    assert "ema125" in out.columns
    assert "adx90" in out.columns
    assert "atr14" in out.columns


# --- enrich_donchian tests ---


def test_enrich_donchian_adds_columns():
    df = _sample_df(30)
    out = enrich_donchian(df, entry_window=20, exit_window=10)
    assert "donchian_high_20" in out.columns
    assert "donchian_low_10" in out.columns


# --- enrich_for_strategy composite tests ---


def test_enrich_for_strategy_composite():
    df = _sample_df(300)
    out = enrich_for_strategy(
        df,
        "sma200_ema_adx_composite",
        {"sma_window": 200, "ema_fast_window": 27, "ema_slow_window": 125, "adx_window": 90},
        ma_window=5,
        k=0.5,
    )
    # Should have VB base columns
    assert "target" in out.columns
    assert "range" in out.columns
    # Should have SMA column
    assert "sma200" in out.columns
    # Should have EMA+ADX columns
    assert "ema27" in out.columns
    assert "ema125" in out.columns
    assert "adx90" in out.columns


def test_enrich_for_strategy_composite_custom_windows():
    df = _sample_df(200)
    out = enrich_for_strategy(
        df,
        "sma200_ema_adx_composite",
        {"sma_window": 100, "ema_fast_window": 10, "ema_slow_window": 50, "adx_window": 30},
        ma_window=5,
        k=0.5,
    )
    assert "sma100" in out.columns
    assert "ema10" in out.columns
    assert "ema50" in out.columns
    assert "adx30" in out.columns


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


# === minute30 지원 테스트 ===

def test_normalize_candle_interval_minute30():
    """minute30, 30m, 30min 모두 'minute30'로 정규화."""
    assert normalize_candle_interval("minute30") == "minute30"
    assert normalize_candle_interval("30m") == "minute30"
    assert normalize_candle_interval("30min") == "minute30"
    assert normalize_candle_interval("MINUTE30") == "minute30"
    assert normalize_candle_interval("  30m  ") == "minute30"


def test_candle_bar_seconds_minute30():
    """minute30 bar_seconds == 1800 (30분)."""
    assert candle_bar_seconds("minute30") == 1800
    assert candle_bar_seconds("30m") == 1800
    assert candle_bar_seconds("30min") == 1800


def test_history_days_to_candles_minute30():
    """minute30: 10일 = 480 candles (10 * 48)."""
    assert history_days_to_candles(1, "minute30") == 48
    assert history_days_to_candles(10, "minute30") == 480
    assert history_days_to_candles(1, "30m") == 48
    # day와 비교: 10일 = 10 candles (day) vs 480 candles (minute30)
    assert history_days_to_candles(10, "day") == 10
    assert history_days_to_candles(10, "minute30") == 480


def test_fetch_candles_supports_minute30_interval(mocker):
    """fetch_candles 가 minute30 interval 을 받아 crash-free 로 동작."""
    df = _sample_df(48)
    get_ohlcv = mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv", return_value=df
    )
    client = UpbitClient(
        access_key="", secret_key="", max_retries=1,
        backoff_base=0.0, min_request_interval=0.0,
    )

    out = fetch_candles(
        client, "KRW-BTC", count=48, interval="30m", ma_window=5, k=0.5,
    )

    assert len(out) == 48
    assert "target" in out.columns
    get_ohlcv.assert_called_once_with("KRW-BTC", interval="minute30", count=48, to=None)


def test_fetch_candles_minute30_with_regime_reclaim_30m(mocker):
    """fetch_candles 가 regime_reclaim_30m 전략 시 daily + 1H + 30m 자동 fetch."""
    df_30m = _sample_df(96)
    df_daily = _sample_df(30)
    df_1h = _sample_df(720)

    def side_effect(ticker, interval, count, to=None):
        if interval == "minute30":
            return df_30m
        elif interval == "day":
            return df_daily
        elif interval == "minute60":
            return df_1h
        return pd.DataFrame()

    mocker.patch(
        "auto_coin.data.candles.pyupbit.get_ohlcv", side_effect=side_effect
    )
    client = UpbitClient(
        access_key="", secret_key="", max_retries=1,
        backoff_base=0.0, min_request_interval=0.0,
    )

    out = fetch_candles(
        client, "KRW-ETH", count=96, interval="30m",
        strategy_name="regime_reclaim_30m",
        strategy_params={},
    )

    assert len(out) == 96
    # daily regime columns 가 30m 인덱스에 투영되어야 함
    assert "daily_regime_on" in out.columns
    assert "daily_regime_sma120" in out.columns
    # 1H setup columns 도 투영
    assert "hourly_pullback_return_8" in out.columns
    # 30m trigger columns
    assert "pullback_return_8" in out.columns
    assert "rsi14" in out.columns
    assert "atr14" in out.columns


def test_project_features_daily_to_30m():
    """daily → 30m projection: ffill 로 상위 feature 전파."""
    # daily index (1일 간격)
    daily_idx = pd.date_range("2026-01-01", periods=5, freq="D")
    daily_df = pd.DataFrame(
        {"regime_on": [True, True, False, True, True]},
        index=daily_idx,
    )

    # 30m index (30분 간격, 1일 중 몇 개 바)
    thirty_idx = pd.date_range("2026-01-01", periods=20, freq="30min")

    result = project_features(
        daily_df, thirty_idx,
        source_interval="day",
        target_interval="minute30",
        columns=["regime_on"],
    )

    # daily > 30m 이므로 ffill 적용
    assert result["regime_on"].iloc[0]
    # 3일차에 False 가 나오므로 그 이후는 False
    # 실제로는 index union + ffill 이므로 day3 의 False 가 그 이후에 전파
    assert result["regime_on"].iloc[-1]


def test_project_features_1h_to_30m():
    """1H → 30m projection: ffill 로 상위 feature 전파."""
    # 1H index
    hourly_idx = pd.date_range("2026-01-01", periods=10, freq="h")
    hourly_df = pd.DataFrame(
        {"setup": [False, False, True, True, False, True, False, False, True, True]},
        index=hourly_idx,
    )

    # 30m index (10시간 = 20바)
    thirty_idx = pd.date_range("2026-01-01", periods=20, freq="30min")

    result = project_features(
        hourly_df, thirty_idx,
        source_interval="minute60",
        target_interval="minute30",
        columns=["setup"],
    )

    assert len(result) == 20
    # 1H > 30m 이므로 ffill
    assert not result["setup"].iloc[0]
    assert not result["setup"].iloc[2]  # 1시간째 feature 가 30m 바 2개에 전파


def test_project_features_same_interval():
    """동일 interval: bfill 도 ffill 도 아닌 단순 reindex."""
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    df = pd.DataFrame({"v": [1, 2, 3, 4, 5]}, index=idx)

    # target에서 일부만
    target = idx[[0, 2, 4]]
    result = project_features(
        df, target,
        source_interval="day",
        target_interval="day",
        columns=["v"],
    )

    assert len(result) == 3
    assert list(result["v"]) == [1, 3, 5]


def test_enrich_regime_reclaim_30m_basic():
    """enrich_regime_reclaim_30m 이 기본 컬럼을 추가하는지."""
    # 30m sample df 생성
    idx = pd.date_range("2026-01-01", periods=50, freq="30min")
    df = pd.DataFrame(
        {
            "open":   np.arange(100, 100 + 50, dtype=float),
            "high":   np.arange(110, 110 + 50, dtype=float),
            "low":    np.arange(90,  90  + 50, dtype=float),
            "close":  np.arange(105, 105 + 50, dtype=float),
            "volume": np.ones(50),
        },
        index=idx,
    )

    out = enrich_regime_reclaim_30m(df)

    # 30m trigger features
    assert "pullback_return_8" in out.columns
    assert "pullback_threshold_8" in out.columns
    assert "rsi14" in out.columns
    assert "reclaim_ema6" in out.columns
    assert "reversion_sma8" in out.columns
    assert "atr14" in out.columns


def test_enrich_regime_reclaim_30m_with_daily_regime():
    """enrich_regime_reclaim_30m 이 daily_regime_df 를 받아 투영하는지."""
    # 30m df
    idx_30m = pd.date_range("2026-01-01", periods=100, freq="30min")
    df_30m = pd.DataFrame(
        {
            "open":   np.arange(100, 100 + 100, dtype=float),
            "high":   np.arange(110, 110 + 100, dtype=float),
            "low":    np.arange(90,  90  + 100, dtype=float),
            "close":  np.arange(105, 105 + 100, dtype=float),
            "volume": np.ones(100),
        },
        index=idx_30m,
    )

    # daily regime df
    idx_daily = pd.date_range("2026-01-01", periods=5, freq="D")
    df_daily = pd.DataFrame(
        {
            "open":   np.arange(200, 200 + 5, dtype=float),
            "high":   np.arange(210, 210 + 5, dtype=float),
            "low":    np.arange(190, 190  + 5, dtype=float),
            "close":  np.arange(205, 205 + 5, dtype=float),
            "volume": np.ones(5),
        },
        index=idx_daily,
    )

    out = enrich_regime_reclaim_30m(
        df_30m,
        daily_regime_df=df_daily,
        daily_regime_ma_window=3,
    )

    # daily regime 가 30m 인덱스에 투영되어야 함
    assert "regime_close" in out.columns
    assert "daily_regime_sma3" in out.columns
    assert "daily_regime_on" in out.columns
    # daily → 30m projection 이므로 ffill 적용됨
    assert not out["daily_regime_on"].isna().all()


def test_enrich_regime_reclaim_30m_with_hourly_setup():
    """enrich_regime_reclaim_30m 이 hourly_setup_df 를 받아 투영하는지."""
    # 30m df
    idx_30m = pd.date_range("2026-01-01", periods=100, freq="30min")
    df_30m = pd.DataFrame(
        {
            "open":   np.arange(100, 100 + 100, dtype=float),
            "high":   np.arange(110, 110 + 100, dtype=float),
            "low":    np.arange(90,  90  + 100, dtype=float),
            "close":  np.arange(105, 105 + 100, dtype=float),
            "volume": np.ones(100),
        },
        index=idx_30m,
    )

    # 1H setup df
    idx_1h = pd.date_range("2026-01-01", periods=10, freq="h")
    df_1h = pd.DataFrame(
        {
            "open":   np.arange(300, 300 + 10, dtype=float),
            "high":   np.arange(310, 310 + 10, dtype=float),
            "low":    np.arange(290, 290  + 10, dtype=float),
            "close":  np.arange(305, 305 + 10, dtype=float),
            "volume": np.ones(10),
        },
        index=idx_1h,
    )

    out = enrich_regime_reclaim_30m(
        df_30m,
        daily_regime_df=None,  # fallback 사용
        hourly_setup_df=df_1h,
        hourly_pullback_bars=4,
        hourly_pullback_threshold_pct=-0.03,
    )

    # 1H setup 가 30m 인덱스에 투영되어야 함
    assert "hourly_pullback_return_4" in out.columns
    assert "hourly_pullback_threshold_4" in out.columns
    # 1H → 30m projection 이므로 ffill 적용
    assert not out["hourly_pullback_return_4"].isna().all()


def test_enrich_for_strategy_regime_reclaim_30m():
    """enrich_for_strategy 가 regime_reclaim_30m 전략을 올바르게 라우팅."""
    idx = pd.date_range("2026-01-01", periods=50, freq="30min")
    df = pd.DataFrame(
        {
            "open":   np.arange(100, 100 + 50, dtype=float),
            "high":   np.arange(110, 110 + 50, dtype=float),
            "low":    np.arange(90,  90  + 50, dtype=float),
            "close":  np.arange(105, 105 + 50, dtype=float),
            "volume": np.ones(50),
        },
        index=idx,
    )

    out = enrich_for_strategy(
        df,
        "regime_reclaim_30m",
        {
            "daily_regime_ma_window": 120,
            "dip_lookback_bars": 8,
            "pullback_threshold_pct": -0.025,
            "rsi_window": 14,
            "reclaim_ema_window": 6,
            "atr_window": 14,
        },
        ma_window=5,
        k=0.5,
    )

    assert "daily_regime_on" in out.columns
    assert "hourly_pullback_return_8" in out.columns
    assert "pullback_return_8" in out.columns
    assert "rsi14" in out.columns
    assert "atr14" in out.columns


def test_recommended_history_days_regime_reclaim_30m():
    """regime_reclaim_30m 의 권장 히스토리 days 가 합리적인지."""
    days = recommended_history_days(
        "regime_reclaim_30m",
        {
            "daily_regime_ma_window": 120,
            "hourly_pullback_bars": 8,
            "dip_lookback_bars": 8,
            "rsi_window": 14,
            "reclaim_ema_window": 6,
            "atr_window": 14,
        },
        ma_window=5,
    )
    # daily_regime_ma_window=120 이 가장 큼 → 120 + 50 = 170
    assert days >= 170


def test_existing_day_path_unchanged():
    """기존 day 경로가 여전히 정상 동작."""
    df = _sample_df(20)
    out = enrich_for_strategy(
        df, "volatility_breakout", {}, ma_window=5, k=0.5, interval="day",
    )
    assert "target" in out.columns
    assert "range" in out.columns


def test_existing_minute60_path_unchanged():
    """기존 minute60 경로가 여전히 정상 동작."""
    df = _sample_df(48)
    out = enrich_for_strategy(
        df, "volatility_breakout", {}, ma_window=5, k=0.5, interval="minute60",
    )
    assert "target" in out.columns
    assert "range" in out.columns


def test_existing_regime_reclaim_1h_path_unchanged():
    """기존 regime_reclaim_1h 경로가 여전히 정상 동작."""
    # 1H df
    idx_1h = pd.date_range("2026-01-01", periods=200, freq="h")
    df_1h = pd.DataFrame(
        {
            "open":   np.arange(100, 100 + 200, dtype=float),
            "high":   np.arange(110, 110 + 200, dtype=float),
            "low":    np.arange(90,  90  + 200, dtype=float),
            "close":  np.arange(105, 105 + 200, dtype=float),
            "volume": np.ones(200),
        },
        index=idx_1h,
    )

    # daily regime df
    idx_daily = pd.date_range("2026-01-01", periods=10, freq="D")
    df_daily = pd.DataFrame(
        {
            "open":   np.arange(200, 200 + 10, dtype=float),
            "high":   np.arange(210, 210 + 10, dtype=float),
            "low":    np.arange(190, 190  + 10, dtype=float),
            "close":  np.arange(205, 205 + 10, dtype=float),
            "volume": np.ones(10),
        },
        index=idx_daily,
    )

    out = enrich_for_strategy(
        df_1h,
        "regime_reclaim_1h",
        {"daily_regime_ma_window": 5},
        regime_df=df_daily,
        ma_window=5,
        k=0.5,
        interval="minute60",
    )

    assert "daily_regime_on" in out.columns
    assert "daily_regime_sma5" in out.columns
    assert "pullback_return_8" in out.columns

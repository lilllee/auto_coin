from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import enrich_daily, enrich_for_strategy, enrich_sma, fetch_daily
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

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import enrich_daily, fetch_daily
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

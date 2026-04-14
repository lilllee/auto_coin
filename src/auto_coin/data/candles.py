from __future__ import annotations

import pandas as pd
import pyupbit

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def enrich_daily(df: pd.DataFrame, ma_window: int = 5, k: float = 0.5) -> pd.DataFrame:
    """일봉 DataFrame에 전략용 보조 컬럼 추가.

    추가 컬럼:
        - `range`: 전일 (high - low)
        - `target`: 오늘 시가 + 전일 range * k  (변동성 돌파 진입가)
        - `ma{window}`: 종가 N일 이평
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if k <= 0:
        raise ValueError("k must be positive")
    if ma_window < 1:
        raise ValueError("ma_window must be >= 1")

    out = df.copy()
    out["range"] = (out["high"] - out["low"]).shift(1)
    out["target"] = out["open"] + out["range"] * k
    out[f"ma{ma_window}"] = out["close"].rolling(window=ma_window).mean().shift(1)
    return out


def fetch_daily(
    client: UpbitClient,
    ticker: str,
    *,
    count: int = 200,
    ma_window: int = 5,
    k: float = 0.5,
) -> pd.DataFrame:
    """업비트 일봉 조회 → 보조 컬럼 추가된 DataFrame 반환.

    `client`는 throttle/retry 이점을 위해 받지만, `pyupbit.get_ohlcv`는 공개 엔드포인트라
    인증 없이도 동작한다.
    """

    def _fetch() -> pd.DataFrame | None:
        return pyupbit.get_ohlcv(ticker, interval="day", count=count)

    df = client._call(f"get_ohlcv({ticker}, day, {count})", _fetch)
    if df is None or df.empty:
        raise UpbitError(f"no candles returned for {ticker}")
    return enrich_daily(df, ma_window=ma_window, k=k)

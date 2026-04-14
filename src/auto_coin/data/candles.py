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


def enrich_sma(df: pd.DataFrame, window: int = 200) -> pd.DataFrame:
    """SMA 컬럼 추가. shift(1)로 확정 봉 기준."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if window < 2:
        raise ValueError("window must be >= 2")
    out = df.copy()
    col = f"sma{window}"
    if col not in out.columns:
        out[col] = out["close"].rolling(window=window).mean().shift(1)
    return out


def enrich_atr_channel(
    df: pd.DataFrame,
    atr_window: int = 14,
    channel_multiplier: float = 1.0,
) -> pd.DataFrame:
    """ATR 채널 컬럼 추가.

    Added columns:
        - atr{window}: Average True Range
        - upper_channel: low + atr * multiplier (상향 돌파 진입선)
        - lower_channel: high - atr * multiplier (하향 되밀림 청산선)

    shift(1)로 확정 봉 기준.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if channel_multiplier <= 0:
        raise ValueError("channel_multiplier must be > 0")

    out = df.copy()
    # True Range
    high = out["high"]
    low = out["low"]
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_col = f"atr{atr_window}"
    out[atr_col] = tr.rolling(window=atr_window).mean().shift(1)
    out["upper_channel"] = (out["low"] + out[atr_col] * channel_multiplier).shift(1)
    out["lower_channel"] = (out["high"] - out[atr_col] * channel_multiplier).shift(1)
    return out


def enrich_ema_adx(
    df: pd.DataFrame,
    ema_fast: int = 27,
    ema_slow: int = 125,
    adx_window: int = 90,
) -> pd.DataFrame:
    """EMA + ADX 컬럼 추가.

    Added columns:
        - ema{fast}: Exponential Moving Average (fast)
        - ema{slow}: EMA (slow)
        - adx{window}: Average Directional Index

    shift(1)로 확정 봉 기준.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    out = df.copy()

    # EMA
    out[f"ema{ema_fast}"] = out["close"].ewm(span=ema_fast, adjust=False).mean().shift(1)
    out[f"ema{ema_slow}"] = out["close"].ewm(span=ema_slow, adjust=False).mean().shift(1)

    # ADX calculation
    high = out["high"]
    low = out["low"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = out["close"].shift(1)

    # True Range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # +DM, -DM
    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    # Zero out when the other is larger
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0)

    # Smoothed with EWM (Wilder's smoothing = ewm(alpha=1/window))
    atr = tr.ewm(alpha=1 / adx_window, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1 / adx_window, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / adx_window, adjust=False).mean() / atr)

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    dx = dx.replace([float("inf"), float("-inf")], 0).fillna(0)

    out[f"adx{adx_window}"] = dx.ewm(alpha=1 / adx_window, adjust=False).mean().shift(1)

    return out


def enrich_donchian(
    df: pd.DataFrame,
    entry_window: int = 20,
    exit_window: int = 10,
) -> pd.DataFrame:
    """Donchian 채널 컬럼 추가.

    Added columns:
        - donchian_high_{entry_window}: N일 최고가 (진입용)
        - donchian_low_{exit_window}: N일 최저가 (청산용)

    shift(1)로 확정 봉 기준.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if entry_window < 2:
        raise ValueError("entry_window must be >= 2")
    if exit_window < 1:
        raise ValueError("exit_window must be >= 1")

    out = df.copy()
    out[f"donchian_high_{entry_window}"] = out["high"].rolling(window=entry_window).max().shift(1)
    out[f"donchian_low_{exit_window}"] = out["low"].rolling(window=exit_window).min().shift(1)
    return out


def enrich_for_strategy(
    df: pd.DataFrame,
    strategy_name: str,
    strategy_params: dict,
    *,
    ma_window: int = 5,
    k: float = 0.5,
) -> pd.DataFrame:
    """전략에 맞는 보조 컬럼 추가."""
    if strategy_name == "volatility_breakout":
        return enrich_daily(df, ma_window=ma_window, k=k)
    elif strategy_name == "sma200_regime":
        sma_window = strategy_params.get("ma_window", 200)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)  # keep VB columns for backward compat
        return enrich_sma(enriched, window=sma_window)
    elif strategy_name == "atr_channel_breakout":
        atr_window = strategy_params.get("atr_window", 14)
        channel_multiplier = strategy_params.get("channel_multiplier", 1.0)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_atr_channel(
            enriched, atr_window=atr_window, channel_multiplier=channel_multiplier
        )
    elif strategy_name == "ema_adx_atr_trend":
        ema_fast = strategy_params.get("ema_fast_window", 27)
        ema_slow = strategy_params.get("ema_slow_window", 125)
        adx_win = strategy_params.get("adx_window", 90)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_ema_adx(enriched, ema_fast=ema_fast, ema_slow=ema_slow, adx_window=adx_win)
    elif strategy_name == "ad_turtle":
        entry_w = strategy_params.get("entry_window", 20)
        exit_w = strategy_params.get("exit_window", 10)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_donchian(enriched, entry_window=entry_w, exit_window=exit_w)
    else:
        # Default: at least do basic VB enrichment
        return enrich_daily(df, ma_window=ma_window, k=k)


def fetch_daily(
    client: UpbitClient,
    ticker: str,
    *,
    count: int = 200,
    ma_window: int = 5,
    k: float = 0.5,
    strategy_name: str = "volatility_breakout",
    strategy_params: dict | None = None,
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
    return enrich_for_strategy(
        df, strategy_name, strategy_params or {},
        ma_window=ma_window, k=k,
    )

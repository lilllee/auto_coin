from __future__ import annotations

from datetime import datetime

import pandas as pd
import pyupbit

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class _EmptyCandleResponse(UpbitError):
    """pyupbit가 일시적으로 빈 OHLCV 응답을 돌려줄 때의 내부 재시도용 예외."""


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
    atr_window: int = 14,
) -> pd.DataFrame:
    """EMA + ADX 컬럼 추가.

    Added columns:
        - ema{fast}: Exponential Moving Average (fast)
        - ema{slow}: EMA (slow)
        - adx{window}: Average Directional Index
        - atr{window}: Average True Range (risk manager 연동용)

    shift(1)로 확정 봉 기준.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")

    if ema_fast < 1:
        raise ValueError("ema_fast must be >= 1")
    if ema_slow <= ema_fast:
        raise ValueError("ema_slow must be > ema_fast")
    if adx_window < 1:
        raise ValueError("adx_window must be >= 1")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")

    out = df.copy()

    # EMA
    out[f"ema{ema_fast}"] = out["close"].ewm(span=ema_fast, adjust=False).mean().shift(1)
    out[f"ema{ema_slow}"] = out["close"].ewm(span=ema_slow, adjust=False).mean().shift(1)

    # ADX / ATR calculation
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
    out[f"atr{atr_window}"] = tr.rolling(window=atr_window).mean().shift(1)

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


def enrich_rcdb(
    df: pd.DataFrame,
    *,
    regime_ma_window: int = 120,
    dip_lookback_days: int = 5,
    rsi_window: int = 14,
    atr_window: int = 14,
    regime_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """RCDB용 보조 컬럼 추가.

    Added columns:
        - regime_close / regime_sma{window} / regime_on
        - dip_return_{lookback}
        - rsi{window}
        - atr{window}

    `regime_df`가 없으면 동일 자산 종가를 regime reference로 사용한다.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if regime_ma_window < 2:
        raise ValueError("regime_ma_window must be >= 2")
    if dip_lookback_days < 1:
        raise ValueError("dip_lookback_days must be >= 1")
    if rsi_window < 2:
        raise ValueError("rsi_window must be >= 2")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if regime_df is not None:
        regime_missing = [c for c in REQUIRED_COLUMNS if c not in regime_df.columns]
        if regime_missing:
            raise ValueError(f"regime_df missing required columns: {regime_missing}")

    out = df.copy()

    if regime_df is None:
        regime_close = out["close"].rename("regime_close")
    else:
        regime_close = regime_df["close"].rename("regime_close")

    out = out.join(regime_close, how="left")
    regime_sma_col = f"regime_sma{regime_ma_window}"
    out[regime_sma_col] = out["regime_close"].rolling(window=regime_ma_window).mean().shift(1)
    out["regime_on"] = out["regime_close"] >= out[regime_sma_col]

    dip_col = f"dip_return_{dip_lookback_days}"
    out[dip_col] = out["close"] / out["close"].shift(dip_lookback_days) - 1.0

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out[f"rsi{rsi_window}"] = 100 - (100 / (1 + rs))

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
    out[f"atr{atr_window}"] = tr.rolling(window=atr_window).mean().shift(1)
    return out


def enrich_rcdb_v2(
    df: pd.DataFrame,
    *,
    regime_ma_window: int = 120,
    dip_lookback_days: int = 5,
    vol_window: int = 20,
    rsi_window: int = 14,
    reversal_ema_window: int = 5,
    atr_window: int = 14,
    regime_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """RCDB v2용 보조 컬럼 추가.

    Added columns:
        - regime_close / regime_sma{window} / regime_on
        - lookback_return_{n}
        - realized_vol_{window}
        - dip_score_{n}_{window}
        - rsi{window}
        - reversal_ema{window}
        - atr{window}
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if regime_ma_window < 2:
        raise ValueError("regime_ma_window must be >= 2")
    if dip_lookback_days < 1:
        raise ValueError("dip_lookback_days must be >= 1")
    if vol_window < 2:
        raise ValueError("vol_window must be >= 2")
    if rsi_window < 2:
        raise ValueError("rsi_window must be >= 2")
    if reversal_ema_window < 1:
        raise ValueError("reversal_ema_window must be >= 1")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if regime_df is not None:
        regime_missing = [c for c in REQUIRED_COLUMNS if c not in regime_df.columns]
        if regime_missing:
            raise ValueError(f"regime_df missing required columns: {regime_missing}")

    out = df.copy()

    if regime_df is None:
        regime_close = out["close"].rename("regime_close")
    else:
        regime_close = regime_df["close"].rename("regime_close")

    out = out.join(regime_close, how="left")
    regime_sma_col = f"regime_sma{regime_ma_window}"
    out[regime_sma_col] = out["regime_close"].rolling(window=regime_ma_window).mean().shift(1)
    out["regime_on"] = out["regime_close"] >= out[regime_sma_col]

    lookback_col = f"lookback_return_{dip_lookback_days}"
    out[lookback_col] = out["close"] / out["close"].shift(dip_lookback_days) - 1.0

    daily_return = out["close"].pct_change()
    vol_col = f"realized_vol_{vol_window}"
    out[vol_col] = daily_return.rolling(window=vol_window).std(ddof=0).shift(1)
    vol_scale = out[vol_col] * (dip_lookback_days ** 0.5)
    dip_score_col = f"dip_score_{dip_lookback_days}_{vol_window}"
    out[dip_score_col] = out[lookback_col] / vol_scale.replace(0, float("nan"))

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out[f"rsi{rsi_window}"] = 100 - (100 / (1 + rs))

    out[f"reversal_ema{reversal_ema_window}"] = (
        out["close"].ewm(span=reversal_ema_window, adjust=False).mean().shift(1)
    )

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
    out[f"atr{atr_window}"] = tr.rolling(window=atr_window).mean().shift(1)
    return out


def enrich_for_strategy(
    df: pd.DataFrame,
    strategy_name: str,
    strategy_params: dict,
    *,
    ma_window: int = 5,
    k: float = 0.5,
    regime_df: pd.DataFrame | None = None,
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
        atr_win = strategy_params.get("atr_window", 14)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_ema_adx(
            enriched,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            adx_window=adx_win,
            atr_window=atr_win,
        )
    elif strategy_name == "ad_turtle":
        entry_w = strategy_params.get("entry_window", 20)
        exit_w = strategy_params.get("exit_window", 10)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_donchian(enriched, entry_window=entry_w, exit_window=exit_w)
    elif strategy_name == "sma200_ema_adx_composite":
        sma_win = strategy_params.get("sma_window", 200)
        ema_fast = strategy_params.get("ema_fast_window", 27)
        ema_slow = strategy_params.get("ema_slow_window", 125)
        adx_win = strategy_params.get("adx_window", 90)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        enriched = enrich_sma(enriched, window=sma_win)
        return enrich_ema_adx(enriched, ema_fast=ema_fast, ema_slow=ema_slow, adx_window=adx_win)
    elif strategy_name == "rcdb":
        regime_ma_window = strategy_params.get("regime_ma_window", 120)
        dip_lookback_days = strategy_params.get("dip_lookback_days", 5)
        rsi_window = strategy_params.get("rsi_window", 14)
        atr_window = strategy_params.get("atr_window", 14)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_rcdb(
            enriched,
            regime_ma_window=regime_ma_window,
            dip_lookback_days=dip_lookback_days,
            rsi_window=rsi_window,
            atr_window=atr_window,
            regime_df=regime_df,
        )
    elif strategy_name == "rcdb_v2":
        regime_ma_window = strategy_params.get("regime_ma_window", 120)
        dip_lookback_days = strategy_params.get("dip_lookback_days", 5)
        vol_window = strategy_params.get("vol_window", 20)
        rsi_window = strategy_params.get("rsi_window", 14)
        reversal_ema_window = strategy_params.get("reversal_ema_window", 5)
        atr_window = strategy_params.get("atr_window", 14)
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_rcdb_v2(
            enriched,
            regime_ma_window=regime_ma_window,
            dip_lookback_days=dip_lookback_days,
            vol_window=vol_window,
            rsi_window=rsi_window,
            reversal_ema_window=reversal_ema_window,
            atr_window=atr_window,
            regime_df=regime_df,
        )
    else:
        # Default: at least do basic VB enrichment
        return enrich_daily(df, ma_window=ma_window, k=k)


def recommended_history_days(
    strategy_name: str,
    strategy_params: dict | None = None,
    *,
    ma_window: int = 5,
) -> int:
    """전략별 권장 추가 히스토리 길이(일봉 수)를 반환.

    반환값은 "검토 구간 외에 추가로 더 가져올 보수적 warmup 버퍼"다.
    live bot은 이 값을 그대로 `count` 최소치로 사용할 수 있고,
    review 기능은 `review_days + recommended_history_days(...) - 1` 형태로
    총 조회 길이를 만들 수 있다.
    """
    params = strategy_params or {}
    base_window = max(int(ma_window), 1)

    if strategy_name == "volatility_breakout":
        window = max(int(params.get("ma_window", ma_window)), base_window)
    elif strategy_name == "sma200_regime":
        window = max(int(params.get("ma_window", 200)), base_window)
    elif strategy_name == "atr_channel_breakout":
        window = max(int(params.get("atr_window", 14)), base_window)
    elif strategy_name == "ema_adx_atr_trend":
        window = max(
            int(params.get("ema_slow_window", 125)),
            int(params.get("adx_window", 90)),
            base_window,
        )
    elif strategy_name == "ad_turtle":
        window = max(int(params.get("entry_window", 20)), base_window)
    elif strategy_name == "sma200_ema_adx_composite":
        window = max(
            int(params.get("sma_window", 200)),
            int(params.get("ema_slow_window", 125)),
            int(params.get("adx_window", 90)),
            base_window,
        )
    elif strategy_name == "rcdb":
        window = max(
            int(params.get("regime_ma_window", 120)),
            int(params.get("dip_lookback_days", 5)),
            int(params.get("rsi_window", 14)),
            int(params.get("atr_window", 14)),
            base_window,
        )
    elif strategy_name == "rcdb_v2":
        window = max(
            int(params.get("regime_ma_window", 120)),
            int(params.get("dip_lookback_days", 5)),
            int(params.get("vol_window", 20)),
            int(params.get("rsi_window", 14)),
            int(params.get("reversal_ema_window", 5)),
            int(params.get("atr_window", 14)),
            base_window,
        )
    else:
        window = base_window

    return max(window + 50, 60)


def fetch_daily(
    client: UpbitClient,
    ticker: str,
    *,
    count: int = 200,
    ma_window: int = 5,
    k: float = 0.5,
    strategy_name: str = "volatility_breakout",
    strategy_params: dict | None = None,
    to: datetime | str | None = None,
) -> pd.DataFrame:
    """업비트 일봉 조회 → 보조 컬럼 추가된 DataFrame 반환.

    `client`는 throttle/retry 이점을 위해 받지만, `pyupbit.get_ohlcv`는 공개 엔드포인트라
    인증 없이도 동작한다.
    """

    def _fetch() -> pd.DataFrame:
        df = pyupbit.get_ohlcv(ticker, interval="day", count=count, to=to)
        if df is None or df.empty:
            raise _EmptyCandleResponse(f"no candles returned for {ticker}")
        return df

    label = f"get_ohlcv({ticker}, day, {count})"
    if to is not None:
        label = f"{label}, to={to}"

    try:
        df = client._call(label, _fetch)
    except UpbitError as exc:
        cause = exc.__cause__
        if isinstance(cause, _EmptyCandleResponse):
            raise UpbitError(f"no candles returned for {ticker}") from exc
        raise

    regime_df = None
    params = strategy_params or {}
    if strategy_name in {"rcdb", "rcdb_v2"}:
        regime_ticker = params.get("regime_ticker", "KRW-BTC")
        if regime_ticker and regime_ticker != ticker:
            def _fetch_regime() -> pd.DataFrame:
                rdf = pyupbit.get_ohlcv(regime_ticker, interval="day", count=count, to=to)
                if rdf is None or rdf.empty:
                    raise _EmptyCandleResponse(f"no candles returned for {regime_ticker}")
                return rdf

            regime_label = f"get_ohlcv({regime_ticker}, day, {count})"
            if to is not None:
                regime_label = f"{regime_label}, to={to}"
            try:
                regime_df = client._call(regime_label, _fetch_regime)
            except UpbitError as exc:
                cause = exc.__cause__
                if isinstance(cause, _EmptyCandleResponse):
                    raise UpbitError(f"no candles returned for {regime_ticker}") from exc
                raise
    return enrich_for_strategy(
        df, strategy_name, params,
        ma_window=ma_window, k=k,
        regime_df=regime_df,
    )

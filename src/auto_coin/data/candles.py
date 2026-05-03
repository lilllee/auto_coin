from __future__ import annotations

from datetime import datetime

import pandas as pd
import pyupbit

from auto_coin.exchange.upbit_client import UpbitClient, UpbitError

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
_CANDLE_INTERVAL_ALIASES = {
    "day": "day",
    "daily": "day",
    "1d": "day",
    "d": "day",
    "minute60": "minute60",
    "60m": "minute60",
    "1h": "minute60",
    "hour": "minute60",
    "hourly": "minute60",
    "minute30": "minute30",
    "30m": "minute30",
    "30min": "minute30",
}
_CANDLE_INTERVAL_SECONDS = {
    "day": 24 * 60 * 60,
    "minute60": 60 * 60,
    "minute30": 30 * 60,
}


class _EmptyCandleResponse(UpbitError):
    """pyupbit가 일시적으로 빈 OHLCV 응답을 돌려줄 때의 내부 재시도용 예외."""


def normalize_candle_interval(interval: str) -> str:
    """프로젝트 내부 candle interval alias를 Upbit/pyupbit canonical 값으로 정규화."""
    normalized = _CANDLE_INTERVAL_ALIASES.get(str(interval).strip().lower())
    if normalized is None:
        supported = ", ".join(sorted(set(_CANDLE_INTERVAL_ALIASES.keys())))
        raise ValueError(f"unsupported candle interval: {interval!r} (supported: {supported})")
    return normalized


def candle_bar_seconds(interval: str) -> int:
    """캔들 하나가 대표하는 시간(초)."""
    return _CANDLE_INTERVAL_SECONDS[normalize_candle_interval(interval)]


def history_days_to_candles(days: int, interval: str = "day") -> int:
    """일수 기반 lookback을 interval별 candle 수로 변환.

    - day: N일 -> N candles
    - minute60: N일 -> N*24 candles
    - minute30: N일 -> N*48 candles
    """
    if days < 1:
        raise ValueError("days must be >= 1")
    bar_seconds = candle_bar_seconds(interval)
    return max(int(days * (24 * 60 * 60) / bar_seconds), 1)


def project_higher_timeframe_features(
    feature_df: pd.DataFrame,
    target_index: pd.Index,
    *,
    columns: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """상위 프레임 feature를 하위 프레임 인덱스로 forward-fill 투영.

    멀티 타임프레임 전략의 핵심 빌딩 블록:
    - daily → minute60 (1H): regime_on / regime SMA 투영
    - daily → minute30 (30m): regime_on / regime SMA 투영
    - minute60 → minute30: 1H setup feature → 30m trigger 투영

    예: 일봉에서 계산한 regime_on / regime_sma120을 1H 또는 30m 인덱스에 맞춰 펼친다.
    """
    if feature_df.empty:
        raise ValueError("feature_df must not be empty")
    if len(target_index) == 0:
        raise ValueError("target_index must not be empty")

    projected = feature_df.copy()
    if columns is not None:
        projected = projected.loc[:, list(columns)]
    projected = projected.sort_index()
    union_index = projected.index.union(target_index)
    with pd.option_context("future.no_silent_downcasting", True):
        projected = projected.reindex(union_index).sort_index().ffill().infer_objects(copy=False)
    return projected.reindex(target_index)


def project_features(
    source_df: pd.DataFrame,
    target_index: pd.Index,
    *,
    source_interval: str,
    target_interval: str,
    columns: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """상위/동일/하위 프레임 간 feature projection.

    멀티 타임프레임 전략(daily regime + 1H setup + 30m trigger)을 위한
    일반화 projection helper.

    - source_interval > target_interval: ffill (예: daily→1H, 1H→30m)
    - source_interval == target_interval: 단순 reindex
    - source_interval < target_interval: bfill (예: 30m→1H, 드묾)

    Args:
        source_df: feature가 있는 DataFrame (index는 해당 타임프레임 timestamp).
        target_index: feature를 투영할 하위/동일 프레임 인덱스.
        source_interval: source_df의 interval (canonical).
        target_interval: target_index의 interval (canonical).
        columns: 투영할 컬럼 목록. None이면 전체.

    Returns:
        target_index에 맞춰 reindex + forward-fill 된 DataFrame.
    """
    if source_df.empty:
        raise ValueError("source_df must not be empty")
    if len(target_index) == 0:
        raise ValueError("target_index must not be empty")

    src_norm = normalize_candle_interval(source_interval)
    tgt_norm = normalize_candle_interval(target_interval)
    src_secs = candle_bar_seconds(src_norm)
    tgt_secs = candle_bar_seconds(tgt_norm)

    projected = source_df.copy()
    if columns is not None:
        projected = projected.loc[:, list(columns)]
    projected = projected.sort_index()

    union_index = projected.index.union(target_index)
    projected = projected.reindex(union_index).sort_index().infer_objects(copy=False)

    # 상위 → 하위: ffill (더 새로운 상위 값을 하위에 전파)
    # 동일: 그냥 reindex
    # 하위 → 상위: bfill (더 오래된 하위 값을 상위에 전파 — 드묾)
    if src_secs > tgt_secs:
        projected = projected.ffill()
    elif src_secs < tgt_secs:
        projected = projected.bfill()

    return projected.reindex(target_index)


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


def enrich_regime_reclaim_1h(
    df: pd.DataFrame,
    *,
    daily_regime_ma_window: int = 120,
    dip_lookback_bars: int = 8,
    pullback_threshold_pct: float = -0.025,
    rsi_window: int = 14,
    reclaim_ema_window: int = 6,
    atr_window: int = 14,
    regime_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Daily regime + 1H reclaim mean reversion용 보조 컬럼 추가.

    P0 이후 첫 1H 전략 발판:
    - regime_df가 일봉이면 regime_on / regime SMA를 1H 인덱스로 투영
    - entry는 1H dip + RSI + reclaim 조건으로 판단
    - exit는 reversion baseline / trailing / regime_off / time_exit를 사용
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if daily_regime_ma_window < 2:
        raise ValueError("daily_regime_ma_window must be >= 2")
    if dip_lookback_bars < 1:
        raise ValueError("dip_lookback_bars must be >= 1")
    if pullback_threshold_pct >= 0:
        raise ValueError("pullback_threshold_pct must be < 0")
    if rsi_window < 2:
        raise ValueError("rsi_window must be >= 2")
    if reclaim_ema_window < 1:
        raise ValueError("reclaim_ema_window must be >= 1")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if regime_df is not None:
        regime_missing = [c for c in REQUIRED_COLUMNS if c not in regime_df.columns]
        if regime_missing:
            raise ValueError(f"regime_df missing required columns: {regime_missing}")

    out = df.copy()

    if regime_df is None:
        regime_source = out[["close"]].rename(columns={"close": "regime_close"})
        regime_source[f"daily_regime_sma{daily_regime_ma_window}"] = (
            regime_source["regime_close"]
            .rolling(window=daily_regime_ma_window)
            .mean()
            .shift(1)
        )
        regime_source["daily_regime_on"] = (
            regime_source["regime_close"] >= regime_source[f"daily_regime_sma{daily_regime_ma_window}"]
        )
        projected = regime_source[[
            "regime_close",
            f"daily_regime_sma{daily_regime_ma_window}",
            "daily_regime_on",
        ]]
    else:
        regime_source = regime_df.copy()
        regime_source["regime_close"] = regime_source["close"]
        regime_source[f"daily_regime_sma{daily_regime_ma_window}"] = (
            regime_source["close"].rolling(window=daily_regime_ma_window).mean().shift(1)
        )
        regime_source["daily_regime_on"] = (
            regime_source["close"] >= regime_source[f"daily_regime_sma{daily_regime_ma_window}"]
        )
        projected = project_higher_timeframe_features(
            regime_source,
            out.index,
            columns=[
                "regime_close",
                f"daily_regime_sma{daily_regime_ma_window}",
                "daily_regime_on",
            ],
        )

    out = out.join(projected, how="left")

    pullback_col = f"pullback_return_{dip_lookback_bars}"
    out[pullback_col] = out["close"] / out["close"].shift(dip_lookback_bars) - 1.0
    out[f"pullback_threshold_{dip_lookback_bars}"] = pullback_threshold_pct

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out[f"rsi{rsi_window}"] = 100 - (100 / (1 + rs))

    out[f"reclaim_ema{reclaim_ema_window}"] = (
        out["close"].ewm(span=reclaim_ema_window, adjust=False).mean().shift(1)
    )
    out[f"reversion_sma{dip_lookback_bars}"] = (
        out["close"].rolling(window=dip_lookback_bars).mean().shift(1)
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


def enrich_regime_reclaim_30m(
    df: pd.DataFrame,
    *,
    daily_regime_df: pd.DataFrame | None = None,
    daily_regime_ma_window: int = 120,
    hourly_setup_df: pd.DataFrame | None = None,
    hourly_pullback_bars: int = 8,
    hourly_pullback_threshold_pct: float = -0.025,
    dip_lookback_bars: int = 8,
    pullback_threshold_pct: float = -0.025,
    rsi_window: int = 14,
    reclaim_ema_window: int = 6,
    reversion_sma_window: int | None = None,
    atr_window: int = 14,
) -> pd.DataFrame:
    """Daily regime + 1H setup + 30m trigger 전략용 보조 컬럼 추가.

    멀티 타임프레임 구조:
    - Daily: regime_on / regime SMA (daily_regime_df 또는 df 자체에서 계산)
    - 1H: pullback / oversold setup (hourly_setup_df 에서 계산 후 30m 인덱스로 투영)
    - 30m: reclaim trigger (df 자체에서 계산)

    Args:
        df: 30m candle DataFrame (trigger 기준).
        daily_regime_df: 일봉 DataFrame. None이면 df 자체에서 regime 계산.
        hourly_setup_df: 1H candle DataFrame. None이면 30m df 로 fallback.
        daily_regime_ma_window: 일봉 regime SMA 윈도우.
        hourly_pullback_bars: 1H pullback lookback 바 수.
        hourly_pullback_threshold_pct: 1H pullback 임계값.
        dip_lookback_bars: 30m dip lookback 바 수.
        pullback_threshold_pct: 30m pullback 임계값.
        rsi_window: RSI 윈도우.
        reclaim_ema_window: reclaim EMA 윈도우.
        reversion_sma_window: reversion_exit 목표 SMA 윈도우. None이면 dip_lookback_bars 사용.
        atr_window: ATR 윈도우.

    Added columns (30m df 기준):
        - daily_regime_close / daily_regime_sma{N} / daily_regime_on (daily→30m 투영)
        - hourly_pullback_return_{N} / hourly_pullback_threshold (1H setup→30m 투영)
        - pullback_return_{N} / pullback_threshold (30m 자체)
        - rsi{N}, reclaim_ema{N}, reversion_sma{N}, atr{N}

    Usage pattern for next-turn strategy:
        # fetch 30m candles (trigger), daily candles (regime), 1H candles (setup)
        df30 = fetch_candles(client, ticker, interval="minute30", ...)
        df_daily = fetch_candles(client, ticker, interval="day", ...)
        df_1h = fetch_candles(client, ticker, interval="minute60", ...)
        # enrich 30m with multi-TF features
        enriched = enrich_regime_reclaim_30m(
            df30,
            daily_regime_df=df_daily,
            hourly_setup_df=df_1h,
            daily_regime_ma_window=120,
            hourly_pullback_bars=8,
            ...
        )
        # strategy generates signal from enriched 30m df
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if daily_regime_ma_window < 2:
        raise ValueError("daily_regime_ma_window must be >= 2")
    if dip_lookback_bars < 1:
        raise ValueError("dip_lookback_bars must be >= 1")
    if pullback_threshold_pct >= 0:
        raise ValueError("pullback_threshold_pct must be < 0")
    if rsi_window < 2:
        raise ValueError("rsi_window must be >= 2")
    if reclaim_ema_window < 1:
        raise ValueError("reclaim_ema_window must be >= 1")
    if reversion_sma_window is not None and reversion_sma_window < 1:
        raise ValueError("reversion_sma_window must be >= 1 when set")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if daily_regime_df is not None:
        regime_missing = [c for c in REQUIRED_COLUMNS if c not in daily_regime_df.columns]
        if regime_missing:
            raise ValueError(f"daily_regime_df missing required columns: {regime_missing}")
    if hourly_setup_df is not None:
        setup_missing = [c for c in REQUIRED_COLUMNS if c not in hourly_setup_df.columns]
        if setup_missing:
            raise ValueError(f"hourly_setup_df missing required columns: {setup_missing}")

    out = df.copy()

    # --- Daily regime projection onto 30m index ---
    if daily_regime_df is not None:
        regime_source = daily_regime_df.copy()
        regime_source["regime_close"] = regime_source["close"]
        regime_source[f"daily_regime_sma{daily_regime_ma_window}"] = (
            regime_source["close"].rolling(window=daily_regime_ma_window).mean().shift(1)
        )
        regime_source["daily_regime_on"] = (
            regime_source["close"] >= regime_source[f"daily_regime_sma{daily_regime_ma_window}"]
        )
        daily_features = project_higher_timeframe_features(
            regime_source,
            out.index,
            columns=[
                "regime_close",
                f"daily_regime_sma{daily_regime_ma_window}",
                "daily_regime_on",
            ],
        )
    else:
        # Fallback: compute regime from 30m df itself (same-asset, no cross-TF)
        regime_source = out[["close"]].rename(columns={"close": "regime_close"})
        regime_source[f"daily_regime_sma{daily_regime_ma_window}"] = (
            regime_source["regime_close"]
            .rolling(window=daily_regime_ma_window)
            .mean()
            .shift(1)
        )
        regime_source["daily_regime_on"] = (
            regime_source["regime_close"] >= regime_source[f"daily_regime_sma{daily_regime_ma_window}"]
        )
        daily_features = regime_source[[
            "regime_close",
            f"daily_regime_sma{daily_regime_ma_window}",
            "daily_regime_on",
        ]]

    out = out.join(daily_features, how="left")

    # --- 1H setup projection onto 30m index ---
    if hourly_setup_df is not None:
        # Compute 1H pullback features
        setup = hourly_setup_df.copy()
        setup["regime_close"] = setup["close"]
        setup[f"hourly_pullback_return_{hourly_pullback_bars}"] = (
            setup["close"] / setup["close"].shift(hourly_pullback_bars) - 1.0
        )
        setup[f"hourly_pullback_threshold_{hourly_pullback_bars}"] = hourly_pullback_threshold_pct
        setup_cols = [
            f"hourly_pullback_return_{hourly_pullback_bars}",
            f"hourly_pullback_threshold_{hourly_pullback_bars}",
        ]
        hourly_features = project_higher_timeframe_features(
            setup,
            out.index,
            columns=setup_cols,
        )
        out = out.join(hourly_features, how="left")
    else:
        # Fallback: use 30m df's own pullback features as 1H setup proxy
        # out 에 직접 추가 (join 불필요 — 이미 같은 index)
        pullback_col = f"hourly_pullback_return_{hourly_pullback_bars}"
        threshold_col = f"hourly_pullback_threshold_{hourly_pullback_bars}"
        if pullback_col not in out.columns:
            out[pullback_col] = out["close"] / out["close"].shift(hourly_pullback_bars) - 1.0
        if threshold_col not in out.columns:
            out[threshold_col] = hourly_pullback_threshold_pct

    # --- 30m trigger features ---
    pullback_col = f"pullback_return_{dip_lookback_bars}"
    out[pullback_col] = out["close"] / out["close"].shift(dip_lookback_bars) - 1.0
    out[f"pullback_threshold_{dip_lookback_bars}"] = pullback_threshold_pct

    delta = out["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    avg_loss = loss.ewm(alpha=1 / rsi_window, adjust=False, min_periods=rsi_window).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out[f"rsi{rsi_window}"] = 100 - (100 / (1 + rs))

    out[f"reclaim_ema{reclaim_ema_window}"] = (
        out["close"].ewm(span=reclaim_ema_window, adjust=False).mean().shift(1)
    )
    reversion_window = reversion_sma_window or dip_lookback_bars
    out[f"reversion_sma{reversion_window}"] = (
        out["close"].rolling(window=reversion_window).mean().shift(1)
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


def enrich_vwap_ema_pullback(
    df: pd.DataFrame,
    *,
    ema_period: int = 9,
    vwap_period: int = 48,
    sideways_lookback: int = 12,
    max_vwap_cross_count: int = 3,
    min_ema_slope_ratio: float = 0.001,
    use_volume_profile: bool = False,
    volume_profile_lookback: int = 48,
    volume_profile_bin_count: int = 24,
    volume_gap_threshold: float = 0.3,
    atr_window: int = 14,
) -> pd.DataFrame:
    """VWAP + EMA pullback 전략용 보조 컬럼 추가.

    Added columns:
        - ema{ema_period}: shifted EMA, completed-candle convention
        - vwap: shifted rolling candle VWAP based on HLC3 and volume
        - vwap_above: close > shifted VWAP
        - vwap_cross_count: recent close/VWAP side changes
        - ema_slope_ratio: shifted EMA slope over ``sideways_lookback`` bars
        - is_sideways: choppy VWAP crosses or flat EMA slope

    Volume Profile is intentionally not implemented in Phase 1; parameters are
    accepted only for forward-compatible strategy configuration.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if ema_period < 1:
        raise ValueError("ema_period must be >= 1")
    if vwap_period < 1:
        raise ValueError("vwap_period must be >= 1")
    if sideways_lookback < 1:
        raise ValueError("sideways_lookback must be >= 1")
    if max_vwap_cross_count < 0:
        raise ValueError("max_vwap_cross_count must be >= 0")
    if min_ema_slope_ratio < 0:
        raise ValueError("min_ema_slope_ratio must be >= 0")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if volume_profile_lookback < 1:
        raise ValueError("volume_profile_lookback must be >= 1")
    if volume_profile_bin_count < 1:
        raise ValueError("volume_profile_bin_count must be >= 1")
    if volume_gap_threshold < 0:
        raise ValueError("volume_gap_threshold must be >= 0")

    out = df.copy()
    ema_col = f"ema{ema_period}"
    out[ema_col] = out["close"].ewm(span=ema_period, adjust=False).mean().shift(1)

    typical_price = (out["high"] + out["low"] + out["close"]) / 3.0
    volume = out["volume"].where(out["volume"].notna(), 0.0)
    numerator = (typical_price * volume).rolling(window=vwap_period).sum()
    denominator = volume.rolling(window=vwap_period).sum()
    raw_vwap = numerator / denominator.replace(0, float("nan"))
    out["vwap"] = raw_vwap.shift(1)

    out["vwap_above"] = (out["close"] > out["vwap"]).astype("boolean")
    out.loc[out["vwap"].isna() | out["close"].isna(), "vwap_above"] = pd.NA
    side = out["vwap_above"]
    cross = side.ne(side.shift(1)) & side.notna() & side.shift(1).notna()
    out["vwap_cross_count"] = cross.astype("int").rolling(window=sideways_lookback).sum()

    out["ema_slope_ratio"] = (
        (out[ema_col] - out[ema_col].shift(sideways_lookback))
        / out[ema_col].shift(sideways_lookback).replace(0, float("nan"))
    )
    out["is_sideways"] = (
        (out["vwap_cross_count"] > max_vwap_cross_count)
        | (out["ema_slope_ratio"].abs() < min_ema_slope_ratio)
    )
    out.loc[out["vwap_cross_count"].isna() | out["ema_slope_ratio"].isna(), "is_sideways"] = False

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

    if use_volume_profile:
        # Placeholder column for future Phase 2/3 implementations.  It stays
        # False so enabling the option cannot silently approximate profile logic.
        out["volume_profile_ok"] = False
    return out


def _rsi(close: pd.Series, window: int) -> pd.Series:
    """Wilder-style EWM RSI used by intraday strategy enrichers."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def enrich_regime_pullback_continuation_30m(
    df: pd.DataFrame,
    *,
    daily_regime_df: pd.DataFrame | None = None,
    daily_regime_ma_window: int = 100,
    hourly_setup_df: pd.DataFrame | None = None,
    trend_ema_fast_1h: int = 20,
    trend_ema_slow_1h: int = 60,
    trend_slope_lookback_1h: int = 3,
    pullback_lookback_1h: int = 8,
    setup_rsi_window: int = 14,
    setup_rsi_recent_window_1h: int | None = None,
    trigger_ema_fast_30m: int = 8,
    trigger_ema_slow_30m: int = 21,
    trigger_breakout_lookback_30m: int = 6,
    trigger_volume_window_30m: int = 20,
    atr_window: int = 14,
) -> pd.DataFrame:
    """Daily regime + 1H pullback + 30m continuation strategy features.

    This enricher is intentionally separate from ``regime_reclaim_30m`` because
    the thesis is continuation, not shallow mean reversion.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if daily_regime_ma_window < 2:
        raise ValueError("daily_regime_ma_window must be >= 2")
    if trend_ema_fast_1h < 1:
        raise ValueError("trend_ema_fast_1h must be >= 1")
    if trend_ema_slow_1h <= trend_ema_fast_1h:
        raise ValueError("trend_ema_slow_1h must be > trend_ema_fast_1h")
    if trend_slope_lookback_1h < 1:
        raise ValueError("trend_slope_lookback_1h must be >= 1")
    if pullback_lookback_1h < 1:
        raise ValueError("pullback_lookback_1h must be >= 1")
    if setup_rsi_window < 2:
        raise ValueError("setup_rsi_window must be >= 2")
    if trigger_ema_fast_30m < 1:
        raise ValueError("trigger_ema_fast_30m must be >= 1")
    if trigger_ema_slow_30m <= trigger_ema_fast_30m:
        raise ValueError("trigger_ema_slow_30m must be > trigger_ema_fast_30m")
    if trigger_breakout_lookback_30m < 1:
        raise ValueError("trigger_breakout_lookback_30m must be >= 1")
    if trigger_volume_window_30m < 1:
        raise ValueError("trigger_volume_window_30m must be >= 1")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if daily_regime_df is not None:
        regime_missing = [c for c in REQUIRED_COLUMNS if c not in daily_regime_df.columns]
        if regime_missing:
            raise ValueError(f"daily_regime_df missing required columns: {regime_missing}")
    if hourly_setup_df is not None:
        setup_missing = [c for c in REQUIRED_COLUMNS if c not in hourly_setup_df.columns]
        if setup_missing:
            raise ValueError(f"hourly_setup_df missing required columns: {setup_missing}")

    out = df.copy()
    rsi_recent_window = setup_rsi_recent_window_1h or pullback_lookback_1h

    # --- Daily/BTC regime projection ---
    if daily_regime_df is not None:
        regime_source = daily_regime_df.copy()
        regime_source["regime_close"] = regime_source["close"]
        regime_source[f"daily_regime_sma{daily_regime_ma_window}"] = (
            regime_source["close"].rolling(window=daily_regime_ma_window).mean().shift(1)
        )
        regime_source["daily_regime_on"] = (
            regime_source["close"] >= regime_source[f"daily_regime_sma{daily_regime_ma_window}"]
        )
        daily_features = project_higher_timeframe_features(
            regime_source,
            out.index,
            columns=[
                "regime_close",
                f"daily_regime_sma{daily_regime_ma_window}",
                "daily_regime_on",
            ],
        )
    else:
        regime_source = out[["close"]].rename(columns={"close": "regime_close"})
        regime_source[f"daily_regime_sma{daily_regime_ma_window}"] = (
            regime_source["regime_close"].rolling(window=daily_regime_ma_window).mean().shift(1)
        )
        regime_source["daily_regime_on"] = (
            regime_source["regime_close"] >= regime_source[f"daily_regime_sma{daily_regime_ma_window}"]
        )
        daily_features = regime_source[
            ["regime_close", f"daily_regime_sma{daily_regime_ma_window}", "daily_regime_on"]
        ]
    out = out.join(daily_features, how="left")

    # --- 1H trend / pullback setup projection ---
    setup = hourly_setup_df.copy() if hourly_setup_df is not None else out.copy()
    setup["hourly_close"] = setup["close"]
    setup[f"hourly_ema_fast{trend_ema_fast_1h}"] = (
        setup["close"].ewm(span=trend_ema_fast_1h, adjust=False).mean().shift(1)
    )
    setup[f"hourly_ema_slow{trend_ema_slow_1h}"] = (
        setup["close"].ewm(span=trend_ema_slow_1h, adjust=False).mean().shift(1)
    )
    setup[f"hourly_ema_fast_slope{trend_slope_lookback_1h}"] = (
        setup[f"hourly_ema_fast{trend_ema_fast_1h}"]
        - setup[f"hourly_ema_fast{trend_ema_fast_1h}"].shift(trend_slope_lookback_1h)
    )
    setup["hourly_trend_on"] = (
        setup[f"hourly_ema_fast{trend_ema_fast_1h}"]
        > setup[f"hourly_ema_slow{trend_ema_slow_1h}"]
    )
    setup[f"hourly_pullback_return_{pullback_lookback_1h}"] = (
        setup["close"] / setup["close"].shift(pullback_lookback_1h) - 1.0
    )
    setup[f"hourly_rsi{setup_rsi_window}"] = _rsi(setup["close"], setup_rsi_window)
    setup[f"hourly_rsi_recent_min{rsi_recent_window}"] = (
        setup[f"hourly_rsi{setup_rsi_window}"]
        .rolling(window=rsi_recent_window)
        .min()
        .shift(1)
    )
    hourly_cols = [
        "hourly_close",
        f"hourly_ema_fast{trend_ema_fast_1h}",
        f"hourly_ema_slow{trend_ema_slow_1h}",
        f"hourly_ema_fast_slope{trend_slope_lookback_1h}",
        "hourly_trend_on",
        f"hourly_pullback_return_{pullback_lookback_1h}",
        f"hourly_rsi{setup_rsi_window}",
        f"hourly_rsi_recent_min{rsi_recent_window}",
    ]
    if hourly_setup_df is not None:
        out = out.join(
            project_higher_timeframe_features(setup, out.index, columns=hourly_cols),
            how="left",
        )
    else:
        out = out.join(setup[hourly_cols], how="left", rsuffix="_setup")

    # --- 30m momentum trigger features ---
    out[f"trigger_ema_fast{trigger_ema_fast_30m}"] = (
        out["close"].ewm(span=trigger_ema_fast_30m, adjust=False).mean().shift(1)
    )
    out[f"trigger_ema_slow{trigger_ema_slow_30m}"] = (
        out["close"].ewm(span=trigger_ema_slow_30m, adjust=False).mean().shift(1)
    )
    out[f"trigger_recent_high{trigger_breakout_lookback_30m}"] = (
        out["high"].rolling(window=trigger_breakout_lookback_30m).max().shift(1)
    )
    out[f"trigger_volume_mean{trigger_volume_window_30m}"] = (
        out["volume"].rolling(window=trigger_volume_window_30m).mean().shift(1)
    )
    candle_range = out["high"] - out["low"]
    out["close_location_value"] = (
        (out["close"] - out["low"]) / candle_range.where(candle_range != 0)
    ).fillna(0.5)
    out[f"rsi{setup_rsi_window}"] = _rsi(out["close"], setup_rsi_window)

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


def enrich_regime_relative_breakout_30m(
    df: pd.DataFrame,
    *,
    daily_regime_df: pd.DataFrame | None = None,
    daily_regime_ma_window: int = 100,
    hourly_setup_df: pd.DataFrame | None = None,
    hourly_ema_fast: int = 20,
    hourly_ema_slow: int = 60,
    hourly_slope_lookback: int = 3,
    rs_reference_df: pd.DataFrame | None = None,
    rs_24h_bars_30m: int = 48,
    rs_7d_bars_30m: int = 336,
    breakout_lookback_30m: int = 6,
    volume_window_30m: int = 20,
    atr_window: int = 14,
) -> pd.DataFrame:
    """Daily BTC regime + alt RS vs BTC + 1H trend + 30m breakout features.

    No-lookahead safeguards:

    - ``btc_daily_regime_on`` uses ``shift(1)`` at the daily level so that an
      intra-day 30m bar sees only the last completed daily regime.
    - All 1H features are ``shift(1)`` at the hourly level so that 30m bars
      inside the currently forming 1H bar use the previous completed hour.
    - ``prior_high_N`` and ``volume_ma_N`` are ``shift(1)`` at the 30m level.
    - Relative-strength uses ``close.shift(bars)`` which only looks backward.

    Side note: this enricher intentionally does not compute ``close_location_value``
    with a shift — CLV is a same-bar candle shape metric.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    if daily_regime_ma_window < 2:
        raise ValueError("daily_regime_ma_window must be >= 2")
    if hourly_ema_fast < 1:
        raise ValueError("hourly_ema_fast must be >= 1")
    if hourly_ema_slow <= hourly_ema_fast:
        raise ValueError("hourly_ema_slow must be > hourly_ema_fast")
    if hourly_slope_lookback < 1:
        raise ValueError("hourly_slope_lookback must be >= 1")
    if rs_24h_bars_30m < 1:
        raise ValueError("rs_24h_bars_30m must be >= 1")
    if rs_7d_bars_30m <= rs_24h_bars_30m:
        raise ValueError("rs_7d_bars_30m must be > rs_24h_bars_30m")
    if breakout_lookback_30m < 1:
        raise ValueError("breakout_lookback_30m must be >= 1")
    if volume_window_30m < 1:
        raise ValueError("volume_window_30m must be >= 1")
    if atr_window < 1:
        raise ValueError("atr_window must be >= 1")
    if daily_regime_df is not None:
        regime_missing = [c for c in REQUIRED_COLUMNS if c not in daily_regime_df.columns]
        if regime_missing:
            raise ValueError(f"daily_regime_df missing required columns: {regime_missing}")
    if hourly_setup_df is not None:
        hourly_missing = [c for c in REQUIRED_COLUMNS if c not in hourly_setup_df.columns]
        if hourly_missing:
            raise ValueError(f"hourly_setup_df missing required columns: {hourly_missing}")
    if rs_reference_df is not None and "close" not in rs_reference_df.columns:
        raise ValueError("rs_reference_df must contain 'close' column")

    out = df.copy()

    # --- 30m breakout/volume/CLV features ---
    prior_high_col = f"prior_high_{breakout_lookback_30m}"
    volume_ma_col = f"volume_ma_{volume_window_30m}"
    out[prior_high_col] = out["high"].rolling(window=breakout_lookback_30m).max().shift(1)
    out[volume_ma_col] = out["volume"].rolling(window=volume_window_30m).mean().shift(1)
    candle_range = out["high"] - out["low"]
    out["close_location_value"] = (
        (out["close"] - out["low"]) / candle_range.where(candle_range > 0)
    ).fillna(0.5)
    out["volume_ratio"] = out["volume"] / out[volume_ma_col]

    # --- daily BTC regime, no-lookahead (previous completed day only) ---
    regime_source_df = daily_regime_df if daily_regime_df is not None else out
    regime_close = regime_source_df["close"]
    regime_sma_col = f"daily_regime_sma{daily_regime_ma_window}"
    daily_frame = pd.DataFrame(index=regime_source_df.index)
    daily_frame[regime_sma_col] = regime_close.rolling(window=daily_regime_ma_window).mean().shift(1)
    # regime_on computed from close[d] vs sma[d-1]; then shifted by 1 daily bar so
    # intraday 30m bars only consume day d-1's fully-confirmed regime value.
    raw_regime_on = (regime_close >= daily_frame[regime_sma_col]).astype("boolean")
    daily_frame["btc_daily_regime_on"] = raw_regime_on.shift(1)
    if daily_regime_df is not None:
        daily_projection = project_higher_timeframe_features(
            daily_frame,
            out.index,
            columns=["btc_daily_regime_on"],
        )
        out["btc_daily_regime_on"] = daily_projection["btc_daily_regime_on"]
    else:
        out["btc_daily_regime_on"] = daily_frame["btc_daily_regime_on"]

    # --- 1H trend features, no-lookahead ---
    setup_df = hourly_setup_df if hourly_setup_df is not None else out
    hourly_feats = pd.DataFrame(index=setup_df.index)
    hourly_close = setup_df["close"]
    fast_col = f"hourly_ema{hourly_ema_fast}"
    slow_col = f"hourly_ema{hourly_ema_slow}"
    slope_col = f"hourly_ema{hourly_ema_fast}_slope_{hourly_slope_lookback}"
    below_col = f"hourly_close_below_ema{hourly_ema_fast}"
    run_col = f"{below_col}_run"

    hourly_feats["hourly_close"] = hourly_close
    hourly_feats[fast_col] = hourly_close.ewm(span=hourly_ema_fast, adjust=False).mean()
    hourly_feats[slow_col] = hourly_close.ewm(span=hourly_ema_slow, adjust=False).mean()
    hourly_feats[slope_col] = (
        hourly_feats[fast_col] - hourly_feats[fast_col].shift(hourly_slope_lookback)
    )
    below = (hourly_feats["hourly_close"] < hourly_feats[fast_col]).astype("int")
    # Consecutive run length of True (below) values at each 1H bar (resets at False).
    breaks = (below == 0).cumsum()
    hourly_feats[run_col] = below.groupby(breaks).cumsum()
    hourly_feats[below_col] = below.astype(bool)

    hourly_cols = ["hourly_close", fast_col, slow_col, slope_col, below_col, run_col]
    hourly_shifted = hourly_feats[hourly_cols].shift(1)
    if hourly_setup_df is not None:
        hourly_projection = project_higher_timeframe_features(
            hourly_shifted,
            out.index,
            columns=hourly_cols,
        )
        out = out.join(hourly_projection, how="left")
    else:
        # Same-frame fallback: the df is being used as its own hourly source, just align by index.
        out = out.join(hourly_shifted, how="left", rsuffix="_setup")

    # --- relative strength vs BTC on 30m grid ---
    if rs_reference_df is not None:
        btc_close_aligned = rs_reference_df["close"].reindex(out.index).ffill()
    else:
        btc_close_aligned = out["close"]
    target_close = out["close"]
    out["target_rs_24h_vs_btc"] = (
        (target_close / target_close.shift(rs_24h_bars_30m) - 1.0)
        - (btc_close_aligned / btc_close_aligned.shift(rs_24h_bars_30m) - 1.0)
    )
    out["target_rs_7d_vs_btc"] = (
        (target_close / target_close.shift(rs_7d_bars_30m) - 1.0)
        - (btc_close_aligned / btc_close_aligned.shift(rs_7d_bars_30m) - 1.0)
    )

    # --- ATR for stop/trailing ---
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
    hourly_setup_df: pd.DataFrame | None = None,
    rs_reference_df: pd.DataFrame | None = None,
    interval: str = "day",
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
    elif strategy_name == "regime_reclaim_1h":
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_regime_reclaim_1h(
            enriched,
            daily_regime_ma_window=strategy_params.get("daily_regime_ma_window", 120),
            dip_lookback_bars=strategy_params.get("dip_lookback_bars", 8),
            pullback_threshold_pct=strategy_params.get("pullback_threshold_pct", -0.025),
            rsi_window=strategy_params.get("rsi_window", 14),
            reclaim_ema_window=strategy_params.get("reclaim_ema_window", 6),
            atr_window=strategy_params.get("atr_window", 14),
            regime_df=regime_df,
        )
    elif strategy_name == "vwap_ema_pullback":
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_vwap_ema_pullback(
            enriched,
            ema_period=strategy_params.get("ema_period", 9),
            vwap_period=strategy_params.get("vwap_period", 48),
            sideways_lookback=strategy_params.get("sideways_lookback", 12),
            max_vwap_cross_count=strategy_params.get("max_vwap_cross_count", 3),
            min_ema_slope_ratio=strategy_params.get("min_ema_slope_ratio", 0.001),
            use_volume_profile=strategy_params.get("use_volume_profile", False),
            volume_profile_lookback=strategy_params.get("volume_profile_lookback", 48),
            volume_profile_bin_count=strategy_params.get("volume_profile_bin_count", 24),
            volume_gap_threshold=strategy_params.get("volume_gap_threshold", 0.3),
            atr_window=strategy_params.get("atr_window", 14),
        )
    elif strategy_name == "regime_reclaim_30m":
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_regime_reclaim_30m(
            enriched,
            daily_regime_df=regime_df,
            daily_regime_ma_window=strategy_params.get("daily_regime_ma_window", 120),
            hourly_setup_df=hourly_setup_df,
            hourly_pullback_bars=strategy_params.get("hourly_pullback_bars", 8),
            hourly_pullback_threshold_pct=strategy_params.get("hourly_pullback_threshold_pct", -0.025),
            dip_lookback_bars=strategy_params.get("hourly_pullback_bars", 8),
            pullback_threshold_pct=strategy_params.get("hourly_pullback_threshold_pct", -0.025),
            rsi_window=strategy_params.get("setup_rsi_window", strategy_params.get("rsi_window", 14)),
            reclaim_ema_window=strategy_params.get("trigger_reclaim_ema_window", strategy_params.get("reclaim_ema_window", 6)),
            reversion_sma_window=strategy_params.get("reversion_sma_window_override"),
            atr_window=strategy_params.get("atr_window", 14),
        )
    elif strategy_name == "regime_pullback_continuation_30m":
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_regime_pullback_continuation_30m(
            enriched,
            daily_regime_df=regime_df,
            daily_regime_ma_window=strategy_params.get("daily_regime_ma_window", 100),
            hourly_setup_df=hourly_setup_df,
            trend_ema_fast_1h=strategy_params.get("trend_ema_fast_1h", 20),
            trend_ema_slow_1h=strategy_params.get("trend_ema_slow_1h", 60),
            trend_slope_lookback_1h=strategy_params.get("trend_slope_lookback_1h", 3),
            pullback_lookback_1h=strategy_params.get("pullback_lookback_1h", 8),
            setup_rsi_window=strategy_params.get("setup_rsi_window", 14),
            trigger_ema_fast_30m=strategy_params.get("trigger_ema_fast_30m", 8),
            trigger_ema_slow_30m=strategy_params.get("trigger_ema_slow_30m", 21),
            trigger_breakout_lookback_30m=strategy_params.get("trigger_breakout_lookback_30m", 6),
            trigger_volume_window_30m=strategy_params.get("trigger_volume_window_30m", 20),
            atr_window=strategy_params.get("atr_window", 14),
        )
    elif strategy_name == "regime_relative_breakout_30m":
        enriched = enrich_daily(df, ma_window=ma_window, k=k)
        return enrich_regime_relative_breakout_30m(
            enriched,
            daily_regime_df=regime_df,
            daily_regime_ma_window=strategy_params.get("daily_regime_ma_window", 100),
            hourly_setup_df=hourly_setup_df,
            hourly_ema_fast=strategy_params.get("hourly_ema_fast", 20),
            hourly_ema_slow=strategy_params.get("hourly_ema_slow", 60),
            hourly_slope_lookback=strategy_params.get("hourly_slope_lookback", 3),
            rs_reference_df=rs_reference_df,
            rs_24h_bars_30m=strategy_params.get("rs_24h_bars_30m", 48),
            rs_7d_bars_30m=strategy_params.get("rs_7d_bars_30m", 336),
            breakout_lookback_30m=strategy_params.get("breakout_lookback_30m", 6),
            volume_window_30m=strategy_params.get("volume_window_30m", 20),
            atr_window=strategy_params.get("atr_window", 14),
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
    elif strategy_name == "regime_reclaim_1h":
        window = max(
            int(params.get("daily_regime_ma_window", 120)),
            int(params.get("dip_lookback_bars", 8)),
            int(params.get("rsi_window", 14)),
            int(params.get("reclaim_ema_window", 6)),
            int(params.get("atr_window", 14)),
            base_window,
        )
    elif strategy_name == "vwap_ema_pullback":
        window = max(
            int(params.get("ema_period", 9)),
            int(params.get("vwap_period", 48)),
            int(params.get("sideways_lookback", 12)),
            int(params.get("volume_profile_lookback", 48)),
            int(params.get("atr_window", 14)),
            base_window,
        )
    elif strategy_name == "regime_reclaim_30m":
        window = max(
            int(params.get("daily_regime_ma_window", 120)),
            int(params.get("hourly_pullback_bars", 8)),
            int(params.get("dip_lookback_bars", 8)),
            int(params.get("setup_rsi_window", params.get("rsi_window", 14))),
            int(params.get("trigger_reclaim_ema_window", 6)),
            int(params.get("reversion_sma_window_override") or params.get("dip_lookback_bars", 8)),
            int(params.get("atr_window", 14)),
            base_window,
        )
    elif strategy_name == "regime_pullback_continuation_30m":
        window = max(
            int(params.get("daily_regime_ma_window", 100)),
            int(params.get("trend_ema_slow_1h", 60)),
            int(params.get("trend_slope_lookback_1h", 3)),
            int(params.get("pullback_lookback_1h", 8)),
            int(params.get("setup_rsi_window", 14)),
            int(params.get("trigger_ema_slow_30m", 21)),
            int(params.get("trigger_breakout_lookback_30m", 6)),
            int(params.get("trigger_volume_window_30m", 20)),
            int(params.get("atr_window", 14)),
            base_window,
        )
    elif strategy_name == "regime_relative_breakout_30m":
        window = max(
            int(params.get("daily_regime_ma_window", 100)),
            int(params.get("hourly_ema_slow", 60)),
            int(params.get("rs_7d_bars_30m", 336)),
            int(params.get("rs_24h_bars_30m", 48)),
            int(params.get("breakout_lookback_30m", 6)),
            int(params.get("volume_window_30m", 20)),
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
    interval: str = "day",
) -> pd.DataFrame:
    """업비트 candle 조회 → 보조 컬럼 추가된 DataFrame 반환.

    `client`는 throttle/retry 이점을 위해 받지만, `pyupbit.get_ohlcv`는 공개 엔드포인트라
    인증 없이도 동작한다.
    """
    return fetch_candles(
        client,
        ticker,
        count=count,
        ma_window=ma_window,
        k=k,
        strategy_name=strategy_name,
        strategy_params=strategy_params,
        to=to,
        interval=interval,
    )


def fetch_candles(
    client: UpbitClient,
    ticker: str,
    *,
    count: int = 200,
    ma_window: int = 5,
    k: float = 0.5,
    strategy_name: str = "volatility_breakout",
    strategy_params: dict | None = None,
    to: datetime | str | None = None,
    interval: str = "day",
) -> pd.DataFrame:
    """업비트 candle 조회 → 보조 컬럼 추가된 DataFrame 반환.

    기존 daily 경로와 공존하도록 `interval="day"`가 기본이며,
    P0에서는 `minute60`(1H)까지 공식 지원한다.
    P1에서는 `minute30`(30m)도 지원하며,
    `regime_reclaim_30m` 전략은 daily + 1H + 30m 멀티 TF 자동 fetch 한다.
    """
    interval = normalize_candle_interval(interval)
    params = strategy_params or {}
    regime_interval = normalize_candle_interval(params.get("regime_interval", interval))

    def _fetch() -> pd.DataFrame:
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=count, to=to)
        if df is None or df.empty:
            raise _EmptyCandleResponse(f"no candles returned for {ticker}")
        return df

    label = f"get_ohlcv({ticker}, {interval}, {count})"
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
    hourly_setup_df = None

    # 30m multi-TF strategies: daily regime + 1H setup + 30m trigger
    if strategy_name in {"regime_reclaim_30m", "regime_pullback_continuation_30m"}:
        regime_ticker = params.get("regime_ticker", ticker)
        daily_count = history_days_to_candles(count // 48 + 3, "day") if count < 500 else count // 48 + 3
        # daily regime fetch
        if regime_ticker:
            def _fetch_daily() -> pd.DataFrame:
                rdf = pyupbit.get_ohlcv(regime_ticker, interval="day", count=daily_count, to=to)
                if rdf is None or rdf.empty:
                    raise _EmptyCandleResponse(f"no candles returned for {regime_ticker} day")
                return rdf
            daily_label = f"get_ohlcv({regime_ticker}, day, {daily_count})"
            if to is not None:
                daily_label = f"{daily_label}, to={to}"
            try:
                regime_df = client._call(daily_label, _fetch_daily)
            except UpbitError as exc:
                cause = exc.__cause__
                if isinstance(cause, _EmptyCandleResponse):
                    raise UpbitError(f"no candles returned for {regime_ticker} day") from exc
                raise
        # 1H setup fetch
        hour_count = history_days_to_candles(count // 48 + 3, "minute60") if count < 500 else count // 24 + 3
        setup_ticker = params.get("setup_ticker", ticker)
        if setup_ticker:
            def _fetch_hourly() -> pd.DataFrame:
                rdf = pyupbit.get_ohlcv(setup_ticker, interval="minute60", count=hour_count, to=to)
                if rdf is None or rdf.empty:
                    raise _EmptyCandleResponse(f"no candles returned for {setup_ticker} 1H")
                return rdf
            hourly_label = f"get_ohlcv({setup_ticker}, minute60, {hour_count})"
            if to is not None:
                hourly_label = f"{hourly_label}, to={to}"
            try:
                hourly_setup_df = client._call(hourly_label, _fetch_hourly)
            except UpbitError as exc:
                cause = exc.__cause__
                if isinstance(cause, _EmptyCandleResponse):
                    raise UpbitError(f"no candles returned for {setup_ticker} 1H") from exc
                raise

    # regime strategies: rcdb, rcdb_v2, regime_reclaim_1h
    elif strategy_name in {"rcdb", "rcdb_v2", "regime_reclaim_1h"}:
        regime_ticker = params.get("regime_ticker", "KRW-BTC")
        regime_count = count
        if regime_interval != interval:
            ratio = candle_bar_seconds(interval) / candle_bar_seconds(regime_interval)
            regime_count = max(int((count * ratio) + 0.999999), 1)
        needs_regime_fetch = bool(regime_ticker) and (
            regime_ticker != ticker or regime_interval != interval
        )
        if needs_regime_fetch:
            def _fetch_regime() -> pd.DataFrame:
                rdf = pyupbit.get_ohlcv(
                    regime_ticker,
                    interval=regime_interval,
                    count=regime_count,
                    to=to,
                )
                if rdf is None or rdf.empty:
                    raise _EmptyCandleResponse(f"no candles returned for {regime_ticker}")
                return rdf

            regime_label = f"get_ohlcv({regime_ticker}, {regime_interval}, {regime_count})"
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
        hourly_setup_df=hourly_setup_df,
        interval=interval,
    )

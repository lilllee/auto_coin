from __future__ import annotations

from math import isfinite
from typing import Any

import pandas as pd

from auto_coin.strategy.base import Signal, Strategy

REVIEW_SELL_OVERRIDABLE: frozenset[str] = frozenset({
    "atr_channel_breakout",
    "ema_adx_atr_trend",
    "sma200_regime",
    "ad_turtle",
})
ENTRY_ONLY_REVIEW_STRATEGIES: frozenset[str] = frozenset({"volatility_breakout"})
ALWAYS_SELL_REVIEW_STRATEGIES: frozenset[str] = frozenset({"sma200_ema_adx_composite", "vwap_ema_pullback"})


def derive_review_reason(
    strategy_name: str,
    strategy: Strategy,
    row: pd.Series,
    *,
    current_price: float,
    has_position: bool,
    signal: Signal,
) -> str:
    if strategy_name == "sma200_ema_adx_composite":
        sma = _float_or_none(row.get(f"sma{strategy.sma_window}"))
        ema_fast = _float_or_none(row.get(f"ema{strategy.ema_fast_window}"))
        ema_slow = _float_or_none(row.get(f"ema{strategy.ema_slow_window}"))
        adx = _float_or_none(row.get(f"adx{strategy.adx_window}"))
        if sma is None:
            return f"sma{strategy.sma_window} unavailable"
        if current_price < sma:
            return (
                f"price<sma{strategy.sma_window} (risk-off while holding)"
                if has_position
                else f"price<sma{strategy.sma_window}, stay out"
            )
        if has_position:
            return "risk-on and already in position"
        if ema_fast is None or ema_slow is None or adx is None:
            return "ema/adx unavailable"
        if signal is Signal.BUY:
            return (
                f"price>=sma{strategy.sma_window} and "
                f"ema{strategy.ema_fast_window}>ema{strategy.ema_slow_window} and "
                f"adx{strategy.adx_window}>={strategy.adx_threshold:.1f}"
            )
        if ema_fast <= ema_slow:
            return f"ema{strategy.ema_fast_window}<=ema{strategy.ema_slow_window}"
        if adx < strategy.adx_threshold:
            return f"adx{strategy.adx_window}<{strategy.adx_threshold:.1f}"
        return "entry conditions not met"

    if strategy_name == "volatility_breakout":
        target = _float_or_none(row.get("target"))
        ma = _float_or_none(row.get(f"ma{strategy.ma_window}"))
        if target is None:
            return "target unavailable"
        if has_position:
            return "already in position"
        if current_price < target:
            return "price<target"
        if strategy.require_ma_filter:
            if ma is None:
                return f"ma{strategy.ma_window} unavailable"
            if current_price <= ma:
                return f"price<=ma{strategy.ma_window}"
            return f"price>=target and price>ma{strategy.ma_window}"
        return "price>=target"

    if strategy_name == "sma200_regime":
        return _sma200_regime_reason(strategy, row, current_price=current_price, has_position=has_position, signal=signal)
    if strategy_name == "atr_channel_breakout":
        return _atr_channel_reason(strategy, row, current_price=current_price, has_position=has_position, signal=signal)
    if strategy_name == "ema_adx_atr_trend":
        return _ema_adx_reason(strategy, row, has_position=has_position, signal=signal)
    if strategy_name == "ad_turtle":
        return _ad_turtle_reason(strategy, row, current_price=current_price, has_position=has_position, signal=signal)
    if strategy_name == "vwap_ema_pullback":
        return _vwap_ema_pullback_reason(strategy, row, current_price=current_price, has_position=has_position, signal=signal)

    return f"signal={signal.value}"


def mode_note(strategy_name: str, include_strategy_sell: bool, include_operational_exits: bool = False) -> str:
    if include_operational_exits:
        return "operational exits enabled"
    if strategy_name in ALWAYS_SELL_REVIEW_STRATEGIES:
        return "strategy sell always active"
    if not include_strategy_sell:
        return "strategy-only replay"
    if strategy_name in REVIEW_SELL_OVERRIDABLE:
        return "strategy sell enabled"
    if strategy_name in ENTRY_ONLY_REVIEW_STRATEGIES:
        return "entry-only strategy (no sell logic)"
    return "strategy-only replay"


def mode_label(strategy_name: str, include_strategy_sell: bool, include_operational_exits: bool = False) -> str:
    if include_operational_exits:
        return "운영 청산 포함"
    if strategy_name in ALWAYS_SELL_REVIEW_STRATEGIES:
        return "SELL 항상 활성"
    if not include_strategy_sell:
        return "전략 신호만"
    if strategy_name in REVIEW_SELL_OVERRIDABLE:
        return "전략 SELL 포함"
    if strategy_name in ENTRY_ONLY_REVIEW_STRATEGIES:
        return "진입 전용 (SELL 없음)"
    return "전략 신호만"


def summary_interpretation(
    *,
    buy_count: int,
    sell_count: int,
    last_position_state: str,
    has_operational_exits: bool = False,
) -> str:
    suffix = " (일봉 종가 기준, 실운영과 차이 가능)"
    if sell_count > 0:
        if has_operational_exits:
            return "운영 청산(손절/시간)이 포함된 검토 결과입니다." + suffix
        return "선택 구간에서 전략 기준 청산까지 확인되었습니다." + suffix
    if last_position_state == "long":
        return "선택 구간 마지막까지 포지션을 유지했습니다." + suffix
    if buy_count > 0:
        return "진입 이벤트는 있었지만 구간 종료 시점에는 포지션이 없습니다." + suffix
    return "선택 구간에서는 진입 조건이 끝까지 충족되지 않았습니다." + suffix


def _sma200_regime_reason(
    strategy: Strategy,
    row: pd.Series,
    *,
    current_price: float,
    has_position: bool,
    signal: Signal,
) -> str:
    sma = _float_or_none(row.get(f"sma{strategy.ma_window}"))
    if sma is None:
        return f"sma{strategy.ma_window} unavailable"
    threshold = sma * (1 + strategy.buffer_pct)
    if has_position and strategy.allow_sell_signal:
        if signal is Signal.SELL:
            return f"price<sma{strategy.ma_window}, strategy exit"
        return f"price>=sma{strategy.ma_window}, keep position"
    if has_position:
        return "already in position (strategy sell disabled)"
    if current_price >= threshold:
        if strategy.buffer_pct > 0:
            return f"price>=sma{strategy.ma_window}*(1+buffer)"
        return f"price>=sma{strategy.ma_window}"
    if strategy.buffer_pct > 0 and current_price >= sma:
        return f"price>=sma{strategy.ma_window} but below buffer"
    return f"price<sma{strategy.ma_window}"


def _atr_channel_reason(
    strategy: Strategy,
    row: pd.Series,
    *,
    current_price: float,
    has_position: bool,
    signal: Signal,
) -> str:
    upper = _float_or_none(row.get("upper_channel"))
    lower = _float_or_none(row.get("lower_channel"))
    if upper is None:
        return "upper_channel unavailable"
    if has_position and strategy.allow_sell_signal:
        if lower is None:
            return "lower_channel unavailable"
        if signal is Signal.SELL:
            return "price<lower_channel, strategy exit"
        return "price>=lower_channel, keep position"
    if has_position:
        return "already in position (strategy sell disabled)"
    if current_price > upper:
        return "price>upper_channel breakout"
    return "price<=upper_channel"


def _ema_adx_reason(
    strategy: Strategy,
    row: pd.Series,
    *,
    has_position: bool,
    signal: Signal,
) -> str:
    ema_fast = _float_or_none(row.get(f"ema{strategy.ema_fast_window}"))
    ema_slow = _float_or_none(row.get(f"ema{strategy.ema_slow_window}"))
    adx = _float_or_none(row.get(f"adx{strategy.adx_window}"))
    if ema_fast is None or ema_slow is None or adx is None:
        return "ema/adx unavailable"
    if has_position and strategy.allow_sell_signal:
        if signal is Signal.SELL:
            return f"ema{strategy.ema_fast_window}<=ema{strategy.ema_slow_window}, strategy exit"
        return f"ema{strategy.ema_fast_window}>ema{strategy.ema_slow_window}, keep position"
    if has_position:
        return "already in position (strategy sell disabled)"
    if ema_fast <= ema_slow:
        return f"ema{strategy.ema_fast_window}<=ema{strategy.ema_slow_window}"
    if adx < strategy.adx_threshold:
        return f"adx{strategy.adx_window}<{strategy.adx_threshold:.1f}"
    return (
        f"ema{strategy.ema_fast_window}>ema{strategy.ema_slow_window} and "
        f"adx{strategy.adx_window}>={strategy.adx_threshold:.1f}"
    )


def _ad_turtle_reason(
    strategy: Strategy,
    row: pd.Series,
    *,
    current_price: float,
    has_position: bool,
    signal: Signal,
) -> str:
    high = _float_or_none(row.get(f"donchian_high_{strategy.entry_window}"))
    low = _float_or_none(row.get(f"donchian_low_{strategy.exit_window}"))
    if high is None:
        return f"donchian_high_{strategy.entry_window} unavailable"
    if has_position and strategy.allow_sell_signal:
        if low is None:
            return f"donchian_low_{strategy.exit_window} unavailable"
        if signal is Signal.SELL:
            return f"price<donchian_low_{strategy.exit_window}, strategy exit"
        return f"price>=donchian_low_{strategy.exit_window}, keep position"
    if has_position:
        return "already in position (strategy sell disabled)"
    if current_price > high:
        return f"price>donchian_high_{strategy.entry_window} breakout"
    return f"price<=donchian_high_{strategy.entry_window}"


def _vwap_ema_pullback_reason(
    strategy: Strategy,
    row: pd.Series,
    *,
    current_price: float,
    has_position: bool,
    signal: Signal,
) -> str:
    ema = _float_or_none(row.get(f"ema{strategy.ema_period}"))
    vwap = _float_or_none(row.get("vwap"))
    cross_count = _float_or_none(row.get("vwap_cross_count"))
    slope = _float_or_none(row.get("ema_slope_ratio"))
    is_sideways = bool(row.get("is_sideways")) if row.get("is_sideways") is not None else False
    if ema is None or vwap is None:
        return "ema/vwap unavailable"
    if has_position:
        if signal is Signal.SELL:
            return f"close<ema{strategy.ema_period}, strategy exit"
        return f"close>=ema{strategy.ema_period}, keep position"
    if current_price <= vwap:
        return "close<=vwap"
    if is_sideways:
        return "sideways filter blocked"
    if cross_count is not None and cross_count > strategy.max_vwap_cross_count:
        return "too many VWAP crosses"
    if slope is not None and abs(slope) < strategy.min_ema_slope_ratio:
        return "EMA slope too flat"
    if signal is Signal.BUY:
        return f"close>vwap and EMA{strategy.ema_period} pullback confirmed"
    return "entry conditions not met"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if isfinite(num) else None

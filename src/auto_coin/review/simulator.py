from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any

import pandas as pd

from auto_coin.data.candles import fetch_daily, recommended_history_days
from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.strategy import STRATEGY_LABELS, create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


# 전략별 SELL 오버라이드 지원 분류
_SELL_OVERRIDABLE: frozenset[str] = frozenset({
    "atr_channel_breakout",
    "ema_adx_atr_trend",
    "sma200_regime",
    "ad_turtle",
})
_ENTRY_ONLY: frozenset[str] = frozenset({"volatility_breakout"})
_ALWAYS_SELL: frozenset[str] = frozenset({"sma200_ema_adx_composite"})


class ReviewValidationError(ValueError):
    """잘못된 review 시뮬레이션 입력."""


@dataclass(frozen=True)
class ReviewRow:
    date: str
    signal: str
    price: float
    reason: str
    indicators: dict[str, float | None]
    position_state: str


@dataclass(frozen=True)
class ReviewEvent:
    date: str
    signal: str
    price: float
    reason: str
    indicators: dict[str, float | None]
    position_before: str
    position_after: str
    trade_pnl_ratio: float | None = None


@dataclass(frozen=True)
class ReviewSummary:
    buy_count: int
    sell_count: int
    event_count: int
    realized_pnl_ratio: float
    unrealized_pnl_ratio: float
    total_pnl_ratio: float
    last_position: dict[str, Any]
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewResult:
    ticker: str
    strategy: dict[str, Any]
    range: dict[str, Any]
    summary: ReviewSummary
    rows: list[ReviewRow]
    events: list[ReviewEvent]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _PositionState:
    has_position: bool = False
    entry_price: float | None = None
    entry_date: str | None = None
    realized_pnl_ratio: float = 0.0


def run_review_simulation(
    client: UpbitClient,
    *,
    ticker: str,
    start_date: date | datetime | str,
    end_date: date | datetime | str,
    strategy_name: str,
    strategy_params: dict | None = None,
    ma_window: int = 5,
    k: float = 0.5,
    max_review_days: int = 90,
    include_strategy_sell: bool = False,
) -> ReviewResult:
    """선택 구간의 전략 signal을 일봉 종가 기준으로 replay한다."""
    start = _normalize_date(start_date)
    end = _normalize_date(end_date)
    if end < start:
        raise ReviewValidationError("end_date must be >= start_date")

    review_days = (end - start).days + 1
    if review_days < 1:
        raise ReviewValidationError("review range must include at least 1 day")
    if review_days > max_review_days:
        raise ReviewValidationError(f"review range must be <= {max_review_days} days")

    params = strategy_params or {}
    history_days = recommended_history_days(strategy_name, params, ma_window=ma_window)
    fetch_count = history_days + review_days - 1
    fetch_to = datetime.combine(end + timedelta(days=1), time.min)

    df = fetch_daily(
        client,
        ticker.upper(),
        count=fetch_count,
        ma_window=ma_window,
        k=k,
        strategy_name=strategy_name,
        strategy_params=params,
        to=fetch_to,
    )

    review_df = df.loc[(df.index.date >= start) & (df.index.date <= end)]
    if review_df.empty:
        raise ReviewValidationError("no candles available for selected range")

    if include_strategy_sell and strategy_name in _SELL_OVERRIDABLE:
        params = {**params, "allow_sell_signal": True}

    strategy = create_strategy(strategy_name, params)
    state = _PositionState()
    rows: list[ReviewRow] = []
    events: list[ReviewEvent] = []

    for ts, row in review_df.iterrows():
        price = _float_or_none(row.get("close"))
        if price is None or price <= 0:
            raise ReviewValidationError(f"invalid close price at {ts.date().isoformat()}")

        snap = MarketSnapshot(
            df=df.loc[:ts],
            current_price=price,
            has_position=state.has_position,
        )
        signal = strategy.generate_signal(snap)
        indicators = _extract_indicators(strategy_name, strategy, row)
        reason = _derive_reason(
            strategy_name,
            strategy,
            row,
            current_price=price,
            has_position=state.has_position,
            signal=signal,
        )

        position_before = "long" if state.has_position else "flat"
        trade_pnl_ratio: float | None = None
        event_emitted = False

        if signal is Signal.BUY and not state.has_position:
            state.has_position = True
            state.entry_price = price
            state.entry_date = ts.date().isoformat()
            event_emitted = True
        elif signal is Signal.SELL and state.has_position and state.entry_price is not None:
            trade_pnl_ratio = (price - state.entry_price) / state.entry_price
            state.realized_pnl_ratio += trade_pnl_ratio
            state.has_position = False
            state.entry_price = None
            state.entry_date = None
            event_emitted = True

        position_after = "long" if state.has_position else "flat"

        rows.append(
            ReviewRow(
                date=ts.date().isoformat(),
                signal=signal.value,
                price=price,
                reason=reason,
                indicators=indicators,
                position_state=position_after,
            )
        )

        if event_emitted:
            events.append(
                ReviewEvent(
                    date=ts.date().isoformat(),
                    signal=signal.value,
                    price=price,
                    reason=reason,
                    indicators=indicators,
                    position_before=position_before,
                    position_after=position_after,
                    trade_pnl_ratio=trade_pnl_ratio,
                )
            )

    last_price = rows[-1].price
    unrealized = 0.0
    if state.has_position and state.entry_price is not None:
        unrealized = (last_price - state.entry_price) / state.entry_price

    summary = ReviewSummary(
        buy_count=sum(1 for event in events if event.signal == Signal.BUY.value),
        sell_count=sum(1 for event in events if event.signal == Signal.SELL.value),
        event_count=len(events),
        realized_pnl_ratio=state.realized_pnl_ratio,
        unrealized_pnl_ratio=unrealized,
        total_pnl_ratio=state.realized_pnl_ratio + unrealized,
        last_position={
            "state": "long" if state.has_position else "flat",
            "entry_date": state.entry_date,
            "entry_price": state.entry_price,
        },
        notes=[_mode_note(strategy_name, include_strategy_sell), "daily-close approximation"],
    )
    return ReviewResult(
        ticker=ticker.upper(),
        strategy={
            "name": strategy_name,
            "label": STRATEGY_LABELS.get(strategy_name, strategy_name),
            "params": params,
        },
        range={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "days": review_days,
            "history_days": history_days,
        },
        summary=summary,
        rows=rows,
        events=events,
    )


def _normalize_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ReviewValidationError(f"invalid date: {value}") from exc


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if isfinite(num) else None


def _extract_indicators(strategy_name: str, strategy: Strategy, row: pd.Series) -> dict[str, float | None]:
    indicators: dict[str, float | None] = {
        "close": _float_or_none(row.get("close")),
    }

    if strategy_name == "volatility_breakout":
        indicators["target"] = _float_or_none(row.get("target"))
        indicators[f"ma{strategy.ma_window}"] = _float_or_none(row.get(f"ma{strategy.ma_window}"))
    elif strategy_name == "sma200_regime":
        indicators[f"sma{strategy.ma_window}"] = _float_or_none(row.get(f"sma{strategy.ma_window}"))
    elif strategy_name == "atr_channel_breakout":
        indicators["upper_channel"] = _float_or_none(row.get("upper_channel"))
        indicators["lower_channel"] = _float_or_none(row.get("lower_channel"))
        indicators[f"atr{strategy.atr_window}"] = _float_or_none(row.get(f"atr{strategy.atr_window}"))
    elif strategy_name == "ema_adx_atr_trend":
        indicators[f"ema{strategy.ema_fast_window}"] = _float_or_none(row.get(f"ema{strategy.ema_fast_window}"))
        indicators[f"ema{strategy.ema_slow_window}"] = _float_or_none(row.get(f"ema{strategy.ema_slow_window}"))
        indicators[f"adx{strategy.adx_window}"] = _float_or_none(row.get(f"adx{strategy.adx_window}"))
    elif strategy_name == "ad_turtle":
        indicators[f"donchian_high_{strategy.entry_window}"] = _float_or_none(
            row.get(f"donchian_high_{strategy.entry_window}")
        )
        indicators[f"donchian_low_{strategy.exit_window}"] = _float_or_none(
            row.get(f"donchian_low_{strategy.exit_window}")
        )
    elif strategy_name == "sma200_ema_adx_composite":
        indicators[f"sma{strategy.sma_window}"] = _float_or_none(row.get(f"sma{strategy.sma_window}"))
        indicators[f"ema{strategy.ema_fast_window}"] = _float_or_none(row.get(f"ema{strategy.ema_fast_window}"))
        indicators[f"ema{strategy.ema_slow_window}"] = _float_or_none(row.get(f"ema{strategy.ema_slow_window}"))
        indicators[f"adx{strategy.adx_window}"] = _float_or_none(row.get(f"adx{strategy.adx_window}"))

    return indicators


def _derive_reason(
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

    return f"signal={signal.value}"


def _mode_note(strategy_name: str, include_strategy_sell: bool) -> str:
    if not include_strategy_sell:
        return "strategy-only replay"
    if strategy_name in _SELL_OVERRIDABLE:
        return "strategy sell enabled"
    if strategy_name in _ENTRY_ONLY:
        return "entry-only strategy (no sell logic)"
    if strategy_name in _ALWAYS_SELL:
        return "strategy sell always active"
    return "strategy-only replay"

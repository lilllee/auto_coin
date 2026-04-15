from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Any

import pandas as pd

from auto_coin.data.candles import fetch_daily, recommended_history_days
from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.review.reasons import (
    REVIEW_SELL_OVERRIDABLE,
    derive_review_reason,
    mode_label,
    mode_note,
    summary_interpretation,
)
from auto_coin.strategy import STRATEGY_LABELS, create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


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
    exit_type: str | None = None  # None=strategy, "operational:stop_loss", "operational:time_exit"


@dataclass(frozen=True)
class ReviewSummary:
    mode_label: str
    buy_count: int
    sell_count: int
    event_count: int
    realized_pnl_ratio: float
    unrealized_pnl_ratio: float
    total_pnl_ratio: float
    last_position: dict[str, Any]
    interpretation: str
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
    hold_days: int = 0  # 보유 일수 추적


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
    include_operational_exits: bool = False,
    stop_loss_ratio: float = -0.02,
    enable_time_exit: bool = True,
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

    if include_strategy_sell and strategy_name in REVIEW_SELL_OVERRIDABLE:
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
        reason = derive_review_reason(
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
        op_exit_emitted = False

        if signal is Signal.BUY and not state.has_position:
            state.has_position = True
            state.entry_price = price
            state.entry_date = ts.date().isoformat()
            state.hold_days = 0
            event_emitted = True
        elif signal is Signal.SELL and state.has_position and state.entry_price is not None:
            trade_pnl_ratio = (price - state.entry_price) / state.entry_price
            state.realized_pnl_ratio += trade_pnl_ratio
            state.has_position = False
            state.entry_price = None
            state.entry_date = None
            state.hold_days = 0
            event_emitted = True

        # Operational exits (only when enabled and not already exited by strategy)
        if include_operational_exits and state.has_position and not event_emitted:
            op_exit_reason: str | None = None
            op_exit_type: str | None = None

            # 1. Stop loss check: close <= entry * (1 + stop_loss_ratio)
            if state.entry_price is not None and stop_loss_ratio < 0:
                stop_price = state.entry_price * (1 + stop_loss_ratio)
                if price <= stop_price:
                    op_exit_reason = f"stop-loss ({stop_loss_ratio:.1%})"
                    op_exit_type = "operational:stop_loss"

            # 2. Time exit: for day-trading strategies, exit next day
            if op_exit_reason is None and enable_time_exit and strategy_name == "volatility_breakout" and state.hold_days >= 1:
                op_exit_reason = "time-exit (next day close)"
                op_exit_type = "operational:time_exit"

            if op_exit_reason is not None:
                assert state.entry_price is not None
                trade_pnl_ratio = (price - state.entry_price) / state.entry_price
                state.realized_pnl_ratio += trade_pnl_ratio
                state.has_position = False
                state.entry_price = None
                state.entry_date = None
                state.hold_days = 0
                event_emitted = True
                op_exit_emitted = True

                events.append(
                    ReviewEvent(
                        date=ts.date().isoformat(),
                        signal="sell",
                        price=price,
                        reason=op_exit_reason,
                        indicators=indicators,
                        position_before="long",
                        position_after="flat",
                        trade_pnl_ratio=trade_pnl_ratio,
                        exit_type=op_exit_type,
                    )
                )

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

        if event_emitted and not op_exit_emitted:
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

        if state.has_position:
            state.hold_days += 1

    last_price = rows[-1].price
    unrealized = 0.0
    if state.has_position and state.entry_price is not None:
        unrealized = (last_price - state.entry_price) / state.entry_price

    buy_count = sum(1 for event in events if event.signal == Signal.BUY.value)
    sell_count = sum(1 for event in events if event.signal == Signal.SELL.value)
    last_position_state = "long" if state.has_position else "flat"
    summary = ReviewSummary(
        mode_label=mode_label(strategy_name, include_strategy_sell, include_operational_exits),
        buy_count=buy_count,
        sell_count=sell_count,
        event_count=len(events),
        realized_pnl_ratio=state.realized_pnl_ratio,
        unrealized_pnl_ratio=unrealized,
        total_pnl_ratio=state.realized_pnl_ratio + unrealized,
        last_position={
            "state": last_position_state,
            "entry_date": state.entry_date,
            "entry_price": state.entry_price,
        },
        interpretation=summary_interpretation(
            buy_count=buy_count,
            sell_count=sell_count,
            last_position_state=last_position_state,
            has_operational_exits=include_operational_exits,
        ),
        notes=[mode_note(strategy_name, include_strategy_sell, include_operational_exits), "daily-close approximation"],
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

from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


@dataclass(frozen=True)
class AtrChannelBreakoutStrategy(Strategy):
    """ATR 변동성 채널 돌파.

    진입 조건:
        1) 미보유
        2) current_price > upper_channel (= low + atr * channel_multiplier)

    upper_channel은 전처리에서 계산되어 DataFrame 컬럼으로 제공된다.
    손절/익절은 외부 RiskManager가 처리한다.
    """

    name: str = "atr_channel_breakout"
    atr_window: int = 14
    channel_multiplier: float = 1.0
    allow_sell_signal: bool = False

    def __post_init__(self) -> None:
        if self.atr_window < 1:
            raise ValueError(f"atr_window must be >= 1, got {self.atr_window}")
        if self.channel_multiplier <= 0:
            raise ValueError(
                f"channel_multiplier must be > 0, got {self.channel_multiplier}"
            )

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty:
            return Signal.HOLD

        last = df.iloc[-1]

        upper = last.get("upper_channel")
        if upper is None or (isinstance(upper, float) and math.isnan(upper)):
            return Signal.HOLD

        # SELL when holding and price drops below lower_channel (if enabled)
        if self.allow_sell_signal and snap.has_position:
            lower = last.get("lower_channel")
            if (
                lower is not None
                and not (isinstance(lower, float) and math.isnan(lower))
                and snap.current_price < float(lower)
            ):
                return Signal.SELL
            return Signal.HOLD

        if snap.has_position:
            return Signal.HOLD
        if snap.current_price > float(upper):
            return Signal.BUY
        return Signal.HOLD

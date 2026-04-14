from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


@dataclass(frozen=True)
class AdTurtleStrategy(Strategy):
    """AdTurtle (개선형 Turtle) — Donchian 채널 돌파 전략.

    진입 조건:
        1) 미보유
        2) current_price > donchian_high_{entry_window} (N일 최고가 돌파)

    청산은 외부 스케줄러/RiskManager가 처리.
    allow_sell_signal=True 시 donchian_low 하향 돌파에서 SELL.

    배제구간(exclusion zone), 피라미딩(pyramiding)은 외부 상태 관리자로 분리.
    (현재 MarketSnapshot만으로는 상태 추적이 어려움)
    """

    name: str = "ad_turtle"
    entry_window: int = 20
    exit_window: int = 10
    allow_sell_signal: bool = False

    def __post_init__(self) -> None:
        if self.entry_window < 2:
            raise ValueError(f"entry_window must be >= 2, got {self.entry_window}")
        if self.exit_window < 1:
            raise ValueError(f"exit_window must be >= 1, got {self.exit_window}")
        if self.exit_window >= self.entry_window:
            raise ValueError(
                f"exit_window must be < entry_window, "
                f"got exit={self.exit_window} >= entry={self.entry_window}"
            )

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty:
            return Signal.HOLD

        last = df.iloc[-1]
        high_col = f"donchian_high_{self.entry_window}"
        low_col = f"donchian_low_{self.exit_window}"

        donchian_high = last.get(high_col)
        if donchian_high is None or (isinstance(donchian_high, float) and math.isnan(donchian_high)):
            return Signal.HOLD

        # SELL when holding and price drops below donchian low (if enabled)
        if self.allow_sell_signal and snap.has_position:
            donchian_low = last.get(low_col)
            if (
                donchian_low is not None
                and not (isinstance(donchian_low, float) and math.isnan(donchian_low))
                and snap.current_price < float(donchian_low)
            ):
                return Signal.SELL
            return Signal.HOLD

        if snap.has_position:
            return Signal.HOLD

        # Entry: break above N-day high
        if snap.current_price > float(donchian_high):
            return Signal.BUY
        return Signal.HOLD

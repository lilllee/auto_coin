from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


@dataclass(frozen=True)
class Sma200RegimeStrategy(Strategy):
    """SMA200 추세 필터.

    진입 조건:
        1) 미보유
        2) current_price >= sma(ma_window) * (1 + buffer_pct)

    청산은 외부 스케줄러/RiskManager가 처리한다.
    allow_sell_signal=True일 경우, 보유 중 가격이 SMA 아래로 내려가면 SELL.
    """

    name: str = "sma200_regime"
    ma_window: int = 200
    buffer_pct: float = 0.0
    allow_sell_signal: bool = False

    def __post_init__(self) -> None:
        if self.ma_window < 2:
            raise ValueError(f"ma_window must be >= 2, got {self.ma_window}")
        if self.buffer_pct < 0:
            raise ValueError(f"buffer_pct must be >= 0, got {self.buffer_pct}")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty:
            return Signal.HOLD

        last = df.iloc[-1]
        ma_col = f"sma{self.ma_window}"
        ma = last.get(ma_col)
        if ma is None or (isinstance(ma, float) and math.isnan(ma)):
            return Signal.HOLD

        threshold = float(ma) * (1 + self.buffer_pct)

        # SELL signal (if enabled and holding)
        if self.allow_sell_signal and snap.has_position:
            if snap.current_price < float(ma):
                return Signal.SELL
            return Signal.HOLD

        # Entry
        if snap.has_position:
            return Signal.HOLD
        if snap.current_price >= threshold:
            return Signal.BUY
        return Signal.HOLD

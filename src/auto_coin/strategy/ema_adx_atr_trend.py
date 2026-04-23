from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


@dataclass(frozen=True)
class EmaAdxAtrTrendStrategy(Strategy):
    """EMA 크로스 + ADX 추세 강도 확인 전략.

    진입 조건:
        1) 미보유
        2) ema_fast > ema_slow (골든크로스 상태)
        3) adx >= adx_threshold (추세 강도 확인)

    ATR 컬럼은 외부 RiskManager의 초기 스탑/트레일링 계산용으로 함께 요구한다.
    청산/손절은 기본적으로 외부 RiskManager(ATR 기반)가 처리한다.
    allow_sell_signal=True 시 ema_fast <= ema_slow에서 SELL.
    """

    name: str = "ema_adx_atr_trend"
    ema_fast_window: int = 27
    ema_slow_window: int = 125
    adx_window: int = 90
    adx_threshold: float = 14.0
    atr_window: int = 14
    allow_sell_signal: bool = False

    def __post_init__(self) -> None:
        if self.ema_fast_window < 1:
            raise ValueError(f"ema_fast_window must be >= 1, got {self.ema_fast_window}")
        if self.ema_slow_window <= self.ema_fast_window:
            raise ValueError("ema_slow_window must be > ema_fast_window")
        if self.adx_window < 1:
            raise ValueError(f"adx_window must be >= 1, got {self.adx_window}")
        if self.atr_window < 1:
            raise ValueError(f"atr_window must be >= 1, got {self.atr_window}")
        if self.adx_threshold < 0:
            raise ValueError(f"adx_threshold must be >= 0, got {self.adx_threshold}")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty:
            return Signal.HOLD

        last = df.iloc[-1]
        ema_fast_col = f"ema{self.ema_fast_window}"
        ema_slow_col = f"ema{self.ema_slow_window}"
        adx_col = f"adx{self.adx_window}"
        atr_col = f"atr{self.atr_window}"

        ema_fast = last.get(ema_fast_col)
        ema_slow = last.get(ema_slow_col)
        adx = last.get(adx_col)
        atr = last.get(atr_col)

        # Missing data guard
        for val in (ema_fast, ema_slow, adx, atr):
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return Signal.HOLD

        ema_fast_v = float(ema_fast)
        ema_slow_v = float(ema_slow)
        adx_v = float(adx)

        # SELL when holding and EMA crosses down (if enabled)
        if self.allow_sell_signal and snap.has_position:
            if ema_fast_v <= ema_slow_v:
                return Signal.SELL
            return Signal.HOLD

        if snap.has_position:
            return Signal.HOLD

        # Entry: EMA golden cross + ADX trend strength
        if ema_fast_v > ema_slow_v and adx_v >= self.adx_threshold:
            return Signal.BUY
        return Signal.HOLD

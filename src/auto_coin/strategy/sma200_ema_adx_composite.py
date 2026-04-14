from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


@dataclass(frozen=True)
class Sma200EmaAdxCompositeStrategy(Strategy):
    """SMA200 레짐 필터 + EMA+ADX 추세추종 합성 전략.

    2단계 판단:
      1) SMA200 레짐 필터 (일봉)
         - price < SMA200 → SELL (risk-off, 보유 포지션도 청산)
         - price >= SMA200 → risk-on, 2단계로 진행
      2) EMA+ADX 진입 조건 (일봉)
         - ema_fast > ema_slow (골든크로스)
         - adx >= adx_threshold (추세 강도 확인)
         - 둘 다 만족 → BUY

    모든 지표는 확정봉 기준 (shift(1)).
    향후 멀티 타임프레임(일봉 SMA200 + 1H EMA+ADX) 확장 대비 구조.
    """

    name: str = "sma200_ema_adx_composite"

    # SMA200 레짐 필터
    sma_window: int = 200

    # EMA+ADX 진입
    ema_fast_window: int = 27
    ema_slow_window: int = 125
    adx_window: int = 90
    adx_threshold: float = 14.0

    def __post_init__(self) -> None:
        if self.sma_window < 2:
            raise ValueError(f"sma_window must be >= 2, got {self.sma_window}")
        if self.ema_fast_window < 1:
            raise ValueError(f"ema_fast_window must be >= 1, got {self.ema_fast_window}")
        if self.ema_slow_window <= self.ema_fast_window:
            raise ValueError("ema_slow_window must be > ema_fast_window")
        if self.adx_window < 1:
            raise ValueError(f"adx_window must be >= 1, got {self.adx_window}")
        if self.adx_threshold < 0:
            raise ValueError(f"adx_threshold must be >= 0, got {self.adx_threshold}")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty:
            return Signal.HOLD

        last = df.iloc[-1]

        # --- Stage 1: SMA200 Regime Filter ---
        sma_col = f"sma{self.sma_window}"
        sma = last.get(sma_col)
        if sma is None or (isinstance(sma, float) and math.isnan(sma)):
            return Signal.HOLD  # No data = no action

        sma_v = float(sma)

        # Risk-off: price below SMA → SELL everything (including existing positions)
        if snap.current_price < sma_v:
            if snap.has_position:
                return Signal.SELL
            return Signal.HOLD  # No position and risk-off = stay out

        # --- Stage 2: EMA+ADX Entry (only when risk-on) ---
        if snap.has_position:
            return Signal.HOLD  # Already in position, let it ride

        ema_fast_col = f"ema{self.ema_fast_window}"
        ema_slow_col = f"ema{self.ema_slow_window}"
        adx_col = f"adx{self.adx_window}"

        ema_fast = last.get(ema_fast_col)
        ema_slow = last.get(ema_slow_col)
        adx = last.get(adx_col)

        for val in (ema_fast, ema_slow, adx):
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return Signal.HOLD

        if float(ema_fast) > float(ema_slow) and float(adx) >= self.adx_threshold:
            return Signal.BUY

        return Signal.HOLD

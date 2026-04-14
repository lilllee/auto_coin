from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy


@dataclass(frozen=True)
class VolatilityBreakout(Strategy):
    """Larry Williams 변동성 돌파.

    진입 조건 (모두 충족):
        1) 미보유 (`snap.has_position is False`)
        2) `current_price >= target` (target = 오늘_시가 + 전일_range × k)
        3) MA 필터: `current_price > maN` (이평선 위)

    청산은 시간 기반(다음 09:00 직전)으로 외부 스케줄러가 처리하며,
    손절은 RiskManager가 처리한다 — 본 클래스는 진입 판단만 한다.
    """

    name: str = "volatility_breakout"
    k: float = 0.5
    ma_window: int = 5
    require_ma_filter: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.k <= 1:
            raise ValueError(f"k must be in (0, 1], got {self.k}")
        if self.ma_window < 1:
            raise ValueError(f"ma_window must be >= 1, got {self.ma_window}")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.has_position:
            return Signal.HOLD
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty:
            return Signal.HOLD

        last = df.iloc[-1]
        target = last.get("target")
        if target is None or (isinstance(target, float) and math.isnan(target)):
            return Signal.HOLD
        if snap.current_price < float(target):
            return Signal.HOLD

        if self.require_ma_filter:
            ma_col = f"ma{self.ma_window}"
            if ma_col not in df.columns:
                return Signal.HOLD
            ma = last.get(ma_col)
            if ma is None or (isinstance(ma, float) and math.isnan(ma)):
                return Signal.HOLD
            if snap.current_price <= float(ma):
                return Signal.HOLD

        return Signal.BUY

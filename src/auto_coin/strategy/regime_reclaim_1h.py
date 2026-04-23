from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import (
    ExitDecision,
    MarketSnapshot,
    PositionSnapshot,
    Signal,
    Strategy,
)


@dataclass(frozen=True)
class RegimeReclaim1HStrategy(Strategy):
    """Daily regime + 1H reclaim mean reversion.

    목표:
    - daily risk-on일 때만 1H 눌림목 매수
    - 단순 dip catch가 아니라 reclaim 확인 후 진입
    - 수익 실현은 short-term mean reversion, 실패는 ATR trailing / regime off / time exit
    """

    name: str = "regime_reclaim_1h"
    regime_ticker: str = "KRW-BTC"
    regime_interval: str = "day"
    daily_regime_ma_window: int = 120
    dip_lookback_bars: int = 8
    pullback_threshold_pct: float = -0.025
    rsi_window: int = 14
    rsi_threshold: float = 35.0
    reclaim_ema_window: int = 6
    max_hold_bars: int = 36
    atr_window: int = 14
    atr_trailing_mult: float = 2.0

    def __post_init__(self) -> None:
        if not self.regime_ticker:
            raise ValueError("regime_ticker must be non-empty")
        if self.regime_interval != "day":
            raise ValueError("regime_interval must be 'day' for this strategy")
        if self.daily_regime_ma_window < 2:
            raise ValueError("daily_regime_ma_window must be >= 2")
        if self.dip_lookback_bars < 1:
            raise ValueError("dip_lookback_bars must be >= 1")
        if self.pullback_threshold_pct >= 0:
            raise ValueError("pullback_threshold_pct must be < 0")
        if self.rsi_window < 2:
            raise ValueError("rsi_window must be >= 2")
        if not (0 < self.rsi_threshold < 100):
            raise ValueError("rsi_threshold must be between 0 and 100")
        if self.reclaim_ema_window < 1:
            raise ValueError("reclaim_ema_window must be >= 1")
        if self.max_hold_bars < 1:
            raise ValueError("max_hold_bars must be >= 1")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.atr_trailing_mult <= 0:
            raise ValueError("atr_trailing_mult must be > 0")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.has_position or snap.current_price <= 0:
            return Signal.HOLD
        if len(snap.df) < 2:
            return Signal.HOLD

        last = snap.df.iloc[-1]
        prev_close = snap.df.iloc[-2].get("close")
        regime_on = last.get("daily_regime_on")
        pullback = last.get(self._pullback_col)
        rsi = last.get(self._rsi_col)
        reclaim_ema = last.get(self._reclaim_ema_col)

        if not self._is_true(regime_on):
            return Signal.HOLD
        if not all(self._is_finite(v) for v in (prev_close, pullback, rsi, reclaim_ema)):
            return Signal.HOLD

        reclaim_confirmed = (
            snap.current_price > float(prev_close)
            or snap.current_price > float(reclaim_ema)
        )
        if (
            float(pullback) <= self.pullback_threshold_pct
            and float(rsi) <= self.rsi_threshold
            and reclaim_confirmed
        ):
            return Signal.BUY
        return Signal.HOLD

    def generate_exit(
        self,
        snap: MarketSnapshot,
        position: PositionSnapshot,
    ) -> ExitDecision | None:
        if snap.df.empty or snap.current_price <= 0:
            return None

        last = snap.df.iloc[-1]
        low = last.get("low")
        atr = last.get(self._atr_col)
        regime_on = last.get("daily_regime_on")
        reversion_sma = last.get(self._reversion_sma_col)
        hold_bars = position.hold_bars if position.hold_bars is not None else position.hold_days

        if self._is_finite(low) and self._is_finite(atr):
            trailing_stop = position.highest_high - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(reason="regime_reclaim_1h_trailing_exit", exit_price=trailing_stop)

        if self._is_false(regime_on):
            return ExitDecision(reason="regime_reclaim_1h_regime_off_exit")

        if (
            self._is_finite(reversion_sma)
            and snap.current_price >= float(reversion_sma)
            and snap.current_price > position.entry_price
        ):
            return ExitDecision(reason="regime_reclaim_1h_reversion_exit")

        if hold_bars >= self.max_hold_bars:
            return ExitDecision(reason="regime_reclaim_1h_time_exit")

        return None

    @property
    def _pullback_col(self) -> str:
        return f"pullback_return_{self.dip_lookback_bars}"

    @property
    def _rsi_col(self) -> str:
        return f"rsi{self.rsi_window}"

    @property
    def _reclaim_ema_col(self) -> str:
        return f"reclaim_ema{self.reclaim_ema_window}"

    @property
    def _reversion_sma_col(self) -> str:
        return f"reversion_sma{self.dip_lookback_bars}"

    @property
    def _atr_col(self) -> str:
        return f"atr{self.atr_window}"

    @staticmethod
    def _is_finite(value: float | None) -> bool:
        if value is None:
            return False
        try:
            f = float(value)
        except (TypeError, ValueError):
            return False
        return not math.isnan(f) and not math.isinf(f)

    @staticmethod
    def _is_true(value: object) -> bool:
        return value is True or value == True  # noqa: E712

    @staticmethod
    def _is_false(value: object) -> bool:
        return value is False or value == False  # noqa: E712

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
class RcdbStrategy(Strategy):
    """Regime-Conditioned Dip Buy.

    상승/정상 레짐에서만 단기 급락 + RSI 과매도 구간을 매수하고,
    ATR trailing / regime off / max hold 로 청산한다.
    """

    name: str = "rcdb"
    regime_ticker: str = "KRW-BTC"
    regime_ma_window: int = 120
    dip_lookback_days: int = 5
    dip_threshold_pct: float = -0.08
    rsi_window: int = 14
    rsi_threshold: float = 30.0
    max_hold_days: int = 7
    atr_window: int = 14
    atr_trailing_mult: float = 2.5

    def __post_init__(self) -> None:
        if not self.regime_ticker:
            raise ValueError("regime_ticker must be non-empty")
        if self.regime_ma_window < 2:
            raise ValueError("regime_ma_window must be >= 2")
        if self.dip_lookback_days < 1:
            raise ValueError("dip_lookback_days must be >= 1")
        if self.dip_threshold_pct >= 0:
            raise ValueError("dip_threshold_pct must be < 0")
        if self.rsi_window < 2:
            raise ValueError("rsi_window must be >= 2")
        if not (0 < self.rsi_threshold < 100):
            raise ValueError("rsi_threshold must be between 0 and 100")
        if self.max_hold_days < 1:
            raise ValueError("max_hold_days must be >= 1")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.atr_trailing_mult <= 0:
            raise ValueError("atr_trailing_mult must be > 0")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.has_position or snap.current_price <= 0:
            return Signal.HOLD
        if snap.df.empty:
            return Signal.HOLD

        last = snap.df.iloc[-1]
        regime_on = last.get("regime_on")
        dip_ret = last.get(self._dip_col)
        rsi = last.get(self._rsi_col)

        if not self._is_true(regime_on):
            return Signal.HOLD
        if not self._is_finite(dip_ret) or not self._is_finite(rsi):
            return Signal.HOLD
        if float(dip_ret) <= self.dip_threshold_pct and float(rsi) < self.rsi_threshold:
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
        regime_on = last.get("regime_on")

        if self._is_finite(low) and self._is_finite(atr):
            # v1.1: rebound high-water mark is the intraday high, not close.
            # This makes trailing a real give-back guard instead of a late close-only exit.
            trailing_stop = position.highest_high - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(reason="rcdb_trailing_exit", exit_price=trailing_stop)

        if self._is_false(regime_on):
            return ExitDecision(reason="rcdb_regime_off")

        if position.hold_days >= self.max_hold_days:
            return ExitDecision(reason="rcdb_time_exit")

        return None

    @property
    def _dip_col(self) -> str:
        return f"dip_return_{self.dip_lookback_days}"

    @property
    def _rsi_col(self) -> str:
        return f"rsi{self.rsi_window}"

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

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
class RcdbV2Strategy(Strategy):
    """RCDB v2: vol-normalized dip + reversal confirmation + reversion exit."""

    name: str = "rcdb_v2"
    regime_ticker: str = "KRW-BTC"
    regime_ma_window: int = 120
    dip_lookback_days: int = 5
    vol_window: int = 20
    dip_z_threshold: float = -1.75
    rsi_window: int = 14
    rsi_threshold: float = 35.0
    reversal_ema_window: int = 5
    max_hold_days: int = 5
    atr_window: int = 14
    atr_trailing_mult: float = 2.0

    def __post_init__(self) -> None:
        if not self.regime_ticker:
            raise ValueError("regime_ticker must be non-empty")
        if self.regime_ma_window < 2:
            raise ValueError("regime_ma_window must be >= 2")
        if self.dip_lookback_days < 1:
            raise ValueError("dip_lookback_days must be >= 1")
        if self.vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        if self.dip_z_threshold >= 0:
            raise ValueError("dip_z_threshold must be < 0")
        if self.rsi_window < 2:
            raise ValueError("rsi_window must be >= 2")
        if not (0 < self.rsi_threshold < 100):
            raise ValueError("rsi_threshold must be between 0 and 100")
        if self.reversal_ema_window < 1:
            raise ValueError("reversal_ema_window must be >= 1")
        if self.max_hold_days < 1:
            raise ValueError("max_hold_days must be >= 1")
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
        regime_on = last.get("regime_on")
        dip_score = last.get(self._dip_score_col)
        rsi = last.get(self._rsi_col)
        reversal_ema = last.get(self._reversal_ema_col)

        if not self._is_true(regime_on):
            return Signal.HOLD
        if not all(
            self._is_finite(value)
            for value in (prev_close, dip_score, rsi, reversal_ema)
        ):
            return Signal.HOLD

        reversal_confirmed = (
            snap.current_price > float(prev_close)
            or snap.current_price > float(reversal_ema)
        )
        if (
            float(dip_score) <= self.dip_z_threshold
            and float(rsi) <= self.rsi_threshold
            and reversal_confirmed
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
        regime_on = last.get("regime_on")
        dip_score = last.get(self._dip_score_col)

        if self._is_finite(low) and self._is_finite(atr):
            trailing_stop = position.highest_high - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(reason="rcdb_v2_trailing_exit", exit_price=trailing_stop)

        if self._is_false(regime_on):
            return ExitDecision(reason="rcdb_v2_regime_off")

        if self._is_finite(dip_score) and float(dip_score) >= 0.0:
            return ExitDecision(reason="rcdb_v2_reversion_exit")

        if position.hold_days >= self.max_hold_days:
            return ExitDecision(reason="rcdb_v2_time_exit")

        return None

    @property
    def _dip_score_col(self) -> str:
        return f"dip_score_{self.dip_lookback_days}_{self.vol_window}"

    @property
    def _rsi_col(self) -> str:
        return f"rsi{self.rsi_window}"

    @property
    def _reversal_ema_col(self) -> str:
        return f"reversal_ema{self.reversal_ema_window}"

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

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
class RegimePullbackContinuation30mStrategy(Strategy):
    """Daily/BTC regime + 1H trend pullback + 30m continuation trigger.

    This strategy is deliberately not a mean-reversion exit strategy.  It buys
    pullbacks only when the higher timeframe trend remains intact and exits via
    protective stop, ATR trailing, trend deterioration, regime-off, or max-hold.
    """

    name: str = "regime_pullback_continuation_30m"
    regime_ticker: str = "KRW-BTC"
    setup_ticker: str | None = None
    daily_regime_ma_window: int = 100
    trend_ema_fast_1h: int = 20
    trend_ema_slow_1h: int = 60
    trend_slope_lookback_1h: int = 3
    pullback_lookback_1h: int = 8
    pullback_min_pct: float = -0.045
    pullback_max_pct: float = -0.012
    pullback_ema_buffer_pct: float = 0.012
    setup_rsi_window: int = 14
    setup_rsi_min: float = 35.0
    setup_rsi_recovery: float = 40.0
    trigger_ema_fast_30m: int = 8
    trigger_ema_slow_30m: int = 21
    trigger_breakout_lookback_30m: int = 6
    trigger_volume_window_30m: int = 20
    trigger_volume_mult: float = 1.1
    trigger_close_location_min: float = 0.55
    trigger_rsi_momentum_min: float = 3.0
    trigger_rsi_min: float = 45.0
    trigger_required_votes: int = 2
    atr_window: int = 14
    initial_stop_atr_mult: float = 1.5
    atr_trailing_mult: float = 2.5
    trend_exit_mode: str = "close_below_ema20"
    max_hold_bars_30m: int = 96

    def __post_init__(self) -> None:
        if not self.regime_ticker:
            raise ValueError("regime_ticker must be non-empty")
        if self.daily_regime_ma_window < 2:
            raise ValueError("daily_regime_ma_window must be >= 2")
        if self.trend_ema_fast_1h < 1:
            raise ValueError("trend_ema_fast_1h must be >= 1")
        if self.trend_ema_slow_1h <= self.trend_ema_fast_1h:
            raise ValueError("trend_ema_slow_1h must be > trend_ema_fast_1h")
        if self.trend_slope_lookback_1h < 1:
            raise ValueError("trend_slope_lookback_1h must be >= 1")
        if self.pullback_lookback_1h < 1:
            raise ValueError("pullback_lookback_1h must be >= 1")
        if self.pullback_min_pct >= self.pullback_max_pct:
            raise ValueError("pullback_min_pct must be < pullback_max_pct")
        if self.pullback_max_pct >= 0:
            raise ValueError("pullback_max_pct must be < 0")
        if self.pullback_ema_buffer_pct < 0:
            raise ValueError("pullback_ema_buffer_pct must be >= 0")
        if self.setup_rsi_window < 2:
            raise ValueError("setup_rsi_window must be >= 2")
        if not (0 < self.setup_rsi_min < 100):
            raise ValueError("setup_rsi_min must be between 0 and 100")
        if not (0 < self.setup_rsi_recovery < 100):
            raise ValueError("setup_rsi_recovery must be between 0 and 100")
        if self.trigger_ema_fast_30m < 1:
            raise ValueError("trigger_ema_fast_30m must be >= 1")
        if self.trigger_ema_slow_30m <= self.trigger_ema_fast_30m:
            raise ValueError("trigger_ema_slow_30m must be > trigger_ema_fast_30m")
        if self.trigger_breakout_lookback_30m < 1:
            raise ValueError("trigger_breakout_lookback_30m must be >= 1")
        if self.trigger_volume_window_30m < 1:
            raise ValueError("trigger_volume_window_30m must be >= 1")
        if self.trigger_volume_mult <= 0:
            raise ValueError("trigger_volume_mult must be > 0")
        if not (0 <= self.trigger_close_location_min <= 1):
            raise ValueError("trigger_close_location_min must be between 0 and 1")
        if self.trigger_required_votes < 1:
            raise ValueError("trigger_required_votes must be >= 1")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.initial_stop_atr_mult <= 0:
            raise ValueError("initial_stop_atr_mult must be > 0")
        if self.atr_trailing_mult <= 0:
            raise ValueError("atr_trailing_mult must be > 0")
        if self.trend_exit_mode not in {"close_below_ema20", "ema20_below_ema60"}:
            raise ValueError("trend_exit_mode must be close_below_ema20 or ema20_below_ema60")
        if self.max_hold_bars_30m < 1:
            raise ValueError("max_hold_bars_30m must be >= 1")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.has_position or snap.current_price <= 0 or len(snap.df) < 2:
            return Signal.HOLD
        last = snap.df.iloc[-1]
        if not self._daily_regime_ok(last):
            return Signal.HOLD
        if not self._hourly_trend_ok(last):
            return Signal.HOLD
        if not self._hourly_pullback_ok(last):
            return Signal.HOLD
        if self._trigger_votes(snap) < self.trigger_required_votes:
            return Signal.HOLD
        return Signal.BUY

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
        if self._is_finite(low) and self._is_finite(atr):
            initial_stop = position.entry_price - float(atr) * self.initial_stop_atr_mult
            if initial_stop > 0 and float(low) <= initial_stop:
                return ExitDecision(
                    reason="regime_pullback_continuation_30m_initial_stop",
                    exit_price=initial_stop,
                )
            trailing_stop = position.highest_high - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(
                    reason="regime_pullback_continuation_30m_trailing_exit",
                    exit_price=trailing_stop,
                )

        if self._trend_exit(last):
            return ExitDecision(reason="regime_pullback_continuation_30m_trend_exit")

        if self._is_false(last.get("daily_regime_on")):
            return ExitDecision(reason="regime_pullback_continuation_30m_regime_off_exit")

        hold_bars = position.hold_bars if position.hold_bars is not None else position.hold_days
        if hold_bars >= self.max_hold_bars_30m:
            return ExitDecision(reason="regime_pullback_continuation_30m_time_exit")
        return None

    def _daily_regime_ok(self, last) -> bool:
        return self._is_true(last.get("daily_regime_on"))

    def _hourly_trend_ok(self, last) -> bool:
        hourly_close = last.get("hourly_close")
        slow = last.get(self._hourly_ema_slow_col)
        slope = last.get(self._hourly_slope_col)
        if not self._is_true(last.get("hourly_trend_on")):
            return False
        if not all(self._is_finite(v) for v in (hourly_close, slow, slope)):
            return False
        if float(slope) < 0:
            return False
        return float(hourly_close) >= float(slow) * (1.0 - self.pullback_ema_buffer_pct)

    def _hourly_pullback_ok(self, last) -> bool:
        pullback = last.get(self._hourly_pullback_col)
        rsi = last.get(self._hourly_rsi_col)
        rsi_recent_min = last.get(self._hourly_rsi_recent_min_col)
        if not all(self._is_finite(v) for v in (pullback, rsi, rsi_recent_min)):
            return False
        p = float(pullback)
        return (
            self.pullback_min_pct <= p <= self.pullback_max_pct
            and float(rsi_recent_min) <= self.setup_rsi_min
            and float(rsi) >= self.setup_rsi_recovery
        )

    def _trigger_votes(self, snap: MarketSnapshot) -> int:
        last = snap.df.iloc[-1]
        prev = snap.df.iloc[-2]
        votes = 0

        fast = last.get(self._trigger_ema_fast_col)
        slow = last.get(self._trigger_ema_slow_col)
        if all(self._is_finite(v) for v in (fast, slow)) and snap.current_price > float(fast) > float(slow):
            votes += 1

        recent_high = last.get(self._trigger_recent_high_col)
        if self._is_finite(recent_high) and snap.current_price > float(recent_high):
            votes += 1

        clv = last.get("close_location_value")
        if self._is_finite(clv) and float(clv) >= self.trigger_close_location_min:
            votes += 1

        volume = last.get("volume")
        volume_mean = last.get(self._trigger_volume_mean_col)
        if all(self._is_finite(v) for v in (volume, volume_mean)) and float(volume) > float(volume_mean) * self.trigger_volume_mult:
            votes += 1

        rsi = last.get(self._rsi_col)
        prev_rsi = prev.get(self._rsi_col)
        if (
            all(self._is_finite(v) for v in (rsi, prev_rsi))
            and float(rsi) >= self.trigger_rsi_min
            and float(rsi) - float(prev_rsi) >= self.trigger_rsi_momentum_min
        ):
            votes += 1
        return votes

    def _trend_exit(self, last) -> bool:
        fast = last.get(self._hourly_ema_fast_col)
        slow = last.get(self._hourly_ema_slow_col)
        hourly_close = last.get("hourly_close")
        if self.trend_exit_mode == "ema20_below_ema60":
            return all(self._is_finite(v) for v in (fast, slow)) and float(fast) < float(slow)
        return all(self._is_finite(v) for v in (hourly_close, fast)) and float(hourly_close) < float(fast)

    @property
    def _hourly_ema_fast_col(self) -> str:
        return f"hourly_ema_fast{self.trend_ema_fast_1h}"

    @property
    def _hourly_ema_slow_col(self) -> str:
        return f"hourly_ema_slow{self.trend_ema_slow_1h}"

    @property
    def _hourly_slope_col(self) -> str:
        return f"hourly_ema_fast_slope{self.trend_slope_lookback_1h}"

    @property
    def _hourly_pullback_col(self) -> str:
        return f"hourly_pullback_return_{self.pullback_lookback_1h}"

    @property
    def _hourly_rsi_col(self) -> str:
        return f"hourly_rsi{self.setup_rsi_window}"

    @property
    def _hourly_rsi_recent_min_col(self) -> str:
        return f"hourly_rsi_recent_min{self.pullback_lookback_1h}"

    @property
    def _trigger_ema_fast_col(self) -> str:
        return f"trigger_ema_fast{self.trigger_ema_fast_30m}"

    @property
    def _trigger_ema_slow_col(self) -> str:
        return f"trigger_ema_slow{self.trigger_ema_slow_30m}"

    @property
    def _trigger_recent_high_col(self) -> str:
        return f"trigger_recent_high{self.trigger_breakout_lookback_30m}"

    @property
    def _trigger_volume_mean_col(self) -> str:
        return f"trigger_volume_mean{self.trigger_volume_window_30m}"

    @property
    def _rsi_col(self) -> str:
        return f"rsi{self.setup_rsi_window}"

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

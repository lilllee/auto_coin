"""BTC regime + alt relative strength + 1H trend + 30m breakout continuation.

Approved for Stage 2 only after ``regime_relative_strength_event_study`` PASSED
with the daily-regime no-lookahead patch applied.  Entry logic mirrors the
winning ``regime_rs_trend_volume_breakout`` event set.  No reversion exit;
exits are protective only (ATR stop, ATR trailing, 1H trend deterioration,
BTC regime off, time safety).
"""

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
class RegimeRelativeBreakout30mStrategy(Strategy):
    name: str = "regime_relative_breakout_30m"
    regime_ticker: str = "KRW-BTC"
    daily_regime_ma_window: int = 100
    rs_24h_bars_30m: int = 48
    rs_7d_bars_30m: int = 336
    hourly_ema_fast: int = 20
    hourly_ema_slow: int = 60
    hourly_slope_lookback: int = 3
    breakout_lookback_30m: int = 6
    volume_window_30m: int = 20
    volume_mult: float = 1.2
    close_location_min: float = 0.55
    atr_window: int = 14
    initial_stop_atr_mult: float = 2.0
    atr_trailing_mult: float = 3.0
    trend_exit_confirm_bars: int = 2
    max_hold_bars_30m: int = 48

    def __post_init__(self) -> None:
        if not self.regime_ticker:
            raise ValueError("regime_ticker must be non-empty")
        if self.daily_regime_ma_window < 2:
            raise ValueError("daily_regime_ma_window must be >= 2")
        if self.rs_24h_bars_30m < 1:
            raise ValueError("rs_24h_bars_30m must be >= 1")
        if self.rs_7d_bars_30m <= self.rs_24h_bars_30m:
            raise ValueError("rs_7d_bars_30m must be > rs_24h_bars_30m")
        if self.hourly_ema_fast < 1:
            raise ValueError("hourly_ema_fast must be >= 1")
        if self.hourly_ema_slow <= self.hourly_ema_fast:
            raise ValueError("hourly_ema_slow must be > hourly_ema_fast")
        if self.hourly_slope_lookback < 1:
            raise ValueError("hourly_slope_lookback must be >= 1")
        if self.breakout_lookback_30m < 1:
            raise ValueError("breakout_lookback_30m must be >= 1")
        if self.volume_window_30m < 1:
            raise ValueError("volume_window_30m must be >= 1")
        if self.volume_mult <= 0:
            raise ValueError("volume_mult must be > 0")
        if not (0.0 <= self.close_location_min <= 1.0):
            raise ValueError("close_location_min must be between 0 and 1")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.initial_stop_atr_mult <= 0:
            raise ValueError("initial_stop_atr_mult must be > 0")
        if self.atr_trailing_mult <= 0:
            raise ValueError("atr_trailing_mult must be > 0")
        if self.trend_exit_confirm_bars < 1:
            raise ValueError("trend_exit_confirm_bars must be >= 1")
        if self.max_hold_bars_30m < 1:
            raise ValueError("max_hold_bars_30m must be >= 1")

    # ------------------------------------------------------------------
    # entry
    # ------------------------------------------------------------------

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.has_position or snap.current_price <= 0 or snap.df.empty:
            return Signal.HOLD
        last = snap.df.iloc[-1]

        if not self._is_true(last.get("btc_daily_regime_on")):
            return Signal.HOLD

        if not self._rs_positive(last):
            return Signal.HOLD

        if not self._hourly_trend_ok(last):
            return Signal.HOLD

        if not self._breakout_ok(last, snap.current_price):
            return Signal.HOLD

        if not self._volume_ok(last):
            return Signal.HOLD

        return Signal.BUY

    def _rs_positive(self, last) -> bool:
        rs_24 = last.get("target_rs_24h_vs_btc")
        rs_7d = last.get("target_rs_7d_vs_btc")
        if not all(self._is_finite(v) for v in (rs_24, rs_7d)):
            return False
        return float(rs_24) > 0 and float(rs_7d) > 0

    def _hourly_trend_ok(self, last) -> bool:
        hc = last.get("hourly_close")
        fast = last.get(self._hourly_ema_fast_col)
        slow = last.get(self._hourly_ema_slow_col)
        slope = last.get(self._hourly_slope_col)
        if not all(self._is_finite(v) for v in (hc, fast, slow, slope)):
            return False
        return float(hc) > float(fast) > float(slow) and float(slope) >= 0

    def _breakout_ok(self, last, current_price: float) -> bool:
        prior_high = last.get(self._prior_high_col)
        clv = last.get("close_location_value")
        close = last.get("close")
        if not all(self._is_finite(v) for v in (prior_high, clv, close)):
            return False
        # Prefer bar close for entry continuity with the event-study semantics;
        # current_price is the simulated execution reference, not the bar close.
        if float(close) <= float(prior_high):
            return False
        return float(clv) >= self.close_location_min

    def _volume_ok(self, last) -> bool:
        vol = last.get("volume")
        vol_ma = last.get(self._volume_ma_col)
        if not all(self._is_finite(v) for v in (vol, vol_ma)):
            return False
        return float(vol) > float(vol_ma) * self.volume_mult

    # ------------------------------------------------------------------
    # exit
    # ------------------------------------------------------------------

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
                    reason=f"{self.name}_initial_stop",
                    exit_price=initial_stop,
                )
            trailing_stop = position.highest_high - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(
                    reason=f"{self.name}_trailing_exit",
                    exit_price=trailing_stop,
                )

        if self._trend_exit_confirmed(last):
            return ExitDecision(reason=f"{self.name}_trend_exit")

        if self._is_false(last.get("btc_daily_regime_on")):
            return ExitDecision(reason=f"{self.name}_regime_off_exit")

        hold_bars = position.hold_bars if position.hold_bars is not None else position.hold_days
        if hold_bars >= self.max_hold_bars_30m:
            return ExitDecision(reason=f"{self.name}_time_exit")
        return None

    def _trend_exit_confirmed(self, last) -> bool:
        """True when the most-recent-completed 1H run of ``close < EMA20`` has
        reached ``trend_exit_confirm_bars`` hourly bars."""
        run = last.get(self._hourly_below_run_col)
        if not self._is_finite(run):
            return False
        return int(run) >= self.trend_exit_confirm_bars

    # ------------------------------------------------------------------
    # column accessors
    # ------------------------------------------------------------------

    @property
    def _hourly_ema_fast_col(self) -> str:
        return f"hourly_ema{self.hourly_ema_fast}"

    @property
    def _hourly_ema_slow_col(self) -> str:
        return f"hourly_ema{self.hourly_ema_slow}"

    @property
    def _hourly_slope_col(self) -> str:
        return f"hourly_ema{self.hourly_ema_fast}_slope_{self.hourly_slope_lookback}"

    @property
    def _hourly_below_run_col(self) -> str:
        return f"hourly_close_below_ema{self.hourly_ema_fast}_run"

    @property
    def _prior_high_col(self) -> str:
        return f"prior_high_{self.breakout_lookback_30m}"

    @property
    def _volume_ma_col(self) -> str:
        return f"volume_ma_{self.volume_window_30m}"

    @property
    def _atr_col(self) -> str:
        return f"atr{self.atr_window}"

    # ------------------------------------------------------------------
    # utils
    # ------------------------------------------------------------------

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

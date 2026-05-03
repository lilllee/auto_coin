from __future__ import annotations

import math
from dataclasses import dataclass

from auto_coin.strategy.base import MarketSnapshot, Signal, Strategy

_VALID_HTF_MODES = frozenset({"off", "htf_close_above_ema", "htf_ema_fast_slow"})
_VALID_RSI_MODES = frozenset({"off", "lt_70", "in_30_70", "lt_75", "in_40_70"})
_VALID_VOLUME_MODES = frozenset({"off", "ge_1_0", "ge_1_2", "ge_1_5"})
_VALID_DAILY_MODES = frozenset({"off", "self_above_sma200", "self_above_sma100"})


@dataclass(frozen=True)
class VwapEmaPullbackStrategy(Strategy):
    """Long-only VWAP direction + EMA pullback strategy.

    Phase 1 intentionally excludes short entries and active Volume Profile
    filtering.  SELL means spot-position exit only when already holding.

    Phase 2 adds opt-in entry-side filters (HTF trend, RSI floor, volume gate,
    daily regime).  All filter modes default to ``"off"`` so behavior is
    backward-compatible with P1 candidates.  When a mode is set but the
    required enricher column is absent, the helper returns ``False`` (BUY
    blocked) — conservative fallback so a half-configured run never produces
    spurious BUY signals.
    """

    name: str = "vwap_ema_pullback"
    ema_period: int = 9
    vwap_period: int = 48
    ema_touch_tolerance: float = 0.003
    sideways_lookback: int = 12
    max_vwap_cross_count: int = 3
    min_ema_slope_ratio: float = 0.001
    require_bullish_candle: bool = True
    use_volume_profile: bool = False
    exit_mode: str = "close_below_ema"
    exit_confirm_bars: int = 2
    exit_atr_multiplier: float = 0.3
    atr_window: int = 14
    volume_profile_lookback: int = 48
    volume_profile_bin_count: int = 24
    volume_gap_threshold: float = 0.3
    # ----- P2 entry-side filters (default "off" — backward compat) -----
    htf_trend_filter_mode: str = "off"
    rsi_filter_mode: str = "off"
    rsi_window: int = 14
    volume_filter_mode: str = "off"
    volume_mean_window: int = 20
    daily_regime_filter_mode: str = "off"
    daily_regime_ma_window: int = 200

    def __post_init__(self) -> None:
        if self.ema_period < 1:
            raise ValueError("ema_period must be >= 1")
        if self.vwap_period < 1:
            raise ValueError("vwap_period must be >= 1")
        if self.ema_touch_tolerance < 0:
            raise ValueError("ema_touch_tolerance must be >= 0")
        if self.sideways_lookback < 1:
            raise ValueError("sideways_lookback must be >= 1")
        if self.max_vwap_cross_count < 0:
            raise ValueError("max_vwap_cross_count must be >= 0")
        if self.min_ema_slope_ratio < 0:
            raise ValueError("min_ema_slope_ratio must be >= 0")
        if self.exit_mode not in {"close_below_ema", "body_below_ema", "confirm_close_below_ema", "atr_buffer_exit"}:
            raise ValueError("exit_mode must be one of close_below_ema, body_below_ema, confirm_close_below_ema, atr_buffer_exit")
        if self.exit_confirm_bars < 1:
            raise ValueError("exit_confirm_bars must be >= 1")
        if self.exit_atr_multiplier < 0:
            raise ValueError("exit_atr_multiplier must be >= 0")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.volume_profile_lookback < 1:
            raise ValueError("volume_profile_lookback must be >= 1")
        if self.volume_profile_bin_count < 1:
            raise ValueError("volume_profile_bin_count must be >= 1")
        if self.volume_gap_threshold < 0:
            raise ValueError("volume_gap_threshold must be >= 0")
        if self.htf_trend_filter_mode not in _VALID_HTF_MODES:
            raise ValueError(
                f"htf_trend_filter_mode must be one of {sorted(_VALID_HTF_MODES)}"
            )
        if self.rsi_filter_mode not in _VALID_RSI_MODES:
            raise ValueError(
                f"rsi_filter_mode must be one of {sorted(_VALID_RSI_MODES)}"
            )
        if self.rsi_window < 2:
            raise ValueError("rsi_window must be >= 2")
        if self.volume_filter_mode not in _VALID_VOLUME_MODES:
            raise ValueError(
                f"volume_filter_mode must be one of {sorted(_VALID_VOLUME_MODES)}"
            )
        if self.volume_mean_window < 1:
            raise ValueError("volume_mean_window must be >= 1")
        if self.daily_regime_filter_mode not in _VALID_DAILY_MODES:
            raise ValueError(
                f"daily_regime_filter_mode must be one of {sorted(_VALID_DAILY_MODES)}"
            )
        if self.daily_regime_ma_window < 2:
            raise ValueError("daily_regime_ma_window must be >= 2")

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.current_price <= 0:
            return Signal.HOLD
        df = snap.df
        if df.empty or len(df) < self._min_required_rows:
            return Signal.HOLD

        last = df.iloc[-1]
        ema = self._finite(last.get(self._ema_col))
        close = self._finite(last.get("close"))
        open_ = self._finite(last.get("open"))
        vwap = self._finite(last.get("vwap"))
        if ema is None or close is None:
            return Signal.HOLD

        # Spot long-only exit. Never emit SELL when flat.
        if snap.has_position:
            if self._should_exit(df, last, close=close, open_=open_, ema=ema):
                return Signal.SELL
            return Signal.HOLD

        # Flat state: no short entry, even if price is below EMA/VWAP.
        if vwap is None:
            return Signal.HOLD
        if close <= vwap:
            return Signal.HOLD
        if not self._trend_above_vwap(df):
            return Signal.HOLD
        if self._is_sideways(last):
            return Signal.HOLD
        if not self._ema_pullback_touched(df):
            return Signal.HOLD
        if close < ema:
            return Signal.HOLD
        if self.require_bullish_candle and (open_ is None or close <= open_):
            return Signal.HOLD
        if not self._htf_trend_ok(last):
            return Signal.HOLD
        if not self._daily_regime_ok(last):
            return Signal.HOLD
        if not self._rsi_ok(last):
            return Signal.HOLD
        if not self._volume_ok(last):
            return Signal.HOLD
        if self.use_volume_profile and not self._volume_profile_ok(last):
            return Signal.HOLD
        return Signal.BUY


    def _should_exit(self, df, last, *, close: float, open_: float | None, ema: float) -> bool:
        if self.exit_mode == "close_below_ema":
            return close < ema
        if self.exit_mode == "body_below_ema":
            return open_ is not None and max(open_, close) < ema
        if self.exit_mode == "confirm_close_below_ema":
            recent = df.tail(self.exit_confirm_bars)
            if len(recent) < self.exit_confirm_bars:
                return False
            for _, row in recent.iterrows():
                row_close = self._finite(row.get("close"))
                row_ema = self._finite(row.get(self._ema_col))
                if row_close is None or row_ema is None or row_close >= row_ema:
                    return False
            return True
        if self.exit_mode == "atr_buffer_exit":
            atr = self._finite(last.get(self._atr_col))
            return atr is not None and close < ema - atr * self.exit_atr_multiplier
        return False

    @property
    def _ema_col(self) -> str:
        return f"ema{self.ema_period}"

    @property
    def _atr_col(self) -> str:
        return f"atr{self.atr_window}"

    @property
    def _min_required_rows(self) -> int:
        return max(self.ema_period, self.vwap_period, self.sideways_lookback, self.atr_window) + 2

    @staticmethod
    def _finite(value) -> float | None:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if math.isfinite(out) else None

    def _is_sideways(self, row) -> bool:
        explicit = row.get("is_sideways")
        if isinstance(explicit, bool):
            return explicit
        if explicit is not None and explicit == explicit:
            return bool(explicit)

        cross_count = self._finite(row.get("vwap_cross_count"))
        if cross_count is not None and cross_count > self.max_vwap_cross_count:
            return True
        slope = self._finite(row.get("ema_slope_ratio"))
        return slope is not None and abs(slope) < self.min_ema_slope_ratio

    def _trend_above_vwap(self, df) -> bool:
        window = df.tail(self.sideways_lookback)
        if len(window) < self.sideways_lookback:
            return False
        above = window.get("vwap_above")
        if above is None:
            return False
        valid = above.dropna()
        if len(valid) < self.sideways_lookback:
            return False
        # Stable long bias: more bars above VWAP than below, while cross-count
        # separately filters choppy oscillation.
        return int(valid.astype(bool).sum()) > len(valid) // 2

    def _ema_pullback_touched(self, df) -> bool:
        recent = df.tail(2)
        if recent.empty:
            return False
        for _, row in recent.iterrows():
            ema = self._finite(row.get(self._ema_col))
            low = self._finite(row.get("low"))
            close = self._finite(row.get("close"))
            if ema is None or low is None or close is None:
                continue
            if low <= ema * (1.0 + self.ema_touch_tolerance) and close >= ema:
                return True
        return False

    def _volume_profile_ok(self, row) -> bool:
        """Phase 1 placeholder: no active profile columns are required.

        The option exists for forward-compatible parameter persistence.  If a
        future enricher supplies a boolean gate, honor it; otherwise do not let
        an enabled-but-unimplemented placeholder create accidental BUY signals.
        """
        value = row.get("volume_profile_ok")
        return bool(value) if value is not None and value == value else False

    # ----- P2 entry-side filter helpers -----
    # Each helper short-circuits to True when its mode is "off" so P1 candidates
    # see no behavior change. When mode is set but the required column is
    # missing/NaN, the helper returns False — conservative fallback to avoid
    # spurious BUY signals from a half-configured run.

    @staticmethod
    def _bool_or_none(value) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        # Skip NaN
        if value != value:
            return None
        return bool(value)

    def _htf_trend_ok(self, row) -> bool:
        if self.htf_trend_filter_mode == "off":
            return True
        if self.htf_trend_filter_mode == "htf_close_above_ema":
            v = self._bool_or_none(row.get("htf_close_above_ema"))
            return v is True
        if self.htf_trend_filter_mode == "htf_ema_fast_slow":
            v = self._bool_or_none(row.get("htf_ema_fast_above_slow"))
            return v is True
        return True

    def _rsi_ok(self, row) -> bool:
        if self.rsi_filter_mode == "off":
            return True
        rsi = self._finite(row.get(f"rsi{self.rsi_window}"))
        if rsi is None:
            return False
        if self.rsi_filter_mode == "lt_70":
            return rsi < 70.0
        if self.rsi_filter_mode == "lt_75":
            return rsi < 75.0
        if self.rsi_filter_mode == "in_30_70":
            return 30.0 <= rsi <= 70.0
        if self.rsi_filter_mode == "in_40_70":
            return 40.0 <= rsi <= 70.0
        return True

    def _volume_ok(self, row) -> bool:
        if self.volume_filter_mode == "off":
            return True
        vol = self._finite(row.get("volume"))
        mean = self._finite(row.get(f"volume_mean{self.volume_mean_window}"))
        if vol is None or mean is None or mean <= 0:
            return False
        if self.volume_filter_mode == "ge_1_0":
            return vol >= mean * 1.0
        if self.volume_filter_mode == "ge_1_2":
            return vol >= mean * 1.2
        if self.volume_filter_mode == "ge_1_5":
            return vol >= mean * 1.5
        return True

    def _daily_regime_ok(self, row) -> bool:
        if self.daily_regime_filter_mode == "off":
            return True
        v = self._bool_or_none(row.get("daily_above_sma"))
        if v is None:
            return False
        return v

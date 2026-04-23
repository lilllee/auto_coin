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
class RegimeReclaim30mStrategy(Strategy):
    """Daily regime + 1H setup + 30m reclaim trigger mean reversion.

    구조:
    - Daily: close > SMA(100) → risk-on
    - 1H: pullback_return <= threshold AND RSI <= threshold → setup
    - 30m: reclaim trigger (A/B/C 중 1개 이상) → 진입

    Exit:
    - reversion_exit: 수익 실현 (mean reversion 목표 도달)
    - trailing_exit: ATR trailing (추세 반전 방어)
    - regime_off_exit: daily regime off → 리스크 차단
    - time_exit: safety fallback (최후 수단)
    """

    name: str = "regime_reclaim_30m"
    regime_ticker: str = "KRW-BTC"
    daily_regime_ma_window: int = 100
    hourly_pullback_bars: int = 8
    hourly_pullback_threshold_pct: float = -0.025
    setup_rsi_window: int = 14
    setup_rsi_threshold: float = 35.0
    trigger_reclaim_ema_window: int = 6
    trigger_rsi_rebound_threshold: float = 30.0
    max_hold_bars_30m: int = 36
    atr_window: int = 14
    atr_trailing_mult: float = 2.0
    min_hold_bars_30m: int = 0
    reversion_min_profit_pct: float = 0.0
    reversion_confirmation_type: str = "none"
    reversion_sma_window_override: int | None = None

    def __post_init__(self) -> None:
        if not self.regime_ticker:
            raise ValueError("regime_ticker must be non-empty")
        if self.daily_regime_ma_window < 2:
            raise ValueError("daily_regime_ma_window must be >= 2")
        if self.hourly_pullback_bars < 1:
            raise ValueError("hourly_pullback_bars must be >= 1")
        if self.hourly_pullback_threshold_pct >= 0:
            raise ValueError("hourly_pullback_threshold_pct must be < 0")
        if self.setup_rsi_window < 2:
            raise ValueError("setup_rsi_window must be >= 2")
        if not (0 < self.setup_rsi_threshold < 100):
            raise ValueError("setup_rsi_threshold must be between 0 and 100")
        if self.trigger_reclaim_ema_window < 1:
            raise ValueError("trigger_reclaim_ema_window must be >= 1")
        if self.trigger_rsi_rebound_threshold <= 0:
            raise ValueError("trigger_rsi_rebound_threshold_30m must be > 0")
        if self.max_hold_bars_30m < 1:
            raise ValueError("max_hold_bars_30m must be >= 1")
        if self.atr_window < 1:
            raise ValueError("atr_window must be >= 1")
        if self.atr_trailing_mult <= 0:
            raise ValueError("atr_trailing_mult must be > 0")
        if self.min_hold_bars_30m < 0:
            raise ValueError("min_hold_bars_30m must be >= 0")
        if self.reversion_min_profit_pct < 0:
            raise ValueError("reversion_min_profit_pct must be >= 0")
        if (
            self.reversion_sma_window_override is not None
            and self.reversion_sma_window_override < 1
        ):
            raise ValueError("reversion_sma_window_override must be >= 1 when set")
        valid_types = {"none", "rsi", "consecutive"}
        if self.reversion_confirmation_type not in valid_types:
            raise ValueError(f"reversion_confirmation_type must be one of {valid_types}")

    # ------------------------------------------------------------------
    # generate_signal: 30m trigger 기반 진입
    # ------------------------------------------------------------------

    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        if snap.has_position or snap.current_price <= 0:
            return Signal.HOLD
        if len(snap.df) < 2:
            return Signal.HOLD

        last = snap.df.iloc[-1]
        prev_close = snap.df.iloc[-2].get("close")

        # --- Daily regime check (must be ON) ---
        regime_on = last.get("daily_regime_on")
        if not self._is_true(regime_on):
            return Signal.HOLD

        # --- 1H setup check (pullback + RSI oversold) ---
        setup_pullback = last.get(self._setup_pullback_col)
        setup_rsi = last.get(self._setup_rsi_col)
        if not all(self._is_finite(v) for v in (setup_pullback, setup_rsi)):
            return Signal.HOLD
        if float(setup_pullback) > self.hourly_pullback_threshold_pct:
            return Signal.HOLD
        if float(setup_rsi) > self.setup_rsi_threshold:
            return Signal.HOLD

        # --- 30m trigger check (3 candidate types, OR logic) ---
        if not prev_close or not self._is_finite(prev_close):
            return Signal.HOLD

        trigger_a = self._trigger_a(snap, last, prev_close)
        trigger_b = self._trigger_b(snap, last, prev_close)
        trigger_c = self._trigger_c(snap, last, prev_close)

        if not any([trigger_a, trigger_b, trigger_c]):
            return Signal.HOLD

        return Signal.BUY

    def _trigger_a(self, snap, last, prev_close: float) -> bool:
        """Trigger A: close > prev_close AND close > reclaim_ema

        단순 모멘텀 반전 — 전 봉 종가 돌파 + EMA 복귀.
        가장 기본적이고 민감한 trigger.
        """
        reclaim_ema = last.get(self._reclaim_ema_col)
        if not self._is_finite(reclaim_ema):
            return False
        return snap.current_price > float(prev_close) and snap.current_price > float(reclaim_ema)

    def _trigger_b(self, snap, last, prev_close: float) -> bool:
        """Trigger B: close > reclaim_ema AND RSI rebound

        reclaim_ema 회복 + RSI 가파른 반등.
        Trigger A 보다 조금 더 conservative — RSI rebound 확인.
        """
        reclaim_ema = last.get(self._reclaim_ema_col)
        current_rsi = last.get(self._rsi_col)
        prev_rsi = snap.df.iloc[-2].get(self._rsi_col)
        if not all(self._is_finite(v) for v in (reclaim_ema, current_rsi, prev_rsi)):
            return False
        ema_reclaim = snap.current_price > float(reclaim_ema)
        rsi_rebound = float(current_rsi) > self.trigger_rsi_rebound_threshold
        # RSI 가파른 반등: 전 봉보다 3 포인트 이상 상승
        rsi_momentum = float(current_rsi) - float(prev_rsi) > 3.0
        return ema_reclaim and rsi_rebound and rsi_momentum

    def _trigger_c(self, snap, last, prev_close: float) -> bool:
        """Trigger C: low sweep 후 strong close

        저가 스윕 후 강한 종가 — wick reclaim 패턴.
        low가 전 봉 low 아래로 스윕되고, close 가 전 봉 close 위로 복귀.
        """
        prev_low = snap.df.iloc[-2].get("low")
        reclaim_ema = last.get(self._reclaim_ema_col)
        if not all(self._is_finite(v) for v in (prev_low, reclaim_ema)):
            return False
        # low sweep: 현재봉 low 가 전봉 low 아래로 떨어졌으나
        low_sweep = snap.current_price < float(prev_low)
        # strong close: 전 봉 close 위로 복귀
        strong_close = snap.current_price > float(prev_close)
        # 또는 reclaim_ema 위 복귀
        ema_recovery = snap.current_price > float(reclaim_ema)
        return low_sweep and (strong_close or ema_recovery)

    # ------------------------------------------------------------------
    # generate_exit: 4가지 exit 조건
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
        regime_on = last.get("daily_regime_on")
        reversion_sma = last.get(self._reversion_sma_col)
        current_rsi = last.get(self._rsi_col)
        hold_bars = position.hold_bars if position.hold_bars is not None else position.hold_days
        entry_price = position.entry_price

        # 1) ATR trailing stop — 보호성 exit 이므로 min_hold 와 무관하게 유지한다.
        if self._is_finite(low) and self._is_finite(atr):
            trailing_stop = position.highest_high - float(atr) * self.atr_trailing_mult
            if trailing_stop > 0 and float(low) <= trailing_stop:
                return ExitDecision(
                    reason="regime_reclaim_30m_trailing_exit",
                    exit_price=trailing_stop,
                )

        # 2) Regime off — 상위 리스크 차단. min_hold 는 reversion_exit 에만 적용한다.
        if self._is_false(regime_on):
            return ExitDecision(
                reason="regime_reclaim_30m_regime_off_exit",
            )

        # 3) Reversion exit — v1.1 재설계
        #    - min_hold: 진입 직후 얕은 평균선 터치 청산 방지
        #    - profit guard: 실제 이익이 일정 수준 이상일 때만 수익 실현
        #    - confirmation: "닿으면 판다"가 아니라 복귀 확인 후 청산
        min_hold_satisfied = (
            self.min_hold_bars_30m <= 0
            or hold_bars >= self.min_hold_bars_30m
        )
        if min_hold_satisfied and self._is_finite(reversion_sma) and entry_price > 0:
            profit_pct = (snap.current_price - entry_price) / entry_price
            if profit_pct >= self.reversion_min_profit_pct:
                confirm = False
                if self.reversion_confirmation_type == "none":
                    confirm = snap.current_price >= float(reversion_sma)
                elif self.reversion_confirmation_type == "rsi":
                    confirm = (
                        snap.current_price >= float(reversion_sma)
                        and self._is_finite(current_rsi)
                        and float(current_rsi) >= 50.0
                    )
                elif self.reversion_confirmation_type == "consecutive":
                    prev_close = snap.df.iloc[-2].get("close") if len(snap.df) >= 2 else None
                    prev_reversion_sma = (
                        snap.df.iloc[-2].get(self._reversion_sma_col)
                        if len(snap.df) >= 2
                        else None
                    )
                    confirm = (
                        snap.current_price >= float(reversion_sma)
                        and self._is_finite(prev_close)
                        and self._is_finite(prev_reversion_sma)
                        and float(prev_close) >= float(prev_reversion_sma)
                    )
                if confirm:
                    return ExitDecision(
                        reason="regime_reclaim_30m_reversion_exit",
                    )

        # 4) Time exit — safety fallback only (min_hold 통과)
        if hold_bars >= self.max_hold_bars_30m:
            return ExitDecision(
                reason="regime_reclaim_30m_time_exit",
            )

        return None

    # ------------------------------------------------------------------
    # Column name helpers
    # ------------------------------------------------------------------

    @property
    def _setup_pullback_col(self) -> str:
        return f"hourly_pullback_return_{self.hourly_pullback_bars}"

    @property
    def _setup_rsi_col(self) -> str:
        return f"rsi{self.setup_rsi_window}"

    @property
    def _rsi_col(self) -> str:
        return f"rsi{self.setup_rsi_window}"

    @property
    def _reclaim_ema_col(self) -> str:
        return f"reclaim_ema{self.trigger_reclaim_ema_window}"

    @property
    def _reversion_sma_col(self) -> str:
        window = self.reversion_sma_window_override or self.hourly_pullback_bars
        return f"reversion_sma{window}"

    @property
    def _atr_col(self) -> str:
        return f"atr{self.atr_window}"

    # ------------------------------------------------------------------
    # Utility
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

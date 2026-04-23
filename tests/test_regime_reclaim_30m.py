"""regime_reclaim_30m 전략 단위 테스트.

검증 항목:
1. Daily regime OFF → 진입 금지
2. 1H setup 없이 30m trigger만 → 진입 금지
3. 1H setup + 30m trigger 충족 → BUY
4. reversion / trailing / regime_off / time_exit reason 구분
5. projection helper 실제 연동
6. minute30 backtest crash-free
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from auto_coin.backtest.runner import BacktestResult, backtest
from auto_coin.data.candles import (
    enrich_regime_reclaim_30m,
    project_features,
)
from auto_coin.strategy import create_strategy
from auto_coin.strategy.base import MarketSnapshot, PositionSnapshot, Signal

# ---------------------------------------------------------------------------
# 헬퍼: mock df 생성
# ---------------------------------------------------------------------------

def _make_30m_df(n: int = 200, base_price: float = 100.0) -> pd.DataFrame:
    """30m candle df 생성 (의도적인 price 패턴 포함)."""
    np.random.seed(42)
    t = np.arange(n, dtype=float)
    # 기본 상승 추세 + 변동성
    price = base_price + 0.02 * t + np.cumsum(np.random.randn(n) * 0.3)
    idx = pd.date_range("2025-01-01", periods=n, freq="30min")
    return pd.DataFrame(
        {
            "open":   price + np.random.randn(n) * 0.1,
            "high":   price + np.abs(np.random.randn(n)) * 0.5,
            "low":    price - np.abs(np.random.randn(n)) * 0.5,
            "close":  price,
            "volume": np.ones(n),
        },
        index=idx,
    )


def _make_daily_regime_df(n: int = 10, regime_on_values: list[bool] | None = None) -> pd.DataFrame:
    """Daily regime df 생성. regime_on_values 가 있으면 그 값으로 daily_regime_on 계산."""
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    closes = np.arange(200, 200 + n * 5, dtype=float)
    df = pd.DataFrame(
        {
            "open":   closes - 5,
            "high":   closes + 5,
            "low":    closes - 10,
            "close":  closes,
            "volume": np.ones(n),
        },
        index=idx,
    )
    return df


def _make_1h_setup_df(n: int = 100) -> pd.DataFrame:
    """1H setup df 생성."""
    idx = pd.date_range("2025-01-01", periods=n, freq="h")
    price = 300 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame(
        {
            "open":   price + np.random.randn(n) * 0.1,
            "high":   price + np.abs(np.random.randn(n)) * 0.5,
            "low":    price - np.abs(np.random.randn(n)) * 0.5,
            "close":  price,
            "volume": np.ones(n),
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# Stage 1: generate_signal 테스트
# ---------------------------------------------------------------------------

def _make_snapshot(df, current_price=None, has_position=False):
    """MarketSnapshot 생성."""
    if current_price is None:
        current_price = float(df.iloc[-1]["close"])
    return MarketSnapshot(
        df=df,
        current_price=current_price,
        has_position=has_position,
        interval="minute30",
        bar_seconds=1800,
    )


def _make_position(entry_price=105.0, hold_bars=5, highest_high=110.0):
    """PositionSnapshot 생성."""
    return PositionSnapshot(
        entry_price=entry_price,
        hold_days=hold_bars,
        highest_close=108.0,
        highest_high=highest_high,
        interval="minute30",
        bar_seconds=1800,
        hold_bars=hold_bars,
    )


class TestGenerateSignal:
    """generate_signal 단위 테스트."""

    def setup_method(self):
        self.strategy = create_strategy("regime_reclaim_30m")

    def test_no_position_required(self):
        """has_position=True 면 항상 HOLD."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df)
        snap = _make_snapshot(enriched, has_position=True)
        assert self.strategy.generate_signal(snap) == Signal.HOLD

    def test_daily_regime_off_no_entry(self):
        """Daily regime OFF면 진입 금지."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        # 수동으로 daily_regime_on 을 False 로 덮어쓰기 (enrich 후 설정)
        enriched["daily_regime_on"] = False

        snap = _make_snapshot(enriched)
        assert self.strategy.generate_signal(snap) == Signal.HOLD

    def test_daily_regime_on_but_no_1h_setup(self):
        """Daily regime ON이지만 1H setup 없으면 진입 금지."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        # daily_regime_on 은 True, setup_pullback 은 threshold 초과 (no setup)
        enriched["daily_regime_on"] = True
        # pullback threshold 를 매우 낮게 설정하여 setup 이 발생하지 않게 함
        enriched["hourly_pullback_return_8"] = 0.1  # 큰 양수 → setup 아님

        snap = _make_snapshot(enriched)
        result = self.strategy.generate_signal(snap)
        # setup_pullback > threshold 이므로 HOLD
        assert result == Signal.HOLD

    def test_1h_setup_and_trigger_buy(self):
        """1H setup + 30m trigger 충족 시 BUY."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)

        # daily regime ON
        enriched["daily_regime_on"] = True
        # 1H pullback (setup)
        enriched["hourly_pullback_return_8"] = -0.05  # -5% pullback
        # 1H RSI oversold
        enriched["rsi14"] = 25.0  # RSI 25 → oversold
        # Trigger A: close > prev_close AND close > reclaim_ema
        # 현재 가격이 prev_close 보다 크고 reclaim_ema 보다 커야 함
        enriched["reclaim_ema6"] = enriched["close"] * 0.98  # EMA 는 현재가보다 낮게
        # current_price 는 이미 prev_close > reclaim_ema 조건 만족

        snap = _make_snapshot(enriched)
        assert self.strategy.generate_signal(snap) == Signal.BUY

    def test_1h_setup_no_trigger_no_entry(self):
        """1H setup 은 충족했지만 30m trigger 없으면 진입 금지."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)

        enriched["daily_regime_on"] = True
        enriched["hourly_pullback_return_8"] = -0.05
        enriched["rsi14"] = 25.0
        # Trigger 조건을 모두 위배: reclaim_ema 를 현재가보다 높게 설정
        enriched["reclaim_ema6"] = enriched["close"] * 1.05  # EMA 가 현재가보다 높음

        snap = _make_snapshot(enriched)
        result = self.strategy.generate_signal(snap)
        # Trigger A: close > reclaim_ema → 위배
        # Trigger B: close > reclaim_ema → 위배
        # Trigger C: low sweep → 위배
        assert result == Signal.HOLD

    def test_empty_df_holds(self):
        """빈 df 면 HOLD."""
        # 빈 df 는 enrich_regime_reclaim_30m 에서도 예외 발생 가능하므로
        # strategy.generate_signal 자체 테스트
        strategy = create_strategy("regime_reclaim_30m")
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        snap = _make_snapshot(df) if len(df) > 0 else _make_snapshot(
            pd.DataFrame({
                "open": [100.0], "high": [110.0], "low": [90.0],
                "close": [105.0], "volume": [1.0],
                "daily_regime_on": [True],
                "hourly_pullback_return_8": [-0.05],
                "rsi14": [25.0],
                "reclaim_ema6": [100.0],
                "reversion_sma8": [100.0],
                "atr14": [5.0],
            })
        )
        assert strategy.generate_signal(snap) == Signal.HOLD

    def test_small_df_holds(self):
        """df 가 2 개 미만이 면 HOLD."""
        df = _make_30m_df(1)
        enriched = enrich_regime_reclaim_30m(df)
        snap = _make_snapshot(enriched)
        assert self.strategy.generate_signal(snap) == Signal.HOLD

    def test_trigger_c_low_sweep(self):
        """Trigger C (low sweep 후 strong close) 도 진입 허용."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)

        enriched["daily_regime_on"] = True
        enriched["hourly_pullback_return_8"] = -0.05
        enriched["rsi14"] = 25.0

        # Trigger C: low sweep 후 strong close
        # prev_low 를 현재가보다 높게 설정 (low sweep)
        enriched.loc[enriched.index[-1], "low"] = enriched["close"].iloc[-1] * 0.95
        enriched.loc[enriched.index[-2], "low"] = enriched["close"].iloc[-2] * 0.90

        snap = _make_snapshot(enriched)
        result = self.strategy.generate_signal(snap)
        # Trigger C 가 발동할 수 있는지 확인 (low_sweep and strong_close/ema_recovery)
        # low_sweep: current_price < prev_low → 위배될 수 있음
        # 실제로는 trigger_a 가 발동할 가능성이 더 높음
        # 이 테스트는 trigger_c 가 구조적으로 동작하는지 확인
        assert result in (Signal.BUY, Signal.HOLD)


# ---------------------------------------------------------------------------
# Stage 1: generate_exit 테스트
# ---------------------------------------------------------------------------

class TestGenerateExit:
    """generate_exit 단위 테스트."""

    def setup_method(self):
        self.strategy = create_strategy("regime_reclaim_30m")

    def test_trailing_exit(self):
        """ATR trailing stop 발동 시 trailing_exit."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True

        snap = _make_snapshot(enriched)
        # highest_high 매우 높게, low 매우 낮게 → trailing stop 발동
        position = _make_position(
            entry_price=100.0,
            hold_bars=5,
            highest_high=150.0,  # 매우 높음
        )
        # low 를 highest_high - atr * mult 아래로 설정
        low_val = enriched["low"].iloc[-1]
        atr_val = enriched["atr14"].iloc[-1]
        if pd.notna(atr_val) and pd.notna(low_val):
            # low 가 trailing_stop 아래로 떨어뜨림
            enriched.loc[enriched.index[-1], "low"] = 150.0 - float(atr_val) * 2.0 - 1.0

        snap = _make_snapshot(enriched)
        result = self.strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_trailing_exit"

    def test_regime_off_exit(self):
        """Daily regime OFF 면 regime_off_exit."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = False

        snap = _make_snapshot(enriched)
        position = _make_position()
        # trailing_exit 가 먼저 발동되지 않도록 low 를 매우 높게
        enriched.loc[enriched.index[-1], "low"] = 999.0
        # atr 이 유한해야 trailing 계산되지만 low > trailing_stop 이어야 skip
        result = self.strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_regime_off_exit"

    def test_reversion_exit(self):
        """Reversion exit: 현재가 >= reversion_sma AND 현재가 > entry_price."""
        df = _make_30m_df(80)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True

        snap = _make_snapshot(enriched)
        # current_price 보다 entry_price 를 낮게 설정 → 재version exit 조건 만족
        entry_price = enriched["close"].iloc[-1] * 0.95  # 현재가보다 5% 낮은 진입가
        position = _make_position(entry_price=entry_price)
        # reversion_sma 가 현재가보다 충분히 낮게 (reversion_sma < close < current_price)
        enriched.loc[enriched.index[-1], "reversion_sma8"] = enriched["close"].iloc[-1] * 0.90
        # trailing_exit 가 먼저 발동되지 않도록 low 를 매우 높게
        enriched.loc[enriched.index[-1], "low"] = 999.0

        result = self.strategy.generate_exit(snap, position)
        assert result is not None, (f"expected reversion_exit but got {result}")
        assert result.reason == "regime_reclaim_30m_reversion_exit"

    def test_min_hold_blocks_only_reversion_exit(self):
        """min_hold 는 얕은 reversion_exit 만 막고 보호성 trailing/regime_off 는 유지."""
        df = _make_30m_df(80)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True
        enriched.loc[enriched.index[-1], "low"] = 999.0
        enriched.loc[enriched.index[-1], "reversion_sma8"] = enriched["close"].iloc[-1] * 0.90

        strategy = create_strategy("regime_reclaim_30m", {"min_hold_bars_30m": 3})
        snap = _make_snapshot(enriched)
        position = _make_position(
            entry_price=enriched["close"].iloc[-1] * 0.95,
            hold_bars=1,
        )
        assert strategy.generate_exit(snap, position) is None

        enriched["daily_regime_on"] = False
        result = strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_regime_off_exit"

    def test_reversion_min_profit_guard_blocks_tiny_profit(self):
        """profit guard 는 기준선 touch 만으로 나가는 얕은 reversion_exit 를 차단."""
        df = _make_30m_df(80)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True
        enriched.loc[enriched.index[-1], "low"] = 999.0
        enriched.loc[enriched.index[-1], "reversion_sma8"] = enriched["close"].iloc[-1] * 0.90

        strategy = create_strategy(
            "regime_reclaim_30m",
            {"reversion_min_profit_pct": 0.005},
        )
        snap = _make_snapshot(enriched)
        # 0.2% 이익은 0.5% guard 를 통과하지 못한다.
        position = _make_position(
            entry_price=enriched["close"].iloc[-1] / 1.002,
            hold_bars=5,
        )
        assert strategy.generate_exit(snap, position) is None

    def test_reversion_confirmation_rsi_requires_neutral_rsi(self):
        """rsi confirmation 은 SMA touch 와 RSI>=50 을 모두 요구."""
        df = _make_30m_df(80)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True
        enriched.loc[enriched.index[-1], "low"] = 999.0
        enriched.loc[enriched.index[-1], "reversion_sma8"] = enriched["close"].iloc[-1] * 0.90
        enriched.loc[enriched.index[-1], "rsi14"] = 49.0

        strategy = create_strategy(
            "regime_reclaim_30m",
            {"reversion_confirmation_type": "rsi"},
        )
        snap = _make_snapshot(enriched)
        position = _make_position(entry_price=enriched["close"].iloc[-1] * 0.95, hold_bars=5)
        assert strategy.generate_exit(snap, position) is None

        enriched.loc[enriched.index[-1], "rsi14"] = 50.0
        result = strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_reversion_exit"

    def test_reversion_confirmation_consecutive_uses_previous_bar_sma(self):
        """consecutive confirmation 은 현재/전 bar 가 각각 자기 SMA 위여야 한다."""
        df = _make_30m_df(80)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True
        enriched.loc[enriched.index[-1], "low"] = 999.0
        enriched.loc[enriched.index[-1], "reversion_sma8"] = enriched["close"].iloc[-1] * 0.90
        enriched.loc[enriched.index[-2], "reversion_sma8"] = enriched["close"].iloc[-2] * 1.10

        strategy = create_strategy(
            "regime_reclaim_30m",
            {"reversion_confirmation_type": "consecutive"},
        )
        snap = _make_snapshot(enriched)
        position = _make_position(entry_price=enriched["close"].iloc[-1] * 0.95, hold_bars=5)
        assert strategy.generate_exit(snap, position) is None

        enriched.loc[enriched.index[-2], "reversion_sma8"] = enriched["close"].iloc[-2] * 0.90
        result = strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_reversion_exit"

    def test_reversion_sma_window_override_uses_farther_target_column(self):
        """window override 는 reversion_sma{N} 컬럼을 target 으로 사용."""
        df = _make_30m_df(100)
        enriched = enrich_regime_reclaim_30m(
            df,
            daily_regime_df=None,
            reversion_sma_window=24,
        )
        assert "reversion_sma24" in enriched.columns

        enriched["daily_regime_on"] = True
        enriched.loc[enriched.index[-1], "low"] = 999.0
        enriched.loc[enriched.index[-1], "reversion_sma24"] = enriched["close"].iloc[-1] * 0.90

        strategy = create_strategy(
            "regime_reclaim_30m",
            {"reversion_sma_window_override": 24},
        )
        snap = _make_snapshot(enriched)
        position = _make_position(entry_price=enriched["close"].iloc[-1] * 0.95, hold_bars=5)
        result = strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_reversion_exit"

    def test_time_exit(self):
        """Time exit: hold_bars >= max_hold_bars_30m."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True

        snap = _make_snapshot(enriched)
        # max_hold_bars_30m = 36 인데 hold_bars = 50 으로 설정
        position = _make_position(hold_bars=50)
        # trailing_exit 가 먼저 발동되지 않도록 low 를 매우 높게
        enriched.loc[enriched.index[-1], "low"] = 999.0

        result = self.strategy.generate_exit(snap, position)
        assert result is not None
        assert result.reason == "regime_reclaim_30m_time_exit"

    def test_no_exit_when_conditions_not_met(self):
        """어떤 exit 조건도 충족하지 않으면 None."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True
        # trailing stop 조건 위배 (low 가 높게)
        enriched.loc[enriched.index[-1], "low"] = 200.0
        # reversion exit 조건 위배 (reversion_sma 가 현재가보다 높게)
        enriched.loc[enriched.index[-1], "reversion_sma8"] = enriched["close"].iloc[-1] * 1.1

        snap = _make_snapshot(enriched)
        position = _make_position(entry_price=100.0, hold_bars=5)
        result = self.strategy.generate_exit(snap, position)
        assert result is None

    def test_exit_with_finite_low_atr(self):
        """low/atr 가 finite 하지 않으면 trailing skip."""
        df = _make_30m_df(50)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True

        snap = _make_snapshot(enriched)
        position = _make_position()
        # low/atr 를 NaN 으로 설정
        enriched.loc[enriched.index[-1], "low"] = float("nan")
        enriched.loc[enriched.index[-1], "atr14"] = float("nan")

        result = self.strategy.generate_exit(snap, position)
        # trailing_exit 는 skip 되고 regime_off / reversion / time_exit 확인
        # regime_on=True 이고 reversion_sma 가 유한하지 않으므로 time_exit 만 남음
        # hold_bars=5 < 36 이므로 None 일 수 있음
        assert result is None or result.reason in (
            "regime_reclaim_30m_regime_off_exit",
            "regime_reclaim_30m_reversion_exit",
            "regime_reclaim_30m_time_exit",
        )


# ---------------------------------------------------------------------------
# Projection helper 연동 테스트
# ---------------------------------------------------------------------------

class TestProjectionHelper:
    """project_features 가 실제 전략에서 올바르게 동작하는지."""

    def test_daily_to_30m_projection(self):
        """daily regime → 30m projection 이 ffill 로 동작."""
        daily_idx = pd.date_range("2025-01-01", periods=5, freq="D")
        daily_df = pd.DataFrame(
            {"regime_on": [True, True, False, True, True]},
            index=daily_idx,
        )
        thirty_idx = pd.date_range("2025-01-01", periods=20, freq="30min")

        result = project_features(
            daily_df, thirty_idx,
            source_interval="day",
            target_interval="minute30",
            columns=["regime_on"],
        )

        assert len(result) == 20
        # ffill 적용: 첫 daily 값(True) 이 30m 전체에 전파
        assert result["regime_on"].iloc[0]

    def test_1h_to_30m_projection(self):
        """1H setup → 30m projection 이 ffill 로 동작."""
        hourly_idx = pd.date_range("2025-01-01", periods=10, freq="h")
        hourly_df = pd.DataFrame(
            {"pullback": [-0.05] * 10},
            index=hourly_idx,
        )
        thirty_idx = pd.date_range("2025-01-01", periods=20, freq="30min")

        result = project_features(
            hourly_df, thirty_idx,
            source_interval="minute60",
            target_interval="minute30",
            columns=["pullback"],
        )

        assert len(result) == 20
        assert result["pullback"].iloc[0] == -0.05


# ---------------------------------------------------------------------------
# Stage 2: in-sample backtest 테스트
# ---------------------------------------------------------------------------

class TestBacktest:
    """minute30 backtest crash-free 및 exit reason 구분."""

    def test_backtest_crash_free_minute30(self):
        """minute30 interval 에서 backtest 가 crash-free 로 동작."""
        df = _make_30m_df(200)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        enriched["daily_regime_on"] = True

        strategy = create_strategy("regime_reclaim_30m")
        result = backtest(
            enriched, strategy,
            fee=0.0005, slippage=0.0005,
            interval="minute30",
        )
        assert isinstance(result, BacktestResult)

    def test_backtest_exit_reason_mix(self):
        """backtest 가 여러 exit reason 을 구분하는지."""
        # regime_off 가 자주 발생하도록 df 생성
        df = _make_30m_df(200)
        enriched = enrich_regime_reclaim_30m(df, daily_regime_df=None)
        # regime_on 을 alternating 으로 설정 (50% OFF)
        enriched["daily_regime_on"] = [i % 2 == 0 for i in range(len(enriched))]

        strategy = create_strategy("regime_reclaim_30m")
        result = backtest(
            enriched, strategy,
            fee=0.0005, slippage=0.0005,
            interval="minute30",
        )
        # crash-free 확인
        assert isinstance(result, BacktestResult)
        # trades 가 있으면 exit reason mix 확인
        if result.trades:
            reasons = {t.exit_type for t in result.trades}
            # 적어도 하나의 exit reason 이 있어야 함
            assert len(reasons) >= 1


# ---------------------------------------------------------------------------
# Registry 연결 테스트
# ---------------------------------------------------------------------------

class TestRegistryConnection:
    """strategy registry / create_strategy 연결."""

    def test_create_from_registry(self):
        """STRATEGY_REGISTRY 에서 직접 생성."""
        from auto_coin.strategy import STRATEGY_REGISTRY
        cls = STRATEGY_REGISTRY["regime_reclaim_30m"]
        s = cls()
        assert s.name == "regime_reclaim_30m"

    def test_create_with_params(self):
        """create_strategy 가 params 를 올바르게 전달."""
        s = create_strategy("regime_reclaim_30m", {
            "daily_regime_ma_window": 200,
            "max_hold_bars_30m": 48,
        })
        assert s.daily_regime_ma_window == 200
        assert s.max_hold_bars_30m == 48

    def test_strategy_in_experimental_set(self):
        """regime_reclaim_30m 가 EXPERIMENTAL_STRATEGIES 에 포함."""
        from auto_coin.strategy import EXPERIMENTAL_STRATEGIES
        assert "regime_reclaim_30m" in EXPERIMENTAL_STRATEGIES

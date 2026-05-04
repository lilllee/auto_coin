from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from auto_coin.data.candles import enrich_for_strategy, enrich_vwap_ema_pullback
from auto_coin.strategy.base import MarketSnapshot, Signal
from auto_coin.strategy.vwap_ema_pullback import VwapEmaPullbackStrategy
from scripts.verify_vwap_ema_pullback import DEFAULT_SLIPPAGE, simulate_execution_trades


def _raw_df(n: int = 80, *, volume: float = 100.0) -> pd.DataFrame:
    close = np.linspace(100.0, 140.0, n)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, volume),
        },
        index=pd.date_range("2026-01-01", periods=n, freq="30min"),
    )


def _entry_df() -> pd.DataFrame:
    df = enrich_vwap_ema_pullback(_raw_df())
    ema = float(df.iloc[-1]["ema9"])
    # Force a clean same-bar EMA touch while preserving the already computed
    # shifted indicator values used by the strategy.
    df.iloc[-1, df.columns.get_loc("low")] = ema * 1.001
    df.iloc[-1, df.columns.get_loc("open")] = float(df.iloc[-1]["close"]) - 0.5
    df.iloc[-1, df.columns.get_loc("is_sideways")] = False
    return df


def test_enrich_vwap_ema_pullback_adds_required_columns():
    out = enrich_vwap_ema_pullback(_raw_df())
    for col in ("ema9", "vwap", "vwap_above", "vwap_cross_count", "ema_slope_ratio", "is_sideways"):
        assert col in out.columns
    assert out["ema9"].iloc[10] == pytest.approx(_raw_df()["close"].ewm(span=9, adjust=False).mean().iloc[9])
    assert np.isfinite(out["vwap"].dropna().iloc[-1])


def test_enrich_vwap_handles_zero_volume_without_error():
    out = enrich_vwap_ema_pullback(_raw_df(volume=0.0))
    assert "vwap" in out.columns
    assert out["vwap"].isna().all()


def test_enrich_vwap_uses_shifted_completed_candle_value():
    raw = _raw_df(60)
    out = enrich_vwap_ema_pullback(raw, vwap_period=5)
    typical = (raw["high"] + raw["low"] + raw["close"]) / 3.0
    expected_previous_raw_vwap = (typical.iloc[4:9] * raw["volume"].iloc[4:9]).sum() / raw["volume"].iloc[4:9].sum()
    assert out["vwap"].iloc[9] == pytest.approx(expected_previous_raw_vwap)


def test_enrich_for_strategy_routes_vwap_ema_pullback():
    out = enrich_for_strategy(_raw_df(), "vwap_ema_pullback", {"ema_period": 9, "vwap_period": 20})
    assert "ema9" in out.columns
    assert "vwap" in out.columns


def test_buy_when_vwap_above_ema_touch_bullish_and_not_sideways():
    df = _entry_df()
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_hold_when_close_not_above_vwap():
    df = _entry_df()
    df.iloc[-1, df.columns.get_loc("close")] = float(df.iloc[-1]["vwap"]) * 0.99
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_sideways_filter_blocks():
    df = _entry_df()
    df.iloc[-1, df.columns.get_loc("is_sideways")] = True
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_price_too_far_from_ema_pullback():
    df = _entry_df()
    df.iloc[-1, df.columns.get_loc("low")] = float(df.iloc[-1]["ema9"]) * 1.02
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_hold_when_candle_count_too_short():
    df = enrich_vwap_ema_pullback(_raw_df(20))
    s = VwapEmaPullbackStrategy(vwap_period=48)
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_sell_when_holding_and_close_below_ema():
    df = _entry_df()
    df.iloc[-1, df.columns.get_loc("close")] = float(df.iloc[-1]["ema9"]) * 0.99
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_hold_when_holding_and_close_above_ema():
    df = _entry_df()
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD


def test_never_sell_when_flat_even_if_close_below_ema():
    df = _entry_df()
    df.iloc[-1, df.columns.get_loc("close")] = float(df.iloc[-1]["ema9"]) * 0.99
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]), has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_invalid_params_raise():
    with pytest.raises(ValueError, match="ema_period"):
        VwapEmaPullbackStrategy(ema_period=0)
    with pytest.raises(ValueError, match="vwap_period"):
        VwapEmaPullbackStrategy(vwap_period=0)


def _exit_df(*, open_: float, close: float, ema: float = 100.0, atr: float = 10.0) -> pd.DataFrame:
    df = _entry_df()
    df.iloc[-1, df.columns.get_loc("open")] = open_
    df.iloc[-1, df.columns.get_loc("close")] = close
    if "atr14" not in df.columns:
        df["atr14"] = atr
    df.iloc[-1, df.columns.get_loc("ema9")] = ema
    df.iloc[-1, df.columns.get_loc("atr14")] = atr
    return df


def test_body_below_ema_requires_full_body_below():
    s = VwapEmaPullbackStrategy(exit_mode="body_below_ema")
    df = _exit_df(open_=101.0, close=99.0)
    snap = MarketSnapshot(df=df, current_price=99.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD

    df = _exit_df(open_=99.5, close=99.0)
    snap = MarketSnapshot(df=df, current_price=99.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_confirm_close_below_ema_requires_consecutive_closes():
    s = VwapEmaPullbackStrategy(exit_mode="confirm_close_below_ema", exit_confirm_bars=2)
    df = _entry_df()
    df.iloc[-2, df.columns.get_loc("close")] = 101.0
    df.iloc[-2, df.columns.get_loc("ema9")] = 100.0
    df.iloc[-1, df.columns.get_loc("close")] = 99.0
    df.iloc[-1, df.columns.get_loc("ema9")] = 100.0
    snap = MarketSnapshot(df=df, current_price=99.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD

    df.iloc[-2, df.columns.get_loc("close")] = 99.5
    snap = MarketSnapshot(df=df, current_price=99.0, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_atr_buffer_exit_requires_close_below_buffer():
    s = VwapEmaPullbackStrategy(exit_mode="atr_buffer_exit", exit_atr_multiplier=0.3)
    df = _exit_df(open_=101.0, close=98.0, ema=100.0, atr=10.0)
    snap = MarketSnapshot(df=df, current_price=98.0, has_position=True)
    assert s.generate_signal(snap) is Signal.HOLD

    df = _exit_df(open_=101.0, close=96.5, ema=100.0, atr=10.0)
    snap = MarketSnapshot(df=df, current_price=96.5, has_position=True)
    assert s.generate_signal(snap) is Signal.SELL


def test_enrich_adds_atr_for_atr_buffer_exit():
    out = enrich_vwap_ema_pullback(_raw_df())
    assert "atr14" in out.columns
    assert np.isfinite(out["atr14"].dropna().iloc[-1])


def _execution_df() -> pd.DataFrame:
    df = _raw_df(80)
    out = enrich_vwap_ema_pullback(df)
    # Make every row clearly non-sideways and VWAP-up so specific rows can
    # trigger BUY/SELL while the rest remain HOLD because they are not near EMA.
    out["vwap"] = 90.0
    out["vwap_above"] = True
    out["vwap_cross_count"] = 0
    out["ema_slope_ratio"] = 0.01
    out["is_sideways"] = False
    out["ema9"] = 100.0
    out["atr14"] = 10.0
    out["open"] = 120.0
    out["high"] = 121.0
    out["low"] = 115.0
    out["close"] = 120.0

    # Row 60 signal: BUY. Row 61 open must be used as entry in next_open mode.
    out.iloc[60, out.columns.get_loc("open")] = 104.0
    out.iloc[60, out.columns.get_loc("low")] = 100.1
    out.iloc[60, out.columns.get_loc("close")] = 105.0
    out.iloc[61, out.columns.get_loc("open")] = 110.0

    # Row 62 signal: SELL. Row 63 open must be used as exit in next_open mode.
    out.iloc[62, out.columns.get_loc("open")] = 96.0
    out.iloc[62, out.columns.get_loc("close")] = 95.0
    out.iloc[63, out.columns.get_loc("open")] = 90.0
    return out


def test_next_open_executes_buy_and_sell_at_following_open():
    trades = simulate_execution_trades(_execution_df(), {}, execution_mode="next_open", mark_to_market=False)
    assert len(trades) == 1
    assert trades[0]["entry"] == pytest.approx(110.0 * (1.0 + DEFAULT_SLIPPAGE))
    assert trades[0]["exit"] == pytest.approx(90.0 * (1.0 - DEFAULT_SLIPPAGE))
    assert trades[0]["hold_bars"] == 2


def test_next_open_ignores_last_candle_signal_without_next_open():
    df = _execution_df().iloc[:61].copy()
    trades = simulate_execution_trades(df, {}, execution_mode="next_open", mark_to_market=False)
    assert trades == []


def _cooldown_two_trade_df() -> pd.DataFrame:
    """Two-trade fixture: BUY60(exec61) → SELL62(exec63) → second BUY at row 64 and 66.

    rows 65 / 67 의 open 만 override 한다 — close/low 는 default 유지해서 해당 row 가
    스스로 BUY 신호를 내지 않게 한다. 만약 row 65 close 를 건드리면 ``_ema_pullback_touched``
    가 row 64 의 touch 를 그대로 인식해 row 65 자체에서 추가 BUY 신호가 나오므로 fixture
    의도가 깨진다.
    """
    out = _execution_df()
    # Second BUY trigger at row 64 (within cooldown window when cooldown_bars=2)
    out.iloc[64, out.columns.get_loc("open")] = 104.5
    out.iloc[64, out.columns.get_loc("low")] = 100.1
    out.iloc[64, out.columns.get_loc("close")] = 105.5
    # row 65 stays default (open=120 close=120 → not bullish → 자체 BUY 안 남)
    # Second BUY trigger at row 66 (after cooldown window when cooldown_bars=2)
    out.iloc[66, out.columns.get_loc("open")] = 104.5
    out.iloc[66, out.columns.get_loc("low")] = 100.1
    out.iloc[66, out.columns.get_loc("close")] = 105.5
    out.iloc[67, out.columns.get_loc("open")] = 112.0  # entry exec target if 66 BUY allowed
    return out


def test_cooldown_zero_matches_baseline_behavior():
    """cooldown_bars=0 옵션은 기존 동작과 완전 동일 (회귀 보장)."""
    base = simulate_execution_trades(
        _execution_df(), {}, execution_mode="next_open", mark_to_market=False,
    )
    same = simulate_execution_trades(
        _execution_df(), {}, execution_mode="next_open", mark_to_market=False,
        cooldown_bars=0,
    )
    assert len(same) == len(base) == 1
    assert same[0]["entry"] == pytest.approx(base[0]["entry"])
    assert same[0]["exit"] == pytest.approx(base[0]["exit"])
    assert same[0]["hold_bars"] == base[0]["hold_bars"]


def test_cooldown_blocks_buy_within_window():
    """cooldown_bars=2 → exit(row 63) 이후 row 64 BUY 차단, row 66 BUY 통과.

    next_open 모드:
      - cooldown=0: trade 2 entry at row 65 (signal at row 64).
      - cooldown=2: row 64 BUY blocked, row 66 BUY → trade 2 entry at row 67.

    open trade 가 SELL 없이 끝나므로 mark_to_market=True 로 닫는다.
    """
    df = _cooldown_two_trade_df()
    no_cd = simulate_execution_trades(
        df, {}, execution_mode="next_open", mark_to_market=True, cooldown_bars=0,
    )
    cd2 = simulate_execution_trades(
        df, {}, execution_mode="next_open", mark_to_market=True, cooldown_bars=2,
    )
    row_65_ts = str(df.index[65])
    row_67_ts = str(df.index[67])
    no_cd_entry_ts = [t["entry_ts"] for t in no_cd]
    cd2_entry_ts = [t["entry_ts"] for t in cd2]
    # cooldown=0 → trade 2 entry timestamp 는 row 65
    assert row_65_ts in no_cd_entry_ts
    # cooldown=2 → trade 2 entry timestamp 는 row 67 (row 65 는 cooldown 로 막힘)
    assert row_65_ts not in cd2_entry_ts
    assert row_67_ts in cd2_entry_ts


def test_cooldown_inactive_when_flat_initially():
    """초기 BUY (직전 SELL 없음) 는 cooldown 영향 없음."""
    trades = simulate_execution_trades(
        _execution_df(), {}, execution_mode="next_open", mark_to_market=False,
        cooldown_bars=10,  # 큰 값이라도 초기 BUY 는 통과
    )
    assert len(trades) == 1
    assert trades[0]["entry"] == pytest.approx(110.0 * (1.0 + DEFAULT_SLIPPAGE))


def test_cooldown_works_in_same_close_mode():
    """same_close 모드에서도 cooldown 이 BUY 신호를 차단.

    same_close: exit happens at bar 62 close (last_exit_i=62).
      - Row 64 BUY: 64-62=2 ≤ 2 → blocked.
      - Row 66 BUY: 66-62=4 > 2 → allowed.
    """
    df = _cooldown_two_trade_df()
    cd0 = simulate_execution_trades(
        df, {}, execution_mode="same_close", mark_to_market=True, cooldown_bars=0,
    )
    cd2 = simulate_execution_trades(
        df, {}, execution_mode="same_close", mark_to_market=True, cooldown_bars=2,
    )
    # row 64 close == row 66 close (105.5) 라서 가격으로 구분 불가 → entry_ts 로 검증
    cd0_entry_ts = [t["entry_ts"] for t in cd0]
    cd2_entry_ts = [t["entry_ts"] for t in cd2]
    # cooldown=0 should have an entry at row 64's timestamp; cooldown=2 should not.
    row_64_ts = str(df.index[64])
    row_66_ts = str(df.index[66])
    assert row_64_ts in cd0_entry_ts
    assert row_64_ts not in cd2_entry_ts
    assert row_66_ts in cd2_entry_ts


def test_cooldown_negative_value_rejected():
    with pytest.raises(ValueError, match="cooldown_bars"):
        simulate_execution_trades(
            _execution_df(), {}, execution_mode="next_open", cooldown_bars=-1,
        )


# =============================================================================
# P2 — entry-side filter tests
# Test spec: .omx/plans/test-spec-vwap-ema-pullback-p2-2026-05-04.md
# =============================================================================

# ---------------------------------------------------------------------------
# §2 Enricher tests
# ---------------------------------------------------------------------------

def _daily_df(n: int = 30) -> pd.DataFrame:
    """Synthetic daily candles (any close, fixed volume) for daily regime tests."""
    close = np.linspace(100.0, 130.0, n)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=pd.date_range("2026-01-01", periods=n, freq="D"),
    )


def _htf_df(n: int = 60) -> pd.DataFrame:
    """Synthetic 4h candles."""
    close = np.linspace(100.0, 150.0, n)
    return pd.DataFrame(
        {
            "open": close - 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 500.0),
        },
        index=pd.date_range("2026-01-01", periods=n, freq="4h"),
    )


def test_enrich_default_does_not_add_p2_columns():
    """P1 default 호출 시 P2 컬럼 0건 추가 — backward compat."""
    out = enrich_vwap_ema_pullback(_raw_df(80))
    p2_cols = {
        "rsi14", "volume_mean20",
        "htf_close_projected", "htf_ema20_projected", "htf_close_above_ema",
        "daily_close_projected", "daily_sma200_projected", "daily_above_sma",
    }
    assert not (p2_cols & set(out.columns)), \
        f"P1 default should not add P2 columns, found: {p2_cols & set(out.columns)}"


def test_enrich_with_rsi_window_adds_rsi_column():
    # RSI requires both up and down moves — _raw_df 의 monotonic rise 만으로는 NaN.
    # 작은 noise 추가해 finite 결과 보장.
    rng = np.random.default_rng(42)
    base = _raw_df(80)
    base["close"] = base["close"] + rng.normal(0, 0.5, 80)
    base["high"] = base[["high", "close"]].max(axis=1) + 0.1
    base["low"] = base[["low", "close"]].min(axis=1) - 0.1
    out = enrich_vwap_ema_pullback(base, rsi_window=14)
    assert "rsi14" in out.columns
    last_val = float(out["rsi14"].dropna().iloc[-1])
    assert 0 <= last_val <= 100
    assert np.isfinite(last_val)


def test_enrich_with_volume_mean_window_adds_volume_mean_column():
    out = enrich_vwap_ema_pullback(_raw_df(80), volume_mean_window=20)
    assert "volume_mean20" in out.columns
    # shifted: row N's volume_mean = mean of rows N-20..N-1's volume
    vol_mean_last = float(out["volume_mean20"].dropna().iloc[-1])
    assert vol_mean_last == pytest.approx(100.0)  # fixture has constant volume=100


def test_enrich_with_htf_df_adds_htf_columns():
    base_1h = _raw_df(200, volume=100.0)
    base_1h.index = pd.date_range("2026-01-01", periods=200, freq="60min")
    htf = _htf_df(60)
    out = enrich_vwap_ema_pullback(
        base_1h, htf_df=htf, htf_ema_window=20, htf_ema_slow_window=60,
    )
    for col in (
        "htf_close_projected",
        "htf_ema20_projected",
        "htf_ema60_projected",
        "htf_close_above_ema",
        "htf_ema_fast_above_slow",
    ):
        assert col in out.columns, f"missing {col}"
    # Projected boolean values exist as a real series
    above = out["htf_close_above_ema"].dropna()
    if not above.empty:
        # values are bool / boolean dtype
        assert bool(above.iloc[-1]) in (True, False)


def test_enrich_with_daily_df_adds_daily_regime_columns():
    base_1h = _raw_df(200)
    base_1h.index = pd.date_range("2026-01-01", periods=200, freq="60min")
    daily = _daily_df(30)
    out = enrich_vwap_ema_pullback(
        base_1h, daily_df=daily, daily_regime_ma_window=10,
    )
    assert "daily_close_projected" in out.columns
    assert "daily_sma10_projected" in out.columns
    assert "daily_above_sma" in out.columns


def test_enrich_handles_short_data_for_p2_columns():
    short = _raw_df(10)
    out = enrich_vwap_ema_pullback(short, rsi_window=14, volume_mean_window=20)
    assert "rsi14" in out.columns
    assert "volume_mean20" in out.columns
    # All NaN is fine; no exception raised.


def test_enrich_rsi_window_too_small_rejected():
    with pytest.raises(ValueError, match="rsi_window"):
        enrich_vwap_ema_pullback(_raw_df(80), rsi_window=1)


def test_enrich_volume_mean_window_too_small_rejected():
    with pytest.raises(ValueError, match="volume_mean_window"):
        enrich_vwap_ema_pullback(_raw_df(80), volume_mean_window=0)


# ---------------------------------------------------------------------------
# §3 Strategy filter tests
# ---------------------------------------------------------------------------

def _entry_df_with_p2_cols(
    *,
    htf_close_above_ema: bool | None = None,
    htf_ema_fast_above_slow: bool | None = None,
    rsi_value: float | None = None,
    rsi_window: int = 14,
    volume_value: float | None = None,
    volume_mean_value: float | None = None,
    volume_mean_window: int = 20,
    daily_above_sma: bool | None = None,
) -> pd.DataFrame:
    """`_entry_df()` 위에 P2 컬럼을 마지막 row 에 set 한 fixture."""
    df = _entry_df()
    last_idx = df.index[-1]
    if htf_close_above_ema is not None:
        df.loc[last_idx, "htf_close_above_ema"] = htf_close_above_ema
    if htf_ema_fast_above_slow is not None:
        df.loc[last_idx, "htf_ema_fast_above_slow"] = htf_ema_fast_above_slow
    if rsi_value is not None:
        df.loc[last_idx, f"rsi{rsi_window}"] = rsi_value
    if volume_value is not None:
        df.loc[last_idx, "volume"] = volume_value
    if volume_mean_value is not None:
        df.loc[last_idx, f"volume_mean{volume_mean_window}"] = volume_mean_value
    if daily_above_sma is not None:
        df.loc[last_idx, "daily_above_sma"] = daily_above_sma
    return df


def test_filter_default_off_preserves_p1_buy():
    df = _entry_df()
    s = VwapEmaPullbackStrategy()
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


# Axis A — htf_trend_filter

def test_htf_close_above_ema_blocks_when_below():
    df = _entry_df_with_p2_cols(htf_close_above_ema=False)
    s = VwapEmaPullbackStrategy(htf_trend_filter_mode="htf_close_above_ema")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_htf_close_above_ema_allows_when_true():
    df = _entry_df_with_p2_cols(htf_close_above_ema=True)
    s = VwapEmaPullbackStrategy(htf_trend_filter_mode="htf_close_above_ema")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_htf_filter_blocks_when_column_missing():
    """mode 만 켜고 enricher 안 켰을 때 false BUY 만들지 않도록 보수."""
    df = _entry_df()  # htf_close_above_ema 컬럼 자체 없음
    s = VwapEmaPullbackStrategy(htf_trend_filter_mode="htf_close_above_ema")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_htf_ema_fast_slow_blocks_when_inverted():
    df = _entry_df_with_p2_cols(htf_ema_fast_above_slow=False)
    s = VwapEmaPullbackStrategy(htf_trend_filter_mode="htf_ema_fast_slow")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_htf_ema_fast_slow_allows_when_aligned():
    df = _entry_df_with_p2_cols(htf_ema_fast_above_slow=True)
    s = VwapEmaPullbackStrategy(htf_trend_filter_mode="htf_ema_fast_slow")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


# Axis B — rsi_filter

def test_rsi_lt_70_blocks_when_overbought():
    df = _entry_df_with_p2_cols(rsi_value=75.0)
    s = VwapEmaPullbackStrategy(rsi_filter_mode="lt_70")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_rsi_lt_70_allows_when_below_70():
    df = _entry_df_with_p2_cols(rsi_value=55.0)
    s = VwapEmaPullbackStrategy(rsi_filter_mode="lt_70")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_rsi_in_30_70_blocks_when_below_30():
    df = _entry_df_with_p2_cols(rsi_value=25.0)
    s = VwapEmaPullbackStrategy(rsi_filter_mode="in_30_70")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_rsi_in_40_70_blocks_when_between_30_and_40():
    df = _entry_df_with_p2_cols(rsi_value=35.0)
    s = VwapEmaPullbackStrategy(rsi_filter_mode="in_40_70")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_rsi_filter_blocks_when_column_missing():
    df = _entry_df()  # rsi14 컬럼 없음
    s = VwapEmaPullbackStrategy(rsi_filter_mode="lt_70")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_rsi_lt_75_allows_at_72():
    df = _entry_df_with_p2_cols(rsi_value=72.0)
    s = VwapEmaPullbackStrategy(rsi_filter_mode="lt_75")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


# Axis C — volume_filter

def test_volume_ge_1_0_blocks_below_mean():
    df = _entry_df_with_p2_cols(volume_value=50.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_0")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_volume_ge_1_0_allows_at_or_above_mean():
    df = _entry_df_with_p2_cols(volume_value=100.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_0")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_volume_ge_1_2_blocks_at_mean():
    df = _entry_df_with_p2_cols(volume_value=100.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_2")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_volume_filter_blocks_when_column_missing():
    df = _entry_df()  # volume_mean20 컬럼 없음
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_0")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


# Axis D — daily_regime_filter

def test_daily_sma200_blocks_in_bear_regime():
    df = _entry_df_with_p2_cols(daily_above_sma=False)
    s = VwapEmaPullbackStrategy(daily_regime_filter_mode="self_above_sma200",
                                daily_regime_ma_window=200)
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


def test_daily_sma200_allows_in_bull_regime():
    df = _entry_df_with_p2_cols(daily_above_sma=True)
    s = VwapEmaPullbackStrategy(daily_regime_filter_mode="self_above_sma200",
                                daily_regime_ma_window=200)
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_daily_filter_blocks_when_column_missing():
    df = _entry_df()  # daily_above_sma 컬럼 없음
    s = VwapEmaPullbackStrategy(daily_regime_filter_mode="self_above_sma200",
                                daily_regime_ma_window=200)
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


# Combined

def test_all_filters_active_requires_all_pass():
    df = _entry_df_with_p2_cols(
        htf_close_above_ema=True,
        rsi_value=55.0,
        volume_value=120.0,
        volume_mean_value=100.0,
        daily_above_sma=True,
    )
    s = VwapEmaPullbackStrategy(
        htf_trend_filter_mode="htf_close_above_ema",
        rsi_filter_mode="lt_70",
        volume_filter_mode="ge_1_0",
        daily_regime_filter_mode="self_above_sma200",
        daily_regime_ma_window=200,
    )
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_all_filters_active_blocks_if_any_fails():
    df = _entry_df_with_p2_cols(
        htf_close_above_ema=True,
        rsi_value=55.0,
        volume_value=120.0,
        volume_mean_value=100.0,
        daily_above_sma=False,  # ← only this fails
    )
    s = VwapEmaPullbackStrategy(
        htf_trend_filter_mode="htf_close_above_ema",
        rsi_filter_mode="lt_70",
        volume_filter_mode="ge_1_0",
        daily_regime_filter_mode="self_above_sma200",
        daily_regime_ma_window=200,
    )
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD


# Validation

def test_invalid_filter_modes_rejected():
    with pytest.raises(ValueError, match="htf_trend_filter_mode"):
        VwapEmaPullbackStrategy(htf_trend_filter_mode="bogus")
    with pytest.raises(ValueError, match="rsi_filter_mode"):
        VwapEmaPullbackStrategy(rsi_filter_mode="bogus")
    with pytest.raises(ValueError, match="volume_filter_mode"):
        VwapEmaPullbackStrategy(volume_filter_mode="bogus")
    with pytest.raises(ValueError, match="daily_regime_filter_mode"):
        VwapEmaPullbackStrategy(daily_regime_filter_mode="bogus")
    with pytest.raises(ValueError, match="rsi_window"):
        VwapEmaPullbackStrategy(rsi_window=1)
    with pytest.raises(ValueError, match="volume_mean_window"):
        VwapEmaPullbackStrategy(volume_mean_window=0)
    with pytest.raises(ValueError, match="daily_regime_ma_window"):
        VwapEmaPullbackStrategy(daily_regime_ma_window=1)


# =============================================================================
# P2.5 — fine-grid threshold extension
# Test spec: .omx/plans/test-spec-vwap-ema-pullback-p25-2026-05-04.md §2
# =============================================================================

def test_volume_ge_1_1_blocks_below_threshold():
    df = _entry_df_with_p2_cols(volume_value=109.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_1")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD  # 109 < 110


def test_volume_ge_1_1_allows_above_threshold():
    # `100.0 * 1.1` 은 FP 부정확 (≈ 110.00000000000001) — clearly-above 값 사용.
    df = _entry_df_with_p2_cols(volume_value=111.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_1")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_volume_ge_1_3_blocks_below():
    df = _entry_df_with_p2_cols(volume_value=129.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_3")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD  # 129 < 130


def test_volume_ge_1_3_allows_above_threshold():
    df = _entry_df_with_p2_cols(volume_value=131.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_3")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_volume_ge_1_4_blocks_below():
    df = _entry_df_with_p2_cols(volume_value=139.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_4")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.HOLD  # 139 < 140


def test_volume_ge_1_4_allows_above_threshold():
    df = _entry_df_with_p2_cols(volume_value=141.0, volume_mean_value=100.0)
    s = VwapEmaPullbackStrategy(volume_filter_mode="ge_1_4")
    snap = MarketSnapshot(df=df, current_price=float(df.iloc[-1]["close"]),
                          has_position=False)
    assert s.generate_signal(snap) is Signal.BUY


def test_new_volume_modes_in_valid_set():
    from auto_coin.strategy.vwap_ema_pullback import _VALID_VOLUME_MODES
    # P2.5 신규
    assert "ge_1_1" in _VALID_VOLUME_MODES
    assert "ge_1_3" in _VALID_VOLUME_MODES
    assert "ge_1_4" in _VALID_VOLUME_MODES
    # P2 기존 (회귀)
    assert "ge_1_0" in _VALID_VOLUME_MODES
    assert "ge_1_2" in _VALID_VOLUME_MODES
    assert "ge_1_5" in _VALID_VOLUME_MODES
    assert "off" in _VALID_VOLUME_MODES


def test_invalid_volume_mode_rejected_p25():
    """P2.5 외 random invalid mode 거부."""
    with pytest.raises(ValueError, match="volume_filter_mode"):
        VwapEmaPullbackStrategy(volume_filter_mode="ge_1_25")
    with pytest.raises(ValueError, match="volume_filter_mode"):
        VwapEmaPullbackStrategy(volume_filter_mode="ge_2_0")
    with pytest.raises(ValueError, match="volume_filter_mode"):
        VwapEmaPullbackStrategy(volume_filter_mode="ge_0_5")


def test_volume_threshold_dispatch_consistent():
    """PRD §3.2 의 threshold 매핑이 dispatch 함수에 정확히 반영."""
    from auto_coin.strategy.vwap_ema_pullback import _VOLUME_THRESHOLD_MAP
    assert _VOLUME_THRESHOLD_MAP == {
        "ge_1_0": 1.0, "ge_1_1": 1.1, "ge_1_2": 1.2,
        "ge_1_3": 1.3, "ge_1_4": 1.4, "ge_1_5": 1.5,
    }
    # 각 multiplier 의 above/below 경계 검증. FP 정확도 회피해서 +1/-1 margin.
    for mode, mult in _VOLUME_THRESHOLD_MAP.items():
        s = VwapEmaPullbackStrategy(volume_filter_mode=mode)
        threshold = 100.0 * mult
        # 경계 위 (threshold + 1) — 통과
        df_above = _entry_df_with_p2_cols(volume_value=threshold + 1.0,
                                          volume_mean_value=100.0)
        snap_above = MarketSnapshot(df=df_above, current_price=float(df_above.iloc[-1]["close"]),
                                    has_position=False)
        assert s.generate_signal(snap_above) is Signal.BUY, f"{mode} above-threshold should allow"
        # 경계 아래 (threshold - 1) — 차단
        df_below = _entry_df_with_p2_cols(volume_value=threshold - 1.0,
                                          volume_mean_value=100.0)
        snap_below = MarketSnapshot(df=df_below, current_price=float(df_below.iloc[-1]["close"]),
                                    has_position=False)
        assert s.generate_signal(snap_below) is Signal.HOLD, f"{mode} below-threshold should block"

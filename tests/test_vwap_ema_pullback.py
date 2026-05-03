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

"""Strategy registry / factory tests."""

import pytest

from auto_coin.strategy import (
    STRATEGY_LABELS,
    STRATEGY_PARAMS,
    STRATEGY_REGISTRY,
    create_strategy,
    get_strategy_names,
)
from auto_coin.strategy.ad_turtle import AdTurtleStrategy
from auto_coin.strategy.atr_channel_breakout import AtrChannelBreakoutStrategy
from auto_coin.strategy.base import Strategy
from auto_coin.strategy.ema_adx_atr_trend import EmaAdxAtrTrendStrategy
from auto_coin.strategy.rcdb import RcdbStrategy
from auto_coin.strategy.rcdb_v2 import RcdbV2Strategy
from auto_coin.strategy.regime_reclaim_1h import RegimeReclaim1HStrategy
from auto_coin.strategy.sma200_ema_adx_composite import Sma200EmaAdxCompositeStrategy
from auto_coin.strategy.sma200_regime import Sma200RegimeStrategy
from auto_coin.strategy.volatility_breakout import VolatilityBreakout


def test_registry_contains_volatility_breakout():
    assert "volatility_breakout" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["volatility_breakout"] is VolatilityBreakout


def test_create_strategy_vb_default_params():
    s = create_strategy("volatility_breakout")
    assert isinstance(s, VolatilityBreakout)
    assert s.k == 0.5
    assert s.ma_window == 5


def test_create_strategy_vb_custom_params():
    s = create_strategy("volatility_breakout", {"k": 0.7, "ma_window": 10})
    assert isinstance(s, VolatilityBreakout)
    assert s.k == 0.7
    assert s.ma_window == 10


def test_create_strategy_unknown_raises():
    with pytest.raises(ValueError, match="unknown strategy"):
        create_strategy("nonexistent_strategy")


def test_get_strategy_names():
    names = get_strategy_names()
    assert isinstance(names, list)
    assert "volatility_breakout" in names
    assert "regime_reclaim_1h" not in names
    assert "regime_reclaim_1h" in get_strategy_names(include_experimental=True)


def test_strategy_params_has_all_registry_entries():
    for name in STRATEGY_REGISTRY:
        assert name in STRATEGY_PARAMS, f"missing params definition for {name}"


def test_strategy_labels_has_all_registry_entries():
    for name in STRATEGY_REGISTRY:
        assert name in STRATEGY_LABELS, f"missing label for {name}"


def test_created_strategy_is_strategy_abc_subclass():
    s = create_strategy("volatility_breakout")
    assert isinstance(s, Strategy)


def test_create_strategy_vb_invalid_k_raises():
    with pytest.raises(ValueError):
        create_strategy("volatility_breakout", {"k": 2.0})


def test_registry_contains_regime_reclaim_1h():
    assert "regime_reclaim_1h" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["regime_reclaim_1h"] is RegimeReclaim1HStrategy


def test_create_strategy_regime_reclaim_1h_defaults():
    s = create_strategy("regime_reclaim_1h")
    assert isinstance(s, RegimeReclaim1HStrategy)
    assert s.regime_interval == "day"
    assert s.daily_regime_ma_window == 120
    assert s.dip_lookback_bars == 8
    assert s.max_hold_bars == 36


# --- SMA200 Regime ---


def test_registry_contains_sma200_regime():
    assert "sma200_regime" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["sma200_regime"] is Sma200RegimeStrategy


def test_create_strategy_sma200_default_params():
    s = create_strategy("sma200_regime")
    assert isinstance(s, Sma200RegimeStrategy)
    assert s.ma_window == 200
    assert s.buffer_pct == 0.0
    assert s.allow_sell_signal is False


def test_create_strategy_sma200_custom_params():
    s = create_strategy("sma200_regime", {"ma_window": 50, "buffer_pct": 0.01})
    assert isinstance(s, Sma200RegimeStrategy)
    assert s.ma_window == 50
    assert s.buffer_pct == 0.01


def test_create_strategy_sma200_is_strategy_subclass():
    s = create_strategy("sma200_regime")
    assert isinstance(s, Strategy)


def test_sma200_in_get_strategy_names():
    names = get_strategy_names()
    assert "sma200_regime" in names


# --- ATR Channel Breakout ---


def test_registry_contains_atr_channel_breakout():
    assert "atr_channel_breakout" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["atr_channel_breakout"] is AtrChannelBreakoutStrategy


def test_create_strategy_atr_channel_default_params():
    s = create_strategy("atr_channel_breakout")
    assert isinstance(s, AtrChannelBreakoutStrategy)
    assert s.atr_window == 14
    assert s.channel_multiplier == 1.0
    assert s.allow_sell_signal is False


def test_create_strategy_atr_channel_custom_params():
    s = create_strategy(
        "atr_channel_breakout",
        {"atr_window": 20, "channel_multiplier": 2.0, "allow_sell_signal": True},
    )
    assert isinstance(s, AtrChannelBreakoutStrategy)
    assert s.atr_window == 20
    assert s.channel_multiplier == 2.0
    assert s.allow_sell_signal is True


def test_create_strategy_atr_channel_is_strategy_subclass():
    s = create_strategy("atr_channel_breakout")
    assert isinstance(s, Strategy)


def test_atr_channel_in_get_strategy_names():
    names = get_strategy_names()
    assert "atr_channel_breakout" in names


# --- EMA+ADX ATR Trend ---


def test_registry_contains_ema_adx_atr_trend():
    assert "ema_adx_atr_trend" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["ema_adx_atr_trend"] is EmaAdxAtrTrendStrategy


def test_create_strategy_ema_adx_default_params():
    s = create_strategy("ema_adx_atr_trend")
    assert isinstance(s, EmaAdxAtrTrendStrategy)
    assert s.ema_fast_window == 27
    assert s.ema_slow_window == 125
    assert s.adx_window == 90
    assert s.adx_threshold == 14.0
    assert s.atr_window == 14
    assert s.allow_sell_signal is False


def test_create_strategy_ema_adx_custom_params():
    s = create_strategy(
        "ema_adx_atr_trend",
        {
            "ema_fast_window": 10,
            "ema_slow_window": 50,
            "adx_window": 30,
            "adx_threshold": 20.0,
            "atr_window": 21,
        },
    )
    assert isinstance(s, EmaAdxAtrTrendStrategy)
    assert s.ema_fast_window == 10
    assert s.ema_slow_window == 50
    assert s.adx_window == 30
    assert s.adx_threshold == 20.0
    assert s.atr_window == 21


def test_create_strategy_ema_adx_is_strategy_subclass():
    s = create_strategy("ema_adx_atr_trend")
    assert isinstance(s, Strategy)


def test_ema_adx_in_get_strategy_names():
    names = get_strategy_names()
    assert "ema_adx_atr_trend" in names


# --- AdTurtle ---


def test_registry_contains_ad_turtle():
    assert "ad_turtle" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["ad_turtle"] is AdTurtleStrategy


def test_create_strategy_ad_turtle_default_params():
    s = create_strategy("ad_turtle")
    assert isinstance(s, AdTurtleStrategy)
    assert s.entry_window == 20
    assert s.exit_window == 10
    assert s.allow_sell_signal is False


def test_create_strategy_ad_turtle_custom_params():
    s = create_strategy(
        "ad_turtle",
        {"entry_window": 30, "exit_window": 15, "allow_sell_signal": True},
    )
    assert isinstance(s, AdTurtleStrategy)
    assert s.entry_window == 30
    assert s.exit_window == 15
    assert s.allow_sell_signal is True


def test_create_strategy_ad_turtle_is_strategy_subclass():
    s = create_strategy("ad_turtle")
    assert isinstance(s, Strategy)


def test_ad_turtle_in_get_strategy_names():
    names = get_strategy_names()
    assert "ad_turtle" in names


# --- SMA200 + EMA+ADX Composite ---


def test_registry_contains_composite():
    assert "sma200_ema_adx_composite" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["sma200_ema_adx_composite"] is Sma200EmaAdxCompositeStrategy


def test_create_strategy_composite_default_params():
    s = create_strategy("sma200_ema_adx_composite")
    assert isinstance(s, Sma200EmaAdxCompositeStrategy)
    assert s.sma_window == 200
    assert s.ema_fast_window == 27
    assert s.ema_slow_window == 125
    assert s.adx_window == 90
    assert s.adx_threshold == 14.0


def test_create_strategy_composite_custom_params():
    s = create_strategy(
        "sma200_ema_adx_composite",
        {"sma_window": 100, "ema_fast_window": 10, "ema_slow_window": 50,
         "adx_window": 30, "adx_threshold": 20.0},
    )
    assert isinstance(s, Sma200EmaAdxCompositeStrategy)
    assert s.sma_window == 100
    assert s.ema_fast_window == 10
    assert s.ema_slow_window == 50
    assert s.adx_window == 30
    assert s.adx_threshold == 20.0


def test_create_strategy_composite_is_strategy_subclass():
    s = create_strategy("sma200_ema_adx_composite")
    assert isinstance(s, Strategy)


def test_composite_in_get_strategy_names():
    names = get_strategy_names()
    assert "sma200_ema_adx_composite" in names


# --- RCDB ---


def test_registry_contains_rcdb():
    assert "rcdb" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["rcdb"] is RcdbStrategy


def test_create_strategy_rcdb_default_params():
    s = create_strategy("rcdb")
    assert isinstance(s, RcdbStrategy)
    assert s.regime_ticker == "KRW-BTC"
    assert s.regime_ma_window == 120
    assert s.dip_lookback_days == 5
    assert s.dip_threshold_pct == -0.08
    assert s.rsi_window == 14
    assert s.rsi_threshold == 30.0
    assert s.max_hold_days == 7
    assert s.atr_window == 14
    assert s.atr_trailing_mult == 2.5


def test_create_strategy_rcdb_custom_params():
    s = create_strategy(
        "rcdb",
        {
            "regime_ticker": "KRW-ETH",
            "regime_ma_window": 100,
            "dip_lookback_days": 7,
            "dip_threshold_pct": -0.1,
            "rsi_window": 10,
            "rsi_threshold": 35.0,
            "max_hold_days": 5,
            "atr_window": 10,
            "atr_trailing_mult": 3.0,
        },
    )
    assert isinstance(s, RcdbStrategy)
    assert s.regime_ticker == "KRW-ETH"
    assert s.regime_ma_window == 100
    assert s.dip_lookback_days == 7
    assert s.dip_threshold_pct == -0.1
    assert s.rsi_window == 10
    assert s.rsi_threshold == 35.0
    assert s.max_hold_days == 5
    assert s.atr_window == 10
    assert s.atr_trailing_mult == 3.0


def test_rcdb_hidden_from_default_strategy_names():
    assert "rcdb" not in get_strategy_names()


def test_rcdb_available_when_including_experimental():
    assert "rcdb" in get_strategy_names(include_experimental=True)


def test_registry_contains_rcdb_v2():
    assert "rcdb_v2" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["rcdb_v2"] is RcdbV2Strategy


def test_create_strategy_rcdb_v2_default_params():
    s = create_strategy("rcdb_v2")
    assert isinstance(s, RcdbV2Strategy)
    assert s.regime_ticker == "KRW-BTC"
    assert s.regime_ma_window == 120
    assert s.dip_lookback_days == 5
    assert s.vol_window == 20
    assert s.dip_z_threshold == -1.75
    assert s.rsi_window == 14
    assert s.rsi_threshold == 35.0
    assert s.reversal_ema_window == 5
    assert s.max_hold_days == 5
    assert s.atr_window == 14
    assert s.atr_trailing_mult == 2.0


def test_create_strategy_rcdb_v2_custom_params():
    s = create_strategy(
        "rcdb_v2",
        {
            "regime_ticker": "KRW-ETH",
            "regime_ma_window": 100,
            "dip_lookback_days": 3,
            "vol_window": 15,
            "dip_z_threshold": -2.0,
            "rsi_window": 10,
            "rsi_threshold": 40.0,
            "reversal_ema_window": 3,
            "max_hold_days": 7,
            "atr_window": 10,
            "atr_trailing_mult": 2.3,
        },
    )
    assert isinstance(s, RcdbV2Strategy)
    assert s.regime_ticker == "KRW-ETH"
    assert s.regime_ma_window == 100
    assert s.dip_lookback_days == 3
    assert s.vol_window == 15
    assert s.dip_z_threshold == -2.0
    assert s.rsi_window == 10
    assert s.rsi_threshold == 40.0
    assert s.reversal_ema_window == 3
    assert s.max_hold_days == 7
    assert s.atr_window == 10
    assert s.atr_trailing_mult == 2.3


def test_rcdb_v2_hidden_from_default_strategy_names():
    assert "rcdb_v2" not in get_strategy_names()


def test_rcdb_v2_available_when_including_experimental():
    assert "rcdb_v2" in get_strategy_names(include_experimental=True)


# --- regime_reclaim_30m ---


def test_registry_contains_regime_reclaim_30m():
    from auto_coin.strategy.regime_reclaim_30m import RegimeReclaim30mStrategy
    assert "regime_reclaim_30m" in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY["regime_reclaim_30m"] is RegimeReclaim30mStrategy


def test_create_strategy_regime_reclaim_30m_defaults():
    from auto_coin.strategy.regime_reclaim_30m import RegimeReclaim30mStrategy
    s = create_strategy("regime_reclaim_30m")
    assert isinstance(s, RegimeReclaim30mStrategy)
    assert s.regime_ticker == "KRW-BTC"
    assert s.daily_regime_ma_window == 100
    assert s.hourly_pullback_bars == 8
    assert s.hourly_pullback_threshold_pct == -0.025
    assert s.setup_rsi_window == 14
    assert s.setup_rsi_threshold == 35.0
    assert s.trigger_reclaim_ema_window == 6
    assert s.trigger_rsi_rebound_threshold == 30.0
    assert s.max_hold_bars_30m == 36
    assert s.atr_window == 14
    assert s.atr_trailing_mult == 2.0
    assert s.reversion_sma_window_override is None
    assert s.min_hold_bars_30m == 0
    assert s.reversion_min_profit_pct == 0.0
    assert s.reversion_confirmation_type == "none"


def test_create_strategy_regime_reclaim_30m_custom_params():
    from auto_coin.strategy.regime_reclaim_30m import RegimeReclaim30mStrategy
    s = create_strategy(
        "regime_reclaim_30m",
        {
            "regime_ticker": "KRW-ETH",
            "daily_regime_ma_window": 200,
            "hourly_pullback_bars": 12,
            "hourly_pullback_threshold_pct": -0.03,
            "setup_rsi_window": 10,
            "setup_rsi_threshold": 40.0,
            "trigger_reclaim_ema_window": 8,
            "trigger_rsi_rebound_threshold": 35.0,
            "max_hold_bars_30m": 48,
            "atr_window": 10,
            "atr_trailing_mult": 3.0,
            "reversion_sma_window_override": 24,
            "min_hold_bars_30m": 3,
            "reversion_min_profit_pct": 0.005,
            "reversion_confirmation_type": "rsi",
        },
    )
    assert isinstance(s, RegimeReclaim30mStrategy)
    assert s.regime_ticker == "KRW-ETH"
    assert s.daily_regime_ma_window == 200
    assert s.hourly_pullback_bars == 12
    assert s.hourly_pullback_threshold_pct == -0.03
    assert s.setup_rsi_window == 10
    assert s.setup_rsi_threshold == 40.0
    assert s.trigger_reclaim_ema_window == 8
    assert s.trigger_rsi_rebound_threshold == 35.0
    assert s.max_hold_bars_30m == 48
    assert s.atr_window == 10
    assert s.atr_trailing_mult == 3.0
    assert s.reversion_sma_window_override == 24
    assert s.min_hold_bars_30m == 3
    assert s.reversion_min_profit_pct == 0.005
    assert s.reversion_confirmation_type == "rsi"


def test_regime_reclaim_30m_hidden_from_default_strategy_names():
    assert "regime_reclaim_30m" not in get_strategy_names()


def test_regime_reclaim_30m_available_when_including_experimental():
    assert "regime_reclaim_30m" in get_strategy_names(include_experimental=True)


def test_regime_reclaim_30m_is_strategy_subclass():
    from auto_coin.strategy.regime_reclaim_30m import RegimeReclaim30mStrategy
    s = create_strategy("regime_reclaim_30m")
    assert isinstance(s, Strategy)
    assert isinstance(s, RegimeReclaim30mStrategy)


def test_regime_reclaim_30m_invalid_empty_regime_ticker():
    with pytest.raises(ValueError, match="regime_ticker must be non-empty"):
        create_strategy("regime_reclaim_30m", {"regime_ticker": ""})


def test_regime_reclaim_30m_invalid_ma_window():
    with pytest.raises(ValueError, match="daily_regime_ma_window must be >= 2"):
        create_strategy("regime_reclaim_30m", {"daily_regime_ma_window": 1})


def test_regime_reclaim_30m_invalid_pullback_threshold():
    with pytest.raises(ValueError, match="hourly_pullback_threshold_pct must be < 0"):
        create_strategy("regime_reclaim_30m", {"hourly_pullback_threshold_pct": 0.0})


def test_strategy_params_has_regime_reclaim_30m():
    assert "regime_reclaim_30m" in STRATEGY_PARAMS
    param_names = [p["name"] for p in STRATEGY_PARAMS["regime_reclaim_30m"]]
    assert "daily_regime_ma_window" in param_names
    assert "hourly_pullback_bars" in param_names
    assert "trigger_reclaim_ema_window" in param_names
    assert "max_hold_bars_30m" in param_names
    assert "reversion_sma_window_override" in param_names
    assert "min_hold_bars_30m" in param_names
    assert "reversion_min_profit_pct" in param_names
    assert "reversion_confirmation_type" in param_names


def test_strategy_params_regime_reclaim_1h_has_no_30m_v11_exit_params():
    param_names = [p["name"] for p in STRATEGY_PARAMS["regime_reclaim_1h"]]
    assert "reversion_sma_window_override" not in param_names
    assert "min_hold_bars_30m" not in param_names
    assert "reversion_min_profit_pct" not in param_names
    assert "reversion_confirmation_type" not in param_names


def test_strategy_labels_has_regime_reclaim_30m():
    assert "regime_reclaim_30m" in STRATEGY_LABELS
    assert "30m" in STRATEGY_LABELS["regime_reclaim_30m"]


# --- regime_pullback_continuation_30m ---


def test_registry_contains_regime_pullback_continuation_30m():
    from auto_coin.strategy.regime_pullback_continuation_30m import (
        RegimePullbackContinuation30mStrategy,
    )

    assert "regime_pullback_continuation_30m" in STRATEGY_REGISTRY
    assert (
        STRATEGY_REGISTRY["regime_pullback_continuation_30m"]
        is RegimePullbackContinuation30mStrategy
    )


def test_create_strategy_regime_pullback_continuation_30m_defaults():
    s = create_strategy("regime_pullback_continuation_30m")
    assert s.name == "regime_pullback_continuation_30m"
    assert s.regime_ticker == "KRW-BTC"
    assert s.trend_ema_fast_1h == 20
    assert s.trend_ema_slow_1h == 60
    assert s.trigger_required_votes == 2
    assert s.atr_trailing_mult == 2.5


def test_create_strategy_regime_pullback_continuation_30m_custom_params():
    s = create_strategy(
        "regime_pullback_continuation_30m",
        {
            "trend_ema_fast_1h": 12,
            "trend_ema_slow_1h": 48,
            "trigger_required_votes": 1,
            "atr_trailing_mult": 3.0,
        },
    )
    assert s.trend_ema_fast_1h == 12
    assert s.trend_ema_slow_1h == 48
    assert s.trigger_required_votes == 1
    assert s.atr_trailing_mult == 3.0


def test_regime_pullback_continuation_30m_hidden_by_default():
    assert "regime_pullback_continuation_30m" not in get_strategy_names()


def test_regime_pullback_continuation_30m_available_when_experimental():
    assert "regime_pullback_continuation_30m" in get_strategy_names(include_experimental=True)


def test_strategy_params_has_regime_pullback_continuation_30m():
    assert "regime_pullback_continuation_30m" in STRATEGY_PARAMS
    names = [p["name"] for p in STRATEGY_PARAMS["regime_pullback_continuation_30m"]]
    assert "trend_ema_fast_1h" in names
    assert "pullback_min_pct" in names
    assert "trigger_required_votes" in names
    assert "initial_stop_atr_mult" in names


def test_strategy_labels_has_regime_pullback_continuation_30m():
    assert "regime_pullback_continuation_30m" in STRATEGY_LABELS
    assert "Continuation" in STRATEGY_LABELS["regime_pullback_continuation_30m"]

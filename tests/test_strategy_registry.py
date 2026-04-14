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
    assert s.allow_sell_signal is False


def test_create_strategy_ema_adx_custom_params():
    s = create_strategy(
        "ema_adx_atr_trend",
        {"ema_fast_window": 10, "ema_slow_window": 50, "adx_window": 30, "adx_threshold": 20.0},
    )
    assert isinstance(s, EmaAdxAtrTrendStrategy)
    assert s.ema_fast_window == 10
    assert s.ema_slow_window == 50
    assert s.adx_window == 30
    assert s.adx_threshold == 20.0


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

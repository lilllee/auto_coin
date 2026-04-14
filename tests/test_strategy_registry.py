"""Strategy registry / factory tests."""

import pytest

from auto_coin.strategy import (
    STRATEGY_LABELS,
    STRATEGY_PARAMS,
    STRATEGY_REGISTRY,
    create_strategy,
    get_strategy_names,
)
from auto_coin.strategy.base import Strategy
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

from __future__ import annotations

import pytest

from auto_coin.config import Settings
from auto_coin.risk.manager import Action, RiskContext, RiskManager
from auto_coin.strategy.base import Signal


def _settings(**overrides) -> Settings:
    base = {
        "max_position_ratio": 0.20,
        "daily_loss_limit": -0.03,
        "stop_loss_ratio": -0.02,
        "min_order_krw": 5000,
        "kill_switch": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def rm():
    return RiskManager(_settings())


def test_buy_approved_when_flat(rm):
    ctx = RiskContext(krw_balance=100_000, coin_balance=0, current_price=100.0)
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.BUY
    assert d.krw_amount == pytest.approx(20_000.0)


def test_buy_rejected_when_already_in_position(rm):
    ctx = RiskContext(krw_balance=100_000, coin_balance=0.001, current_price=100.0,
                      avg_entry_price=100.0)
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.HOLD
    assert "already in position" in d.reason


def test_buy_rejected_below_min_order():
    rm = RiskManager(_settings(max_position_ratio=0.20, min_order_krw=5000))
    ctx = RiskContext(krw_balance=10_000, coin_balance=0, current_price=100.0)  # 20% = 2000
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.HOLD
    assert "below min" in d.reason


def test_buy_rejected_when_kill_switch():
    rm = RiskManager(_settings(kill_switch=True))
    ctx = RiskContext(krw_balance=100_000, coin_balance=0, current_price=100.0)
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.HOLD
    assert "kill_switch" in d.reason


def test_kill_switch_does_not_block_sell():
    rm = RiskManager(_settings(kill_switch=True))
    ctx = RiskContext(krw_balance=0, coin_balance=0.001, current_price=100.0,
                      avg_entry_price=100.0)
    d = rm.evaluate(Signal.SELL, ctx)
    assert d.action is Action.SELL


def test_buy_rejected_when_daily_loss_limit_hit(rm):
    ctx = RiskContext(krw_balance=100_000, coin_balance=0, current_price=100.0,
                      daily_pnl_ratio=-0.04)
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.HOLD
    assert "daily_loss_limit" in d.reason


def test_sell_rejected_when_no_position(rm):
    ctx = RiskContext(krw_balance=100_000, coin_balance=0, current_price=100.0)
    d = rm.evaluate(Signal.SELL, ctx)
    assert d.action is Action.HOLD
    assert "no position" in d.reason


def test_sell_approved_when_in_position(rm):
    ctx = RiskContext(krw_balance=0, coin_balance=0.001, current_price=100.0,
                      avg_entry_price=100.0)
    d = rm.evaluate(Signal.SELL, ctx)
    assert d.action is Action.SELL
    assert d.volume == pytest.approx(0.001)


def test_stop_loss_triggers_force_sell_on_hold(rm):
    """HOLD 시그널이라도 손절선 도달 시 강제 SELL."""
    ctx = RiskContext(krw_balance=0, coin_balance=0.001, current_price=97.0,
                      avg_entry_price=100.0)  # -3% (손절 -2%)
    d = rm.evaluate(Signal.HOLD, ctx)
    assert d.action is Action.SELL
    assert "stop_loss" in d.reason
    assert d.volume == pytest.approx(0.001)


def test_stop_loss_overrides_buy_signal(rm):
    """기존 포지션이 손절이면 새 BUY가 와도 우선 SELL."""
    ctx = RiskContext(krw_balance=100_000, coin_balance=0.001, current_price=97.0,
                      avg_entry_price=100.0)
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.SELL
    assert "stop_loss" in d.reason


def test_no_stop_loss_when_within_threshold(rm):
    """-1.5% (손절 -2% 이내)면 HOLD."""
    ctx = RiskContext(krw_balance=0, coin_balance=0.001, current_price=98.5,
                      avg_entry_price=100.0)
    d = rm.evaluate(Signal.HOLD, ctx)
    assert d.action is Action.HOLD


def test_hold_signal_passes_through_when_flat(rm):
    ctx = RiskContext(krw_balance=100_000, coin_balance=0, current_price=100.0)
    d = rm.evaluate(Signal.HOLD, ctx)
    assert d.action is Action.HOLD


# ---- portfolio constraints ----

def test_buy_rejected_when_portfolio_slots_full(rm):
    """동시 보유 상한에 도달하면 미보유 종목의 BUY도 차단."""
    ctx = RiskContext(
        krw_balance=100_000, coin_balance=0, current_price=100.0,
        portfolio_open_positions=3, portfolio_max_positions=3,
    )
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.HOLD
    assert "portfolio slot full" in d.reason


def test_buy_allowed_when_portfolio_has_free_slot(rm):
    ctx = RiskContext(
        krw_balance=100_000, coin_balance=0, current_price=100.0,
        portfolio_open_positions=2, portfolio_max_positions=3,
    )
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.BUY


def test_portfolio_slot_check_uses_max_from_ctx(rm):
    """상한은 RiskContext의 값을 그대로 씀 (settings에 직접 의존하지 않음)."""
    ctx = RiskContext(
        krw_balance=100_000, coin_balance=0, current_price=100.0,
        portfolio_open_positions=1, portfolio_max_positions=1,  # 1 slot 포트폴리오, 이미 보유
    )
    d = rm.evaluate(Signal.BUY, ctx)
    assert d.action is Action.HOLD
    assert "slot full" in d.reason


def test_stop_loss_still_fires_even_when_slots_full(rm):
    """손절은 포트폴리오 상한과 무관하게 최우선 실행된다."""
    ctx = RiskContext(
        krw_balance=0, coin_balance=0.001, current_price=97.0,
        avg_entry_price=100.0,  # -3% (손절 -2%)
        portfolio_open_positions=3, portfolio_max_positions=3,
    )
    d = rm.evaluate(Signal.HOLD, ctx)
    assert d.action is Action.SELL
    assert "stop_loss" in d.reason

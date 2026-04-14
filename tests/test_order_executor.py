from __future__ import annotations

import pytest

from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.executor.order import OrderExecutor
from auto_coin.executor.store import OrderStore
from auto_coin.risk.manager import Action, Decision


@pytest.fixture
def store(tmp_path):
    return OrderStore(tmp_path / "state.json")


@pytest.fixture
def unauth_client():
    return UpbitClient(access_key="", secret_key="", max_retries=1, backoff_base=0.0,
                       min_request_interval=0.0)


@pytest.fixture
def auth_client():
    return UpbitClient(access_key="ak", secret_key="sk", max_retries=1, backoff_base=0.0,
                       min_request_interval=0.0)


def test_live_requires_authenticated_client(unauth_client, store):
    with pytest.raises(ValueError, match="authenticated"):
        OrderExecutor(unauth_client, store, "KRW-BTC", live=True)


def test_paper_executor_does_not_require_auth(unauth_client, store):
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    assert ex.live is False


def test_hold_returns_none(unauth_client, store):
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    rec = ex.execute(Decision(Action.HOLD, reason="signal=HOLD"), current_price=100.0)
    assert rec is None
    assert store.load().orders == []


def test_paper_buy_records_order_and_opens_position(unauth_client, store):
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    rec = ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=100.0,
    )
    assert rec is not None
    assert rec.side == "buy"
    assert rec.status == "paper"
    state = store.load()
    assert len(state.orders) == 1
    assert state.position is not None
    assert state.position.avg_entry_price == 100.0
    assert state.position.volume == pytest.approx(100.0)  # 10000 / 100


def test_paper_sell_closes_position_and_updates_pnl(unauth_client, store):
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)
    ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )
    state = store.load()
    assert state.position is None
    assert len(state.orders) == 2
    assert state.daily_pnl_ratio == pytest.approx(0.10)


def test_live_buy_calls_client_and_records(mocker, auth_client, store):
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "exchange-uuid-1", "side": "bid"},
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True)
    rec = ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=100.0,
    )
    assert rec is not None
    assert rec.uuid == "exchange-uuid-1"
    assert rec.status == "placed"
    auth_client._upbit.buy_market_order.assert_called_once_with("KRW-BTC", 10_000)


def test_live_sell_calls_client(mocker, auth_client, store):
    mocker.patch.object(
        auth_client._upbit, "sell_market_order",
        return_value={"uuid": "exchange-uuid-2", "side": "ask"},
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True)
    rec = ex.execute(
        Decision(Action.SELL, reason="exit", volume=0.001),
        current_price=100.0,
    )
    assert rec is not None
    assert rec.uuid == "exchange-uuid-2"
    auth_client._upbit.sell_market_order.assert_called_once_with("KRW-BTC", 0.001)


def test_buy_without_amount_raises(unauth_client, store):
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    with pytest.raises(ValueError):
        ex.execute(Decision(Action.BUY, reason="bad"), current_price=100.0)


def test_sell_without_volume_raises(unauth_client, store):
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    with pytest.raises(ValueError):
        ex.execute(Decision(Action.SELL, reason="bad"), current_price=100.0)


def test_full_paper_cycle_buy_then_sell(unauth_client, store):
    """BUY → SELL 1사이클 통합 검증."""
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    buy_rec = ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=50_000),
        current_price=50_000_000.0,
    )
    state_after_buy = store.load()
    assert state_after_buy.position is not None
    assert state_after_buy.position.entry_uuid == buy_rec.uuid

    sell_rec = ex.execute(
        Decision(Action.SELL, reason="exit time", volume=state_after_buy.position.volume),
        current_price=51_000_000.0,
    )
    state_final = store.load()
    assert state_final.position is None
    assert len(state_final.orders) == 2
    assert state_final.orders[0].side == "buy"
    assert state_final.orders[1].side == "sell"
    assert state_final.daily_pnl_ratio == pytest.approx(0.02)
    assert sell_rec.uuid != buy_rec.uuid

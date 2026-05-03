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
    # fee-adjusted: (110*(1-0.0005)) / (100*(1+0.0005)) - 1
    assert state.daily_pnl_ratio == pytest.approx(0.09890054972513744)


def test_live_buy_calls_client_and_records(mocker, auth_client, store):
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "exchange-uuid-1", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=0.01)
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
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=0.01)
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
    # fee-adjusted: (51e6*(1-0.0005)) / (50e6*(1+0.0005)) - 1
    expected = (51e6 * (1 - 0.0005)) / (50e6 * (1 + 0.0005)) - 1
    assert state_final.daily_pnl_ratio == pytest.approx(expected)
    assert sell_rec.uuid != buy_rec.uuid


def test_live_buy_stores_estimated_volume(mocker, auth_client, store):
    """라이브 BUY 시 폴링 타임아웃이면 추정 volume(>0)이 기록되어야 한다."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "exchange-uuid-live-buy", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=0.01)
    ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=100.0,
    )
    state = store.load()
    assert state.position is not None
    # 추정 volume: 10_000 / 100.0 = 100.0
    assert state.position.volume == pytest.approx(100.0)
    assert state.position.volume > 0


def test_sell_sets_last_exit_at(unauth_client, store):
    """매도 후 state.last_exit_at에 ISO 타임스탬프가 기록된다."""
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)
    assert store.load().last_exit_at == ""
    ex.execute(Decision(Action.SELL, reason="exit", volume=100.0), current_price=110.0)
    state = store.load()
    assert state.position is None
    assert state.last_exit_at != ""
    # ISO8601 형식 확인
    from datetime import datetime
    datetime.fromisoformat(state.last_exit_at)


def test_sell_close_preserves_existing_state_fields(unauth_client, store):
    """청산 경로가 기존 state 필드를 덮어쓰지 않고 보존해야 한다."""
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)

    def seed_daily_fields(state):
        state.daily_pnl_date = "2026-04-21"
        return state

    store.atomic_update(seed_daily_fields)

    ex.execute(Decision(Action.SELL, reason="exit", volume=100.0), current_price=110.0)

    state = store.load()
    assert state.position is None
    assert len(state.orders) == 2
    assert [order.side for order in state.orders] == ["buy", "sell"]
    assert state.daily_pnl_date == "2026-04-21"
    assert state.last_exit_at != ""


def test_sell_zero_volume_fallback(mocker, auth_client, store):
    """SELL decision.volume=0.0 일 때 store position.volume으로 폴백해 ValueError 없이 처리한다."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "exchange-buy-uuid", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "sell_market_order",
        return_value={"uuid": "exchange-sell-uuid", "side": "ask"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=0.01)
    # 먼저 라이브 BUY → store에 추정 volume 저장
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    state_after_buy = store.load()
    assert state_after_buy.position is not None
    assert state_after_buy.position.volume > 0

    # volume=0.0인 SELL 결정 — ValueError 없이 폴백 실행
    sell_rec = ex.execute(
        Decision(Action.SELL, reason="force_exit", volume=0.0),
        current_price=110.0,
    )
    assert sell_rec is not None
    assert sell_rec.side == "sell"
    # 폴백 volume(100.0)으로 거래소 API 호출 확인
    auth_client._upbit.sell_market_order.assert_called_once_with("KRW-BTC", pytest.approx(100.0))
    # 포지션 청산 확인
    assert store.load().position is None


# ----- fill polling tests -----


def test_live_buy_polls_fill_and_updates_volume(mocker, auth_client, store):
    """체결 폴링 성공 시 실제 executed_volume/avg_price로 포지션이 갱신된다."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "fill-uuid-1", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={
            "uuid": "fill-uuid-1",
            "state": "done",
            "executed_volume": "0.00123",
            "avg_price": "95000000",
        },
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=1.0)
    rec = ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=100_000_000.0,
    )
    assert rec is not None
    assert rec.status == "filled"
    assert "filled" in rec.note
    # 포지션이 실제 체결 데이터로 기록됨
    state = store.load()
    assert state.position is not None
    assert state.position.volume == pytest.approx(0.00123)
    assert state.position.avg_entry_price == pytest.approx(95_000_000.0)


def test_live_buy_fill_avg_price_from_trades_array(mocker, auth_client, store):
    """BUY도 avg_price 직접 필드가 없으면 trades[] 가중평균을 포지션에 반영한다."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "fill-uuid-trades", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={
            "uuid": "fill-uuid-trades",
            "state": "done",
            "executed_volume": "3.0",
            "trades": [
                {"price": "100.0", "volume": "1.0", "funds": "100.0"},
                {"price": "103.0", "volume": "2.0", "funds": "206.0"},
            ],
        },
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=1.0)
    rec = ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=99.0,
    )
    assert rec is not None
    state = store.load()
    assert state.position is not None
    assert state.position.volume == pytest.approx(3.0)
    assert state.position.avg_entry_price == pytest.approx(102.0)


def test_live_buy_poll_timeout_uses_estimate(mocker, auth_client, store):
    """폴링 타임아웃 시 추정 volume/price가 사용된다."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "timeout-uuid-1", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "get_order",
        return_value={"state": "wait"},  # 계속 wait → 타임아웃
    )
    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=0.02)
    rec = ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=100.0,
    )
    assert rec is not None
    assert rec.status == "placed"  # 체결 미확인이므로 placed 유지
    state = store.load()
    assert state.position is not None
    # 추정치 사용: 10_000 / 100.0 = 100.0
    assert state.position.volume == pytest.approx(100.0)
    assert state.position.avg_entry_price == pytest.approx(100.0)


def test_live_sell_polls_fill(mocker, auth_client, store):
    """매도 체결 폴링 성공 시 status가 filled로 기록된다."""
    mocker.patch.object(
        auth_client._upbit, "buy_market_order",
        return_value={"uuid": "buy-for-sell-test", "side": "bid"},
    )
    mocker.patch.object(
        auth_client._upbit, "sell_market_order",
        return_value={"uuid": "sell-fill-uuid", "side": "ask"},
    )
    # get_order: buy는 wait(타임아웃), sell은 done
    call_count = {"n": 0}
    def fake_get_order(uuid):
        call_count["n"] += 1
        if uuid == "sell-fill-uuid":
            return {"uuid": "sell-fill-uuid", "state": "done", "executed_volume": "100.0"}
        return {"state": "wait"}
    mocker.patch.object(auth_client._upbit, "get_order", side_effect=fake_get_order)

    ex = OrderExecutor(auth_client, store, "KRW-BTC", live=True,
                       fill_poll_interval=0.01, fill_poll_timeout=0.05)
    # BUY first (poll times out, that's fine)
    ex.execute(
        Decision(Action.BUY, reason="entry", krw_amount=10_000),
        current_price=100.0,
    )
    assert store.load().position is not None

    # SELL with fill confirmation
    sell_rec = ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )
    assert sell_rec is not None
    assert sell_rec.status == "filled"
    assert "filled" in sell_rec.note
    assert store.load().position is None


def test_paper_mode_skips_fill_polling(unauth_client, store):
    """페이퍼 모드에서는 _poll_fill이 호출되지 않는다."""
    ex = OrderExecutor(unauth_client, store, "KRW-BTC", live=False)
    rec = ex.execute(
        Decision(Action.BUY, reason="signal=BUY", krw_amount=10_000),
        current_price=100.0,
    )
    assert rec is not None
    assert rec.status == "paper"
    # poll_fill returns None for non-live, so no fill polling occurs
    assert store.load().position.volume == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Live SELL fill reflection (P2-3 patch)
# ---------------------------------------------------------------------------

def _make_live_executor_with_capture(client, store, *, mocker):
    """헬퍼: BUY는 done(체결)으로 모의, SELL은 인자로 받는 fill_info 반환."""
    captured = []

    def on_trade_closed(data: dict):
        captured.append(data)

    mocker.patch.object(
        client._upbit, "buy_market_order",
        return_value={"uuid": "buy-uuid", "side": "bid"},
    )
    mocker.patch.object(
        client._upbit, "sell_market_order",
        return_value={"uuid": "sell-uuid", "side": "ask"},
    )
    ex = OrderExecutor(
        client, store, "KRW-BTC", live=True,
        strategy_name="vb",
        on_trade_closed=on_trade_closed,
        fill_poll_interval=0.005,
        fill_poll_timeout=0.05,
    )
    return ex, captured


def test_live_sell_fill_avg_price_reflected_in_record_and_tradelog(
    mocker, auth_client, store,
):
    """live SELL: fill avg_price/executed_volume/paid_fee가 OrderRecord와 TradeLog에 반영된다."""
    ex, captured = _make_live_executor_with_capture(auth_client, store, mocker=mocker)

    # BUY: 체결 확인 → position.avg_entry_price=100, volume=100
    def fake_get_order(uuid):
        if uuid == "buy-uuid":
            return {"state": "done", "executed_volume": "100.0", "avg_price": "100.0"}
        if uuid == "sell-uuid":
            return {
                "state": "done",
                "executed_volume": "100.0",
                "avg_price": "108.5",        # decision_price=110과 다른 실제 fill
                "paid_fee": "5.4",           # 실제 매도 수수료
            }
        return {"state": "wait"}
    mocker.patch.object(auth_client._upbit, "get_order", side_effect=fake_get_order)

    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)
    sell_rec = ex.execute(
        Decision(Action.SELL, reason="exit signal", volume=100.0, reason_code="signal_sell"),
        current_price=110.0,
    )

    # OrderRecord — fill 값 반영
    assert sell_rec.status == "filled"
    assert sell_rec.price == pytest.approx(108.5)
    assert sell_rec.volume == pytest.approx(100.0)
    assert sell_rec.krw_amount == pytest.approx(108.5 * 100.0)
    assert "decision_price=" in sell_rec.note

    # TradeLog callback payload
    assert len(captured) == 1
    data = captured[0]
    assert data["mode"] == "live"
    assert data["exit_price"] == pytest.approx(108.5)
    assert data["decision_exit_price"] == pytest.approx(110.0)
    assert data["quantity"] == pytest.approx(100.0)
    assert data["exit_value_krw"] == pytest.approx(108.5 * 100.0)
    # fee_krw = buy_fee_approx (entry_val * 0.0005) + actual sell paid_fee (5.4)
    expected_fee = (100.0 * 100.0) * 0.0005 + 5.4
    assert data["fee_krw"] == pytest.approx(expected_fee)
    # pnl_krw = exit_val - entry_val - fee_krw
    expected_pnl_krw = 10_850.0 - 10_000.0 - expected_fee
    assert data["pnl_krw"] == pytest.approx(expected_pnl_krw)
    # pnl_ratio = pnl_krw / entry_val
    assert data["pnl_ratio"] == pytest.approx(expected_pnl_krw / 10_000.0)


def test_live_sell_fill_missing_avg_price_falls_back_to_decision_price(
    mocker, auth_client, store,
):
    """live SELL: fill_info에 avg_price 없으면 decision-time current_price 사용."""
    ex, captured = _make_live_executor_with_capture(auth_client, store, mocker=mocker)

    def fake_get_order(uuid):
        if uuid == "buy-uuid":
            return {"state": "done", "executed_volume": "100.0", "avg_price": "100.0"}
        if uuid == "sell-uuid":
            # avg_price 없음, paid_fee 없음, executed_volume만 있음
            return {"state": "done", "executed_volume": "100.0"}
        return {"state": "wait"}
    mocker.patch.object(auth_client._upbit, "get_order", side_effect=fake_get_order)

    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)
    sell_rec = ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )

    # OrderRecord.price는 미확정 → None 유지
    assert sell_rec.status == "filled"
    assert sell_rec.price is None
    assert sell_rec.krw_amount is None
    assert sell_rec.volume == pytest.approx(100.0)

    # TradeLog: decision price fallback + 기존 공식 (paid_fee 없음 → UPBIT_FEE_RATE)
    data = captured[0]
    assert data["exit_price"] == pytest.approx(110.0)            # fallback
    assert data["decision_exit_price"] == pytest.approx(110.0)
    fee = 0.0005
    expected_ratio = (110.0 * (1 - fee)) / (100.0 * (1 + fee)) - 1
    assert data["pnl_ratio"] == pytest.approx(expected_ratio)
    expected_fee_krw = (100.0 * 100.0 + 110.0 * 100.0) * fee     # 기존 공식
    assert data["fee_krw"] == pytest.approx(expected_fee_krw)


def test_live_sell_fill_avg_price_from_trades_array(
    mocker, auth_client, store,
):
    """avg_price 직접 필드가 없어도 trades[]에서 가중평균을 계산해 반영한다."""
    ex, captured = _make_live_executor_with_capture(auth_client, store, mocker=mocker)

    def fake_get_order(uuid):
        if uuid == "buy-uuid":
            return {"state": "done", "executed_volume": "100.0", "avg_price": "100.0"}
        if uuid == "sell-uuid":
            return {
                "state": "done",
                "executed_volume": "100.0",
                "trades": [
                    {"price": "108.0", "volume": "60.0", "funds": "6480.0"},
                    {"price": "109.0", "volume": "40.0", "funds": "4360.0"},
                ],
                "paid_fee": "5.42",
            }
        return {"state": "wait"}
    mocker.patch.object(auth_client._upbit, "get_order", side_effect=fake_get_order)

    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)
    ex.execute(Decision(Action.SELL, reason="exit", volume=100.0), current_price=110.0)

    expected_avg = (6480.0 + 4360.0) / 100.0  # = 108.4
    data = captured[0]
    assert data["exit_price"] == pytest.approx(expected_avg)
    assert data["decision_exit_price"] == pytest.approx(110.0)


def test_live_sell_poll_timeout_uses_decision_price_fallback(
    mocker, auth_client, store,
):
    """SELL 폴링 타임아웃 시 OrderRecord.price=None, TradeLog는 decision price fallback."""
    ex, captured = _make_live_executor_with_capture(auth_client, store, mocker=mocker)

    def fake_get_order(uuid):
        if uuid == "buy-uuid":
            return {"state": "done", "executed_volume": "100.0", "avg_price": "100.0"}
        return {"state": "wait"}
    mocker.patch.object(auth_client._upbit, "get_order", side_effect=fake_get_order)

    ex.execute(Decision(Action.BUY, reason="entry", krw_amount=10_000), current_price=100.0)
    sell_rec = ex.execute(
        Decision(Action.SELL, reason="exit", volume=100.0),
        current_price=110.0,
    )

    assert sell_rec.status == "placed"   # 폴링 타임아웃 → filled로 승급되지 않음
    assert sell_rec.price is None
    data = captured[0]
    assert data["exit_price"] == pytest.approx(110.0)
    assert data["decision_exit_price"] == pytest.approx(110.0)


def test_extract_sell_fill_helper_handles_missing_and_zero():
    """_extract_sell_fill: 누락/0/잘못된 값은 None으로 안전하게."""
    from auto_coin.executor.order import OrderExecutor as Ex
    assert Ex._extract_sell_fill({}) == (None, None, None)
    assert Ex._extract_sell_fill({"avg_price": "0", "executed_volume": "0"}) == (
        None, None, None,
    )
    assert Ex._extract_sell_fill({"avg_price": "abc"}) == (None, None, None)
    assert Ex._extract_sell_fill({
        "avg_price": "100.5", "executed_volume": "2.5", "paid_fee": "0.5",
    }) == (100.5, 2.5, 0.5)

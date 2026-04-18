"""UpbitPrivateWebSocket 테스트."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from auto_coin.exchange.ws_private import (
    AssetEntry,
    OrderState,
    UpbitPrivateWebSocket,
    _safe_float,
)

# ---- 유틸 ----


def test_safe_float():
    """_safe_float가 다양한 입력을 안전하게 변환해야 한다."""
    assert _safe_float(100) == 100.0
    assert _safe_float("99.5") == 99.5
    assert _safe_float(None) == 0.0
    assert _safe_float("") == 0.0
    assert _safe_float("abc") == 0.0


# ---- 기본 초기화 ----


def test_init():
    """기본 초기화 상태 확인."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    assert ws._orders == {}
    assert ws._assets == {}
    assert not ws.is_connected()
    assert ws._reconnect_count == 0


def test_init_with_tickers():
    """tickers가 대문자로 저장되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk", tickers=["krw-btc", "krw-eth"])
    assert ws._tickers == ["KRW-BTC", "KRW-ETH"]


# ---- JWT ----


def test_generate_jwt():
    """JWT 토큰이 생성되어야 한다."""
    ws = UpbitPrivateWebSocket("test-access-key", "test-secret-key")
    token = ws._generate_jwt()
    assert isinstance(token, str)
    assert len(token) > 0

    # 토큰 디코딩 검증
    import jwt as pyjwt

    payload = pyjwt.decode(token, "test-secret-key", algorithms=["HS256"])
    assert payload["access_key"] == "test-access-key"
    assert "nonce" in payload


# ---- 구독 메시지 ----


def test_on_open_sends_subscribe():
    """_on_open이 myOrder + myAsset 구독 메시지를 전송해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    mock_ws = MagicMock()
    ws._on_open(mock_ws)

    mock_ws.send.assert_called_once()
    sent = json.loads(mock_ws.send.call_args.args[0])
    assert len(sent) == 4
    assert "ticket" in sent[0]
    assert sent[1]["type"] == "myOrder"
    assert sent[2]["type"] == "myAsset"
    assert sent[3]["format"] == "DEFAULT"
    assert ws.is_connected()


def test_on_open_with_tickers():
    """tickers가 있으면 myOrder에 codes가 포함되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk", tickers=["KRW-BTC"])
    mock_ws = MagicMock()
    ws._on_open(mock_ws)

    sent = json.loads(mock_ws.send.call_args.args[0])
    assert sent[1]["codes"] == ["KRW-BTC"]


# ---- myOrder 이벤트 ----


def _order_msg(
    uuid="test-uuid",
    code="KRW-BTC",
    state="wait",
    ask_bid="BID",
    order_type="market",
    avg_price="0",
    volume="0.01",
    remaining_volume="0.01",
    executed_volume="0",
    paid_fee="0",
    identifier="",
    trade_uuid="",
    order_timestamp=1000,
) -> bytes:
    return json.dumps({
        "type": "myOrder",
        "uuid": uuid,
        "code": code,
        "state": state,
        "ask_bid": ask_bid,
        "order_type": order_type,
        "avg_price": avg_price,
        "volume": volume,
        "remaining_volume": remaining_volume,
        "executed_volume": executed_volume,
        "paid_fee": paid_fee,
        "identifier": identifier,
        "trade_uuid": trade_uuid,
        "order_timestamp": order_timestamp,
        "stream_type": "REALTIME",
    }).encode()


def test_handle_order_new():
    """새 주문 이벤트가 정상 기록되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg(state="wait"))

    order = ws.get_order("test-uuid")
    assert order is not None
    assert order.state == "wait"
    assert order.code == "KRW-BTC"
    assert order.ask_bid == "BID"
    assert order.volume == 0.01
    assert ws._order_event_count == 1


def test_handle_order_state_transition():
    """주문 상태 전이가 정상 반영되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg(state="wait", order_timestamp=1000))
    ws._on_message(None, _order_msg(
        state="trade",
        executed_volume="0.005",
        remaining_volume="0.005",
        avg_price="50000000",
        paid_fee="25",
        trade_uuid="trade-1",
        order_timestamp=2000,
    ))
    ws._on_message(None, _order_msg(
        state="done",
        executed_volume="0.01",
        remaining_volume="0",
        avg_price="50100000",
        paid_fee="50",
        order_timestamp=3000,
    ))

    order = ws.get_order("test-uuid")
    assert order.state == "done"
    assert order.executed_volume == 0.01
    assert order.avg_price == 50100000.0
    assert order.paid_fee == 50.0
    assert ws._order_event_count == 3


def test_handle_order_terminal_state_locked():
    """terminal state(done/cancel)는 불변이어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg(state="done", order_timestamp=3000))

    # done 상태에서 wait로 역행 시도 → 차단
    ws._on_message(None, _order_msg(state="wait", order_timestamp=4000))

    order = ws.get_order("test-uuid")
    assert order.state == "done"
    assert ws._order_event_count == 1  # 두 번째는 카운트 안 됨


def test_handle_order_cancel_locked():
    """cancel 상태도 불변이어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg(state="cancel"))

    ws._on_message(None, _order_msg(state="trade"))

    assert ws.get_order("test-uuid").state == "cancel"


def test_handle_order_partial_fill():
    """부분 체결 이벤트가 올바르게 갱신되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    # 첫 부분 체결
    ws._on_message(None, _order_msg(
        state="trade",
        executed_volume="0.003",
        remaining_volume="0.007",
        avg_price="49000000",
        trade_uuid="t1",
        order_timestamp=1000,
    ))
    # 두 번째 부분 체결
    ws._on_message(None, _order_msg(
        state="trade",
        executed_volume="0.007",
        remaining_volume="0.003",
        avg_price="49500000",
        trade_uuid="t2",
        order_timestamp=2000,
    ))

    order = ws.get_order("test-uuid")
    assert order.state == "trade"
    assert order.executed_volume == 0.007
    assert order.avg_price == 49500000.0
    assert ws._order_event_count == 2


def test_handle_order_missing_uuid():
    """uuid가 없는 이벤트는 무시해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    msg = json.dumps({"type": "myOrder", "state": "wait"}).encode()
    ws._on_message(None, msg)
    assert ws.get_tracked_orders() == {}


def test_handle_order_callback():
    """on_order_update 콜백이 호출되어야 한다."""
    callback = MagicMock()
    ws = UpbitPrivateWebSocket("ak", "sk", on_order_update=callback)
    ws._on_message(None, _order_msg(state="wait"))

    callback.assert_called_once()
    order = callback.call_args.args[0]
    assert isinstance(order, OrderState)
    assert order.state == "wait"


def test_handle_order_callback_error_does_not_crash():
    """콜백 예외가 전체를 멈추지 않아야 한다."""
    callback = MagicMock(side_effect=Exception("boom"))
    ws = UpbitPrivateWebSocket("ak", "sk", on_order_update=callback)
    ws._on_message(None, _order_msg())  # should not raise
    assert ws._order_event_count == 1


# ---- myAsset 이벤트 ----


def _asset_msg(
    assets=None,
    timestamp=1000,
) -> bytes:
    if assets is None:
        assets = [
            {"currency": "KRW", "balance": "1000000", "locked": "0",
             "avg_buy_price": "0", "unit_currency": "KRW"},
            {"currency": "BTC", "balance": "0.01", "locked": "0.002",
             "avg_buy_price": "149000000", "unit_currency": "KRW"},
        ]
    return json.dumps({
        "type": "myAsset",
        "assets": assets,
        "timestamp": timestamp,
        "stream_type": "REALTIME",
    }).encode()


def test_handle_asset():
    """자산 이벤트가 정상 반영되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _asset_msg())

    assets = ws.get_assets()
    assert "KRW" in assets
    assert "BTC" in assets
    assert assets["KRW"].balance == 1000000.0
    assert assets["BTC"].balance == 0.01
    assert assets["BTC"].locked == 0.002
    assert assets["BTC"].avg_buy_price == 149000000.0
    assert ws._asset_event_count == 1


def test_handle_asset_single_query():
    """get_asset로 단일 자산 조회."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _asset_msg())

    btc = ws.get_asset("btc")
    assert btc is not None
    assert btc.currency == "BTC"
    assert btc.balance == 0.01

    assert ws.get_asset("ETH") is None


def test_handle_asset_timestamp_ordering():
    """이전 timestamp의 자산 이벤트는 무시해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _asset_msg(timestamp=2000))
    assert ws.get_assets()["KRW"].balance == 1000000.0

    # 오래된 이벤트 (다른 잔고) → 무시
    ws._on_message(None, _asset_msg(
        assets=[{"currency": "KRW", "balance": "500000", "locked": "0",
                 "avg_buy_price": "0", "unit_currency": "KRW"}],
        timestamp=1000,
    ))
    assert ws.get_assets()["KRW"].balance == 1000000.0  # 유지


def test_handle_asset_empty_assets():
    """빈 assets 배열은 무시해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _asset_msg(assets=[]))
    assert ws.get_assets() == {}
    assert ws._asset_event_count == 0


def test_handle_asset_callback():
    """on_asset_update 콜백이 호출되어야 한다."""
    callback = MagicMock()
    ws = UpbitPrivateWebSocket("ak", "sk", on_asset_update=callback)
    ws._on_message(None, _asset_msg())

    callback.assert_called_once()
    assets = callback.call_args.args[0]
    assert "KRW" in assets
    assert isinstance(assets["KRW"], AssetEntry)


# ---- REST sync ----


def test_sync_assets_from_rest():
    """REST asset_fetcher로 자산이 초기화되어야 한다."""
    fetcher = MagicMock(return_value={
        "KRW": {"balance": 5000000, "locked": 0, "avg_buy_price": 0, "unit_currency": "KRW"},
        "ETH": {"balance": 1.5, "locked": 0.1, "avg_buy_price": 3000000, "unit_currency": "KRW"},
    })
    ws = UpbitPrivateWebSocket("ak", "sk", asset_fetcher=fetcher)
    ws._sync_assets_from_rest("test")

    assets = ws.get_assets()
    assert assets["KRW"].balance == 5000000.0
    assert assets["ETH"].balance == 1.5
    assert ws._asset_ts == 0  # REST sync → WS 우선


def test_sync_assets_rest_failure():
    """REST 실패 시 예외 없이 계속 동작."""
    fetcher = MagicMock(side_effect=Exception("network"))
    ws = UpbitPrivateWebSocket("ak", "sk", asset_fetcher=fetcher)
    ws._sync_assets_from_rest("test")  # should not raise
    assert ws.get_assets() == {}


def test_sync_assets_no_fetcher():
    """asset_fetcher 미제공 시 noop."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._sync_assets_from_rest("test")
    assert ws.get_assets() == {}


# ---- REST order reconcile ----


def test_reconcile_orders_advances_terminal():
    """REST reconcile이 terminal state로 advance시켜야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk", order_fetcher=MagicMock(return_value={
        "state": "done",
        "executed_volume": "0.01",
        "remaining_volume": "0",
        "paid_fee": "50",
        "avg_price": "50000000",
    }))

    # WS에서 wait 상태로 추적 중
    ws._on_message(None, _order_msg(state="wait"))
    assert ws.get_order("test-uuid").state == "wait"

    # REST reconcile → done으로 advance
    ws._reconcile_orders_from_rest("test")

    order = ws.get_order("test-uuid")
    assert order.state == "done"
    assert order.executed_volume == 0.01
    assert order.paid_fee == 50.0


def test_reconcile_orders_skip_already_terminal():
    """이미 terminal인 주문은 reconcile 대상이 아니어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk", order_fetcher=MagicMock())

    ws._on_message(None, _order_msg(state="done"))

    ws._reconcile_orders_from_rest("test")
    # order_fetcher가 호출되지 않아야 함 (pending 없음)
    ws._order_fetcher.assert_not_called()


def test_reconcile_orders_rest_failure():
    """REST 조회 실패 시 예외 없이 계속."""
    ws = UpbitPrivateWebSocket(
        "ak", "sk",
        order_fetcher=MagicMock(side_effect=Exception("timeout")),
    )
    ws._on_message(None, _order_msg(state="wait"))

    ws._reconcile_orders_from_rest("test")  # should not raise
    assert ws.get_order("test-uuid").state == "wait"  # 변경 없음


def test_reconcile_orders_no_fetcher():
    """order_fetcher 미제공 시 noop."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg(state="wait"))
    ws._reconcile_orders_from_rest("test")  # should not raise


# ---- 연결 상태 ----


def test_is_connected():
    """연결 전 False, open 후 True, close 후 False."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    assert not ws.is_connected()

    ws._on_open(MagicMock())
    assert ws.is_connected()

    ws._on_close(MagicMock(), None, None)
    assert not ws.is_connected()


def test_on_error_does_not_raise():
    """_on_error는 예외를 던지지 않아야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_error(None, Exception("test"))


def test_unparseable_message():
    """파싱 불가 메시지는 무시해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, b"\x80\x81\x82")
    assert ws._order_event_count == 0
    assert ws._asset_event_count == 0


def test_unknown_message_type():
    """알 수 없는 type은 무시해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    msg = json.dumps({"type": "unknown", "data": "test"}).encode()
    ws._on_message(None, msg)
    assert ws._order_event_count == 0


# ---- stats ----


def test_stats():
    """stats가 올바른 값을 반환해야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg())
    ws._on_message(None, _asset_msg())

    stats = ws.stats
    assert stats["connected"] is False
    assert stats["order_event_count"] == 1
    assert stats["asset_event_count"] == 1
    assert stats["tracked_orders"] == 1
    assert stats["tracked_assets"] == 2


# ---- start/stop ----


def test_start_stop():
    """start/stop이 에러 없이 동작해야 한다."""
    with patch("auto_coin.exchange.ws_private.websocket.WebSocketApp") as MockWS:
        mock_app = MagicMock()
        mock_app.run_forever = MagicMock(side_effect=lambda **kw: time.sleep(0.1))
        MockWS.return_value = mock_app

        ws = UpbitPrivateWebSocket("ak", "sk")
        ws.start()
        time.sleep(0.3)
        ws.stop()
        assert not ws._running


def test_connect_uses_private_keepalive_settings():
    """private WS keepalive 설정이 idle timeout 완화용 값으로 고정되어야 한다."""
    with patch("auto_coin.exchange.ws_private.websocket.WebSocketApp") as MockWS:
        mock_app = MagicMock()
        mock_app.run_forever = MagicMock()
        MockWS.return_value = mock_app

        ws = UpbitPrivateWebSocket("ak", "sk")
        ws._connect()

        assert mock_app.run_forever.call_args.kwargs == {
            "ping_interval": 30,
            "ping_timeout": 10,
        }


def test_pong_debug_logging_path():
    """debug_log=True일 때 pong 관측 로그 경로가 깨지지 않아야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk", debug_log=True)
    with patch("auto_coin.exchange.ws_private.logger.debug") as mock_debug:
        ws._on_pong(None, b"UP")

    mock_debug.assert_called_once_with(
        "Private WS pong received (payload_len={}, reconnects={})",
        2,
        0,
    )


def test_ping_debug_logging_path():
    """debug_log=True일 때 ping 관측 로그 경로가 깨지지 않아야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk", debug_log=True)
    with patch("auto_coin.exchange.ws_private.logger.debug") as mock_debug:
        ws._on_ping(None, b"")

    mock_debug.assert_called_once_with(
        "Private WS ping received (payload_len={}, reconnects={})",
        0,
        0,
    )


def test_start_without_credentials():
    """credentials 없으면 start를 건너뛰어야 한다."""
    ws = UpbitPrivateWebSocket("", "")
    ws.start()
    assert not ws._running
    assert ws._thread is None


def test_reconnect_calls_reconcile():
    """reconnect 시 REST reconcile이 호출되어야 한다."""
    asset_fetcher = MagicMock(return_value={"KRW": {
        "balance": 1000000, "locked": 0, "avg_buy_price": 0, "unit_currency": "KRW",
    }})

    with patch("auto_coin.exchange.ws_private.websocket.WebSocketApp") as MockWS:
        mock_app = MagicMock()
        call_count = 0

        def fake_run_forever(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("test disconnect")
            time.sleep(0.5)

        mock_app.run_forever = MagicMock(side_effect=fake_run_forever)
        MockWS.return_value = mock_app

        ws = UpbitPrivateWebSocket(
            "ak", "sk",
            asset_fetcher=asset_fetcher,
            reconnect_delay=0.1,
        )
        ws.start()
        time.sleep(0.5)
        ws.stop()

        # initial + reconnect = 최소 2회
        assert asset_fetcher.call_count >= 2
        assert ws._reconnect_count >= 1


# ---- 다중 주문 추적 ----


def test_multiple_orders():
    """여러 주문이 독립적으로 추적되어야 한다."""
    ws = UpbitPrivateWebSocket("ak", "sk")
    ws._on_message(None, _order_msg(uuid="order-1", state="wait"))
    ws._on_message(None, _order_msg(uuid="order-2", state="trade"))
    ws._on_message(None, _order_msg(uuid="order-1", state="done"))

    assert ws.get_order("order-1").state == "done"
    assert ws.get_order("order-2").state == "trade"
    assert len(ws.get_tracked_orders()) == 2


# ---- bot integration ----


def test_bot_accepts_ws_private():
    """TradingBot이 ws_private 파라미터를 수용하는지 확인."""
    import inspect

    from auto_coin.bot import TradingBot

    sig = inspect.signature(TradingBot.__init__)
    assert "ws_private" in sig.parameters
    param = sig.parameters["ws_private"]
    assert param.default is None

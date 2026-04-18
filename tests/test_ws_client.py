"""UpbitWebSocket 테스트."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock, patch

from auto_coin.exchange.ws_client import UpbitWebSocket

# ---- 기본 초기화 ----


def test_init():
    """tickers가 대문자로 저장되고 초기 상태가 올바른지 확인."""
    ws = UpbitWebSocket(["krw-btc", "krw-eth"])
    assert ws._tickers == ["KRW-BTC", "KRW-ETH"]
    assert ws._prices == {}
    assert not ws.is_connected()


def test_get_prices_empty():
    """start 전에는 빈 dict를 반환해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    assert ws.get_prices() == {}


# ---- 메시지 처리 ----


def test_on_message_updates_price():
    """ticker 메시지 수신 시 가격이 업데이트되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    msg = json.dumps({
        "type": "ticker",
        "code": "KRW-BTC",
        "trade_price": 110000000.0,
        "timestamp": 1000,
        "stream_type": "REALTIME",
    }).encode("utf-8")
    ws._on_message(None, msg)
    assert ws.get_price("KRW-BTC") == 110000000.0


def test_on_message_bytes():
    """bytes 입력도 정상 파싱되어야 한다."""
    ws = UpbitWebSocket(["KRW-ETH"])
    msg = json.dumps({
        "type": "ticker",
        "code": "KRW-ETH",
        "trade_price": 5200000.0,
        "timestamp": 1000,
    }).encode("utf-8")
    ws._on_message(None, msg)
    assert ws.get_price("KRW-ETH") == 5200000.0


def test_on_message_str():
    """str 입력도 정상 파싱되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    msg = json.dumps({
        "type": "ticker",
        "code": "KRW-BTC",
        "trade_price": 99000000.0,
        "timestamp": 1000,
    })
    ws._on_message(None, msg)
    assert ws.get_price("KRW-BTC") == 99000000.0


def test_on_message_ignores_non_ticker():
    """type이 ticker가 아닌 메시지는 무시해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    msg = json.dumps({
        "type": "orderbook",
        "code": "KRW-BTC",
        "trade_price": 110000000.0,
        "timestamp": 1000,
    }).encode("utf-8")
    ws._on_message(None, msg)
    assert ws.get_prices() == {}


def test_on_message_missing_fields():
    """code 또는 trade_price가 누락된 메시지는 무시해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])

    # code 누락
    msg1 = json.dumps({"type": "ticker", "trade_price": 100.0, "timestamp": 1000}).encode("utf-8")
    ws._on_message(None, msg1)
    assert ws.get_prices() == {}

    # trade_price 누락
    msg2 = json.dumps({"type": "ticker", "code": "KRW-BTC", "timestamp": 1000}).encode("utf-8")
    ws._on_message(None, msg2)
    assert ws.get_prices() == {}


def test_on_message_unparseable():
    """파싱 불가 메시지는 예외 없이 무시해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    ws._on_message(None, b"\x80\x81\x82")  # invalid bytes
    assert ws.get_prices() == {}
    assert ws._message_count == 0


# ---- timestamp ordering ----


def test_timestamp_ordering_newer_accepted():
    """더 최신 timestamp 메시지는 반영되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    # 먼저 ts=1000
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
    }).encode())
    assert ws.get_price("KRW-BTC") == 100.0

    # ts=2000 → 반영
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 200.0, "timestamp": 2000,
    }).encode())
    assert ws.get_price("KRW-BTC") == 200.0


def test_timestamp_ordering_late_message_dropped():
    """이전 timestamp 메시지는 무시되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    # ts=2000 먼저
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 200.0, "timestamp": 2000,
    }).encode())
    assert ws.get_price("KRW-BTC") == 200.0

    # ts=1000 → drop
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
    }).encode())
    assert ws.get_price("KRW-BTC") == 200.0  # 유지
    assert ws._dropped_count == 1


def test_timestamp_same_accepted():
    """동일 timestamp 메시지는 반영되어야 한다 (>=)."""
    ws = UpbitWebSocket(["KRW-BTC"])
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
    }).encode())
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 150.0, "timestamp": 1000,
    }).encode())
    assert ws.get_price("KRW-BTC") == 150.0
    assert ws._dropped_count == 0


# ---- stream_type (SNAPSHOT / REALTIME) ----


def test_snapshot_then_realtime():
    """SNAPSHOT 이후 REALTIME이 정상 반영되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    # SNAPSHOT (연결 직후)
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
        "stream_type": "SNAPSHOT",
    }).encode())
    assert ws.get_price("KRW-BTC") == 100.0

    # REALTIME (이후 업데이트)
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 105.0, "timestamp": 2000,
        "stream_type": "REALTIME",
    }).encode())
    assert ws.get_price("KRW-BTC") == 105.0


# ---- REST 초기 동기화 ----


def test_rest_initial_sync():
    """rest_fetcher가 주어지면 start() 시 REST로 가격을 미리 채워야 한다."""
    fetcher = MagicMock(return_value={"KRW-BTC": 50000000.0, "KRW-ETH": 3000000.0})

    with patch("auto_coin.exchange.ws_client.websocket.WebSocketApp") as MockWS:
        mock_app = MagicMock()
        mock_app.run_forever = MagicMock(side_effect=lambda **kw: time.sleep(0.1))
        MockWS.return_value = mock_app

        ws = UpbitWebSocket(["KRW-BTC", "KRW-ETH"], rest_fetcher=fetcher)
        ws.start()
        time.sleep(0.2)

        # REST에서 가져온 가격이 있어야 함
        assert ws.get_price("KRW-BTC") == 50000000.0
        assert ws.get_price("KRW-ETH") == 3000000.0
        # initial sync + reconnect sync → 1회 이상 호출
        assert fetcher.call_count >= 1
        fetcher.assert_any_call(["KRW-BTC", "KRW-ETH"])

        ws.stop()


def test_rest_sync_sets_server_ts_zero():
    """REST 동기화 가격은 server_ts=0으로 설정되어 WS 메시지가 항상 우선한다."""
    fetcher = MagicMock(return_value={"KRW-BTC": 50000000.0})
    ws = UpbitWebSocket(["KRW-BTC"], rest_fetcher=fetcher)
    ws._sync_from_rest("test")

    assert ws.get_price("KRW-BTC") == 50000000.0
    assert ws._server_ts["KRW-BTC"] == 0

    # WS 메시지(ts=1)가 REST 가격을 덮어씀
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 55000000.0, "timestamp": 1,
    }).encode())
    assert ws.get_price("KRW-BTC") == 55000000.0


def test_rest_sync_failure_does_not_crash():
    """rest_fetcher 실패 시 예외 없이 계속 동작해야 한다."""
    fetcher = MagicMock(side_effect=Exception("network error"))
    ws = UpbitWebSocket(["KRW-BTC"], rest_fetcher=fetcher)
    ws._sync_from_rest("test")  # should not raise
    assert ws.get_prices() == {}


def test_no_rest_fetcher():
    """rest_fetcher 미제공 시 REST 동기화를 건너뛰어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    ws._sync_from_rest("test")  # should not raise, noop
    assert ws.get_prices() == {}


# ---- reconnect REST 동기화 ----


def test_reconnect_calls_rest_sync():
    """reconnect 시 REST 재동기화가 호출되어야 한다."""
    fetcher = MagicMock(return_value={"KRW-BTC": 60000000.0})

    with patch("auto_coin.exchange.ws_client.websocket.WebSocketApp") as MockWS:
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

        ws = UpbitWebSocket(
            ["KRW-BTC"], rest_fetcher=fetcher, reconnect_delay=0.1,
        )
        ws.start()
        time.sleep(0.5)
        ws.stop()

        # initial + reconnect = 최소 2회 호출
        assert fetcher.call_count >= 2
        assert ws._reconnect_count >= 1


# ---- 스레드 안전성 ----


def test_get_prices_thread_safe():
    """동시 읽기/쓰기에서 데이터 무결성이 유지되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    errors: list[Exception] = []

    def writer():
        try:
            for i in range(100):
                msg = json.dumps({
                    "type": "ticker",
                    "code": "KRW-BTC",
                    "trade_price": float(100000 + i),
                    "timestamp": 1000 + i,
                }).encode("utf-8")
                ws._on_message(None, msg)
        except Exception as exc:
            errors.append(exc)

    def reader():
        try:
            for _ in range(100):
                prices = ws.get_prices()
                if prices:
                    assert isinstance(prices.get("KRW-BTC"), float)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == []


# ---- stale 감지 ----


def test_stale_tickers():
    """수신 이력이 없거나 오래된 종목을 stale로 감지해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC", "KRW-ETH"])
    msg = json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
    }).encode("utf-8")
    ws._on_message(None, msg)

    stale = ws.stale_tickers(max_age_seconds=60.0)
    assert "KRW-BTC" not in stale
    assert "KRW-ETH" in stale


def test_stale_tickers_with_old_update():
    """오래된 갱신은 stale로 감지해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    msg = json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
    }).encode("utf-8")
    ws._on_message(None, msg)

    with ws._lock:
        ws._local_ts["KRW-BTC"] = time.time() - 120.0

    stale = ws.stale_tickers(max_age_seconds=60.0)
    assert "KRW-BTC" in stale


# ---- 구독 메시지 ----


def test_on_open_sends_subscribe():
    """_on_open 호출 시 올바른 구독 메시지를 전송해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC", "KRW-ETH"])
    mock_ws = MagicMock()
    ws._on_open(mock_ws)

    mock_ws.send.assert_called_once()
    sent = json.loads(mock_ws.send.call_args.args[0])
    assert len(sent) == 3
    assert "ticket" in sent[0]
    assert sent[1]["type"] == "ticker"
    assert sent[1]["codes"] == ["KRW-BTC", "KRW-ETH"]
    # is_only_realtime 제거됨 — snapshot + realtime 모두 수신
    assert "is_only_realtime" not in sent[1]
    assert sent[2]["format"] == "DEFAULT"
    assert ws.is_connected()


# ---- 연결 상태 ----


def test_start_stop():
    """start/stop이 에러 없이 동작해야 한다."""
    with patch("auto_coin.exchange.ws_client.websocket.WebSocketApp") as MockWS:
        mock_app = MagicMock()
        mock_app.run_forever = MagicMock(side_effect=lambda **kw: time.sleep(0.1))
        MockWS.return_value = mock_app

        ws = UpbitWebSocket(["KRW-BTC"])
        ws.start()
        time.sleep(0.3)
        ws.stop()
        assert not ws._running


def test_is_connected():
    """연결 전 False, _on_open 후 True, _on_close 후 False."""
    ws = UpbitWebSocket(["KRW-BTC"])
    assert not ws.is_connected()

    ws._on_open(MagicMock())
    assert ws.is_connected()

    ws._on_close(MagicMock(), None, None)
    assert not ws.is_connected()


# ---- 여러 종목 ----


def test_multiple_tickers():
    """여러 종목의 가격이 각각 업데이트되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC", "KRW-ETH", "KRW-XRP"])
    for i, (code, price) in enumerate([
        ("KRW-BTC", 110000000.0),
        ("KRW-ETH", 5200000.0),
        ("KRW-XRP", 3400.0),
    ]):
        msg = json.dumps({
            "type": "ticker", "code": code,
            "trade_price": price, "timestamp": 1000 + i,
        }).encode("utf-8")
        ws._on_message(None, msg)

    prices = ws.get_prices()
    assert prices == {"KRW-BTC": 110000000.0, "KRW-ETH": 5200000.0, "KRW-XRP": 3400.0}


# ---- 에러 처리 ----


def test_on_error_does_not_raise():
    """_on_error는 예외를 던지지 않아야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    ws._on_error(None, Exception("test error"))


# ---- stats ----


def test_stats_property():
    """stats 속성이 올바른 값을 반환해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC", "KRW-ETH"])
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 1000,
    }).encode())

    stats = ws.stats
    assert stats["connected"] is False
    assert stats["reconnect_count"] == 0
    assert stats["message_count"] == 1
    assert stats["dropped_count"] == 0
    assert stats["tracked_tickers"] == 2
    assert stats["priced_tickers"] == 1


# ---- debug logging ----


def test_debug_log_does_not_crash():
    """debug_log=True로 메시지 처리 시 예외 없이 동작해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"], debug_log=True)
    for i in range(55):
        ws._on_message(None, json.dumps({
            "type": "ticker", "code": "KRW-BTC",
            "trade_price": float(100000 + i),
            "timestamp": 1000 + i,
            "stream_type": "SNAPSHOT" if i == 0 else "REALTIME",
        }).encode())
    assert ws._message_count == 55


# ---- bot integration ----


def test_bot_get_prices_ws_fallback():
    """TradingBot이 ws_client 파라미터를 수용하는지 확인."""
    import inspect

    from auto_coin.bot import TradingBot
    sig = inspect.signature(TradingBot.__init__)
    assert "ws_client" in sig.parameters
    param = sig.parameters["ws_client"]
    assert param.default is None

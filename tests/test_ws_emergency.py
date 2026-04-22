"""WS 이벤트 드리븐 긴급 손절 테스트."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import MagicMock

from auto_coin.exchange.upbit_client import AssetBalance
from auto_coin.exchange.ws_client import UpbitWebSocket
from auto_coin.executor.store import OrderRecord, Position, State

# ---- helpers ----


def _make_bot(
    *,
    tickers=None,
    stop_loss_ratio=-0.02,
    position=None,
    ws_client=None,
    executor_live=False,
):
    """최소 TradingBot mock 생성."""
    if tickers is None:
        tickers = ["KRW-BTC"]

    from auto_coin.bot import TradingBot
    from auto_coin.config import Settings
    from auto_coin.exchange.upbit_client import UpbitClient
    from auto_coin.executor.order import OrderExecutor
    from auto_coin.executor.store import OrderStore
    from auto_coin.notifier.telegram import TelegramNotifier
    from auto_coin.risk.manager import RiskManager
    from auto_coin.strategy.base import Strategy

    settings = MagicMock(spec=Settings)
    settings.stop_loss_ratio = stop_loss_ratio
    settings.max_concurrent_positions = 3
    settings.ma_filter_window = 5
    settings.strategy_k = 0.5
    settings.strategy_params_json = ""
    settings.cooldown_minutes = 0
    settings.max_daily_stop_losses = 2
    settings.paper_initial_krw = 1_000_000.0
    settings.mode = MagicMock()
    settings.mode.value = "paper"

    client = MagicMock(spec=UpbitClient)
    client.authenticated = False

    stores = {}
    executors = {}
    for t in tickers:
        store = MagicMock(spec=OrderStore)
        state = State()
        if position and t in position:
            state.position = position[t]
        store.load.return_value = state
        stores[t] = store

        executor = MagicMock(spec=OrderExecutor)
        executor.live = executor_live
        executor.execute.return_value = OrderRecord(
            uuid="test-uuid", side="sell", market=t,
            krw_amount=0.0, volume=0.0, price=0.0,
            placed_at="2026-01-01T00:00:00", status="paper",
        )
        executors[t] = executor

    strategy = MagicMock(spec=Strategy)
    strategy.name = "volatility_breakout"

    risk_manager = MagicMock(spec=RiskManager)
    notifier = MagicMock(spec=TelegramNotifier)

    bot = TradingBot(
        settings=settings,
        client=client,
        strategy=strategy,
        risk_manager=risk_manager,
        stores=stores,
        executors=executors,
        notifier=notifier,
        ws_client=ws_client,
    )
    return bot


def _position(avg_entry: float, volume: float = 0.01) -> Position:
    return Position(
        ticker="KRW-TEST", volume=volume, avg_entry_price=avg_entry,
        entry_uuid="test-entry", entry_at="2026-01-01T00:00:00",
    )


# ---- WS 콜백 등록 ----


def test_ws_callback_registered():
    """WS 클라이언트가 있으면 가격 콜백이 등록되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    bot = _make_bot(ws_client=ws)
    assert ws._on_price_update is not None
    assert ws._on_price_update == bot._on_ws_price


def test_ws_callback_not_registered_without_ws():
    """WS 클라이언트가 없으면 콜백 등록하지 않아야 한다."""
    _make_bot(ws_client=None)  # should not crash


# ---- 긴급 손절 판단 ----


def test_emergency_exit_triggered():
    """손절 조건 충족 시 긴급 SELL이 트리거되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    # -3% 하락 → 손절 트리거
    price = 97_000_000.0
    bot._check_emergency_exit("KRW-BTC", price)

    # 스레드 완료 대기
    time.sleep(0.3)

    executor = bot._executors["KRW-BTC"]
    executor.execute.assert_called_once()
    decision = executor.execute.call_args.args[0]
    assert decision.action.value == "sell"
    assert decision.reason_code == "ws_stop_loss"
    # 완료 후 해제
    assert bot._exit_in_flight.get("KRW-BTC") is False


def test_emergency_exit_not_triggered_above_threshold():
    """손절 기준 이상이면 트리거되지 않아야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    # -1% 하락 → 미해당
    bot._check_emergency_exit("KRW-BTC", 99_000_000.0)

    assert bot._exit_in_flight.get("KRW-BTC") is not True
    bot._executors["KRW-BTC"].execute.assert_not_called()


def test_emergency_exit_no_position():
    """포지션 없으면 트리거되지 않아야 한다."""
    bot = _make_bot()  # No position

    bot._check_emergency_exit("KRW-BTC", 50_000_000.0)
    bot._executors["KRW-BTC"].execute.assert_not_called()


def test_emergency_exit_unknown_ticker():
    """매매 대상이 아닌 종목은 무시해야 한다."""
    bot = _make_bot(tickers=["KRW-BTC"])
    bot._check_emergency_exit("KRW-ETH", 1000.0)  # should not raise


# ---- 중복 방지 ----


def test_duplicate_prevention():
    """exit_in_flight 중에는 추가 트리거가 차단되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    # executor를 느리게 만들어 exit_in_flight 상태 유지
    started = threading.Event()
    proceed = threading.Event()
    original_execute = bot._executors["KRW-BTC"].execute

    def slow_execute(*args, **kwargs):
        started.set()
        proceed.wait(timeout=2.0)
        return original_execute(*args, **kwargs)

    bot._executors["KRW-BTC"].execute = MagicMock(side_effect=slow_execute)

    # 첫 번째 트리거
    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    started.wait(timeout=1.0)  # 스레드가 시작될 때까지 대기
    assert bot._exit_in_flight.get("KRW-BTC") is True

    # 두 번째 트리거 시도 — 차단
    bot._check_emergency_exit("KRW-BTC", 96_000_000.0)

    proceed.set()  # 완료 허용
    time.sleep(0.3)
    # executor는 1번만 호출되어야 함
    assert bot._executors["KRW-BTC"].execute.call_count == 1


def test_exit_in_flight_cleared_after_completion():
    """SELL 완료 후 exit_in_flight가 해제되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    # 완료 후 해제
    assert bot._exit_in_flight.get("KRW-BTC") is False


def test_exit_in_flight_cleared_on_failure():
    """SELL 실패 후에도 exit_in_flight가 해제되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    from auto_coin.exchange.upbit_client import UpbitError
    bot._executors["KRW-BTC"].execute.side_effect = UpbitError("test fail")

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    assert bot._exit_in_flight.get("KRW-BTC") is False


def test_emergency_exit_skips_when_exchange_balance_is_locked():
    """거래소 가용 수량이 0이고 locked만 있으면 추가 긴급 SELL을 보내지 않아야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02, executor_live=True)
    bot._client.authenticated = True
    bot._client.get_holdings.return_value = [
        AssetBalance(
            currency="BTC",
            unit_currency="KRW",
            balance=0.0,
            locked=0.01,
            avg_buy_price=100_000_000.0,
        )
    ]

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    bot._executors["KRW-BTC"].execute.assert_not_called()
    assert bot._exit_in_flight.get("KRW-BTC") is False


# ---- 포지션 캐시 ----


def test_position_cache_initialized():
    """초기 포지션이 캐시에 반영되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0, volume=0.01)}
    bot = _make_bot(position=pos)

    cached = bot._position_cache.get("KRW-BTC")
    assert cached == (100_000_000.0, 0.01)


def test_position_cache_empty_when_no_position():
    """포지션 없으면 캐시도 비어 있어야 한다."""
    bot = _make_bot()
    assert bot._position_cache.get("KRW-BTC") is None


def test_position_cache_cleared_after_emergency_sell():
    """긴급 SELL 성공 후 포지션 캐시가 제거되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    assert bot._position_cache.get("KRW-BTC") is None


# ---- tick 루프 충돌 방지 ----


def test_tick_skips_when_exit_in_flight():
    """exit_in_flight인 종목은 tick에서 executor.execute를 호출하지 않아야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    # exit_in_flight 수동 설정
    with bot._exit_lock:
        bot._exit_in_flight["KRW-BTC"] = True

    bot._executors["KRW-BTC"].execute.reset_mock()

    # _tick_impl 호출 시 가격 필요 → mock
    bot._get_prices = MagicMock(return_value={"KRW-BTC": 97_000_000.0})
    bot._tick_impl()

    # exit_in_flight인 ticker의 executor.execute는 호출되지 않아야 함
    bot._executors["KRW-BTC"].execute.assert_not_called()


# ---- 다중 종목 ----


def test_multiple_tickers_independent():
    """여러 종목의 긴급 exit이 독립적으로 동작해야 한다."""
    pos = {
        "KRW-BTC": _position(avg_entry=100_000_000.0),
        "KRW-ETH": _position(avg_entry=5_000_000.0),
    }
    bot = _make_bot(tickers=["KRW-BTC", "KRW-ETH"], position=pos, stop_loss_ratio=-0.02)

    # BTC만 손절 트리거
    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    # ETH는 미해당
    bot._check_emergency_exit("KRW-ETH", 4_999_000.0)

    time.sleep(0.3)

    bot._executors["KRW-BTC"].execute.assert_called_once()
    bot._executors["KRW-ETH"].execute.assert_not_called()


# ---- 손절 카운트 ----


def test_stop_loss_count_incremented():
    """긴급 손절 시 stop_loss_count가 증가해야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    assert bot._stop_loss_counts.get("KRW-BTC", 0) == 1


# ---- 알림 ----


def test_notification_sent_on_emergency_sell():
    """긴급 SELL 시 텔레그램 알림이 전송되어야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    bot._notifier.send.assert_called()
    msg = bot._notifier.send.call_args.args[0]
    assert "EMERGENCY" in msg


# ---- stale 캐시에서 포지션 없는 경우 ----


def test_stale_cache_position_gone():
    """캐시에는 포지션이 있지만 store에는 없으면 SELL을 건너뛰어야 한다."""
    bot = _make_bot()  # No position in store
    # 캐시에 수동 설정 (stale)
    bot._position_cache["KRW-BTC"] = (100_000_000.0, 0.01)

    bot._check_emergency_exit("KRW-BTC", 97_000_000.0)
    time.sleep(0.3)

    # store.load()에서 position=None → SELL 안 함
    bot._executors["KRW-BTC"].execute.assert_not_called()
    # 캐시가 정리되어야 함
    assert bot._position_cache.get("KRW-BTC") is None


# ---- WS 콜백 통합 ----


def test_ws_price_callback_triggers_check():
    """WS 가격 콜백이 _check_emergency_exit를 호출해야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02, ws_client=ws)

    # WS 메시지 시뮬레이션 — 급락
    msg = json.dumps({
        "type": "ticker",
        "code": "KRW-BTC",
        "trade_price": 97_000_000.0,
        "timestamp": 1000,
        "stream_type": "REALTIME",
    }).encode()
    ws._on_message(None, msg)

    time.sleep(0.3)

    bot._executors["KRW-BTC"].execute.assert_called_once()


def test_ws_price_callback_exception_does_not_crash():
    """콜백 예외가 WS를 멈추지 않아야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    # 예외를 던지는 콜백
    ws.set_price_callback(MagicMock(side_effect=Exception("boom")))

    msg = json.dumps({
        "type": "ticker",
        "code": "KRW-BTC",
        "trade_price": 100.0,
        "timestamp": 1000,
    }).encode()
    ws._on_message(None, msg)  # should not raise
    assert ws.get_price("KRW-BTC") == 100.0


# ---- set_price_callback ----


def test_set_price_callback():
    """set_price_callback으로 콜백을 설정/해제할 수 있어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    assert ws._on_price_update is None

    cb = MagicMock()
    ws.set_price_callback(cb)
    assert ws._on_price_update is cb

    ws.set_price_callback(None)
    assert ws._on_price_update is None


def test_price_callback_invoked_on_message():
    """가격 업데이트 시 콜백이 호출되어야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    cb = MagicMock()
    ws.set_price_callback(cb)

    msg = json.dumps({
        "type": "ticker",
        "code": "KRW-BTC",
        "trade_price": 50000000.0,
        "timestamp": 2000,
    }).encode()
    ws._on_message(None, msg)

    cb.assert_called_once_with("KRW-BTC", 50000000.0, 2000)


def test_price_callback_not_called_for_dropped_message():
    """timestamp guard로 drop된 메시지는 콜백을 호출하지 않아야 한다."""
    ws = UpbitWebSocket(["KRW-BTC"])
    cb = MagicMock()
    ws.set_price_callback(cb)

    # 먼저 ts=2000
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 100.0, "timestamp": 2000,
    }).encode())
    # 오래된 ts=1000 → drop
    ws._on_message(None, json.dumps({
        "type": "ticker", "code": "KRW-BTC",
        "trade_price": 50.0, "timestamp": 1000,
    }).encode())

    # 콜백은 1번만 호출 (drop된 메시지는 콜백 안 함)
    assert cb.call_count == 1


# ---- force_exit ↔ WS emergency 중복 방지 ----


def test_force_exit_skips_when_exit_in_flight():
    """exit_in_flight인 종목은 force_exit_if_holding에서 SELL하지 않아야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    # exit_in_flight 수동 설정
    with bot._exit_lock:
        bot._exit_in_flight["KRW-BTC"] = True

    bot._get_prices = MagicMock(return_value={"KRW-BTC": 97_000_000.0})
    results = bot.force_exit_if_holding()

    # skip됨 — executor.execute 호출되지 않아야 함
    bot._executors["KRW-BTC"].execute.assert_not_called()
    assert results == []


def test_force_exit_proceeds_when_no_exit_in_flight():
    """exit_in_flight가 아닌 종목은 force_exit에서 정상 SELL돼야 한다."""
    pos = {"KRW-BTC": _position(avg_entry=100_000_000.0)}
    bot = _make_bot(position=pos, stop_loss_ratio=-0.02)

    bot._get_prices = MagicMock(return_value={"KRW-BTC": 97_000_000.0})
    results = bot.force_exit_if_holding()

    bot._executors["KRW-BTC"].execute.assert_called_once()
    assert len(results) == 1


def test_force_exit_mixed_tickers_in_flight():
    """exit_in_flight인 종목만 skip, 나머지는 정상 처리."""
    pos = {
        "KRW-BTC": _position(avg_entry=100_000_000.0),
        "KRW-ETH": _position(avg_entry=5_000_000.0),
    }
    bot = _make_bot(tickers=["KRW-BTC", "KRW-ETH"], position=pos)

    # BTC만 in-flight
    with bot._exit_lock:
        bot._exit_in_flight["KRW-BTC"] = True

    bot._get_prices = MagicMock(return_value={
        "KRW-BTC": 97_000_000.0,
        "KRW-ETH": 4_800_000.0,
    })
    results = bot.force_exit_if_holding()

    # BTC는 skip, ETH는 정상 처리
    bot._executors["KRW-BTC"].execute.assert_not_called()
    bot._executors["KRW-ETH"].execute.assert_called_once()
    assert len(results) == 1

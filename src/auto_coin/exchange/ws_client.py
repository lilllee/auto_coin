"""Upbit WebSocket 실시간 가격 피드 (운영 품질).

초기화 흐름:
    1. REST 초기 조회로 가격 즉시 확보 (rest_fetcher 제공 시)
    2. WS 연결 → snapshot + realtime 구독
    3. 이후 증분 반영 (server timestamp 기반 ordering)

재연결 흐름:
    1. 연결 끊김 감지 → _connected 해제
    2. REST 재동기화 (stale 즉시 해소)
    3. WS 재연결 → snapshot 수신 → realtime 전환
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from uuid import uuid4

import websocket
from loguru import logger


class UpbitWebSocket:
    """Upbit WebSocket 실시간 가격 피드.

    사용:
        ws = UpbitWebSocket(
            ["KRW-BTC", "KRW-ETH"],
            rest_fetcher=client.get_current_prices,
        )
        ws.start()
        prices = ws.get_prices()  # {"KRW-BTC": 110000000.0, ...}
        ws.stop()
    """

    def __init__(
        self,
        tickers: list[str],
        *,
        reconnect_delay: float = 5.0,
        rest_fetcher: Callable[[list[str]], dict[str, float]] | None = None,
        debug_log: bool = False,
    ) -> None:
        self._tickers = [t.upper() for t in tickers]
        self._reconnect_delay = reconnect_delay
        self._rest_fetcher = rest_fetcher
        self._debug_log = debug_log
        self._on_price_update: Callable[[str, float, int], None] | None = None

        # Price state (guarded by _lock)
        self._prices: dict[str, float] = {}
        self._server_ts: dict[str, int] = {}   # ticker -> server timestamp (ms)
        self._local_ts: dict[str, float] = {}   # ticker -> time.time()
        self._lock = threading.Lock()

        # Connection state
        self._running = False
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()

        # Metrics
        self._reconnect_count = 0
        self._message_count = 0
        self._dropped_count = 0

    # ---- public API ----

    def start(self) -> None:
        """백그라운드 스레드에서 WebSocket 연결을 시작한다."""
        self._running = True
        # REST 초기 동기화 — WS 연결 전에 가격 확보
        self._sync_from_rest("initial")
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if self._connected.wait(timeout=10.0):
            logger.info("WebSocket started (initial prices: {})", len(self._prices))
        else:
            logger.warning("WebSocket connection timeout (will retry in background)")

    def stop(self) -> None:
        """WebSocket 연결을 종료한다."""
        self._running = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                self._ws.close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info(
            "WebSocket stopped (messages={}, reconnects={}, dropped={})",
            self._message_count, self._reconnect_count, self._dropped_count,
        )

    def get_prices(self) -> dict[str, float]:
        """현재 수신된 모든 가격의 스레드 안전 복사본을 반환한다."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """단일 종목 가격 조회. 수신된 적 없으면 None."""
        with self._lock:
            return self._prices.get(ticker)

    def is_connected(self) -> bool:
        """WebSocket 연결 상태를 반환한다."""
        return self._connected.is_set()

    def stale_tickers(self, max_age_seconds: float = 60.0) -> list[str]:
        """지정 시간 이상 갱신이 없는 종목 목록.

        한 번도 수신되지 않은 종목도 stale로 간주한다.
        """
        now = time.time()
        with self._lock:
            return [
                t for t in self._tickers
                if (last := self._local_ts.get(t)) is None
                or (now - last) > max_age_seconds
            ]

    def set_price_callback(
        self, cb: Callable[[str, float, int], None] | None,
    ) -> None:
        """가격 업데이트 ��백을 설정한다.

        콜백 시그니처: (code: str, price: float, server_ts: int) -> None
        설정 후 모든 가격 이벤트에서 호출된다.
        """
        self._on_price_update = cb

    @property
    def stats(self) -> dict:
        """운영 모니터링용 통계."""
        return {
            "connected": self.is_connected(),
            "reconnect_count": self._reconnect_count,
            "message_count": self._message_count,
            "dropped_count": self._dropped_count,
            "tracked_tickers": len(self._tickers),
            "priced_tickers": len(self._prices),
        }

    # ---- private: REST sync ----

    def _sync_from_rest(self, reason: str) -> None:
        """REST API로 전 종목 현재가를 동기화한다."""
        if self._rest_fetcher is None:
            return
        try:
            prices = self._rest_fetcher(self._tickers)
            now = time.time()
            with self._lock:
                for ticker, price in prices.items():
                    if price is not None and price > 0:
                        self._prices[ticker] = float(price)
                        self._local_ts[ticker] = now
                        # REST 동기화 시 server_ts = 0 → WS 메시지가 항상 우선
                        if ticker not in self._server_ts:
                            self._server_ts[ticker] = 0
            logger.info("REST sync ({}): {}/{} tickers", reason, len(prices), len(self._tickers))
        except Exception:
            logger.warning("REST sync ({}) failed", reason, exc_info=True)

    # ---- private: connection loop ----

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._connect()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "WebSocket disconnected, reconnecting in {}s (count={})",
                    self._reconnect_delay, self._reconnect_count + 1,
                )
            self._connected.clear()
            if self._running:
                self._reconnect_count += 1
                # reconnect 전 REST 재동기화로 stale 즉시 해소
                self._sync_from_rest("reconnect")
                time.sleep(self._reconnect_delay)

    def _connect(self) -> None:
        ws = websocket.WebSocketApp(
            "wss://api.upbit.com/websocket/v1",
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws = ws
        ws.run_forever(ping_interval=0)  # Upbit manages keepalive server-side

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        # snapshot + realtime 모두 수신 (is_only_realtime 제거)
        subscribe = json.dumps([
            {"ticket": f"auto-coin-{uuid4().hex[:8]}"},
            {"type": "ticker", "codes": self._tickers},
            {"format": "DEFAULT"},
        ])
        ws.send(subscribe)
        self._connected.set()
        logger.info(
            "WebSocket connected, subscribed to {} tickers (reconnects={})",
            len(self._tickers), self._reconnect_count,
        )

    def _on_message(
        self,
        ws: websocket.WebSocketApp | None,
        message: str | bytes,
    ) -> None:
        try:
            data = json.loads(
                message if isinstance(message, str) else message.decode("utf-8"),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("WebSocket: unparseable message (len={})", len(message) if message else 0)
            return

        if data.get("type") != "ticker":
            return

        code = data.get("code")
        price = data.get("trade_price")
        if not code or price is None:
            return

        msg_ts: int = data.get("timestamp", 0)
        stream_type: str = data.get("stream_type", "")

        self._message_count += 1

        # Debug raw logging (처음 50건 + 이후 1000건마다 1건)
        if self._debug_log:
            cnt = self._message_count
            if cnt <= 50 or cnt % 1000 == 0:
                logger.debug(
                    "WS [{}] {} code={} price={} ts={} stream={}",
                    cnt, "SNAP" if stream_type == "SNAPSHOT" else "RT",
                    code, price, msg_ts, stream_type,
                )

        with self._lock:
            stored_ts = self._server_ts.get(code, 0)

            # Timestamp guard: 서버 시간이 기존보다 오래된 메시지는 무시
            if msg_ts < stored_ts:
                self._dropped_count += 1
                if self._debug_log:
                    logger.debug(
                        "WS dropped late: code={} msg_ts={} < stored_ts={}",
                        code, msg_ts, stored_ts,
                    )
                return

            self._prices[code] = float(price)
            self._server_ts[code] = msg_ts
            self._local_ts[code] = time.time()

        # 가격 콜백 (lock 밖에서 호출 — 콜백이 오래 걸려도 lock 점유 안 함)
        if self._on_price_update:
            try:
                self._on_price_update(code, float(price), msg_ts)
            except Exception:
                logger.warning("on_price_update callback failed", exc_info=True)

    def _on_error(
        self,
        ws: websocket.WebSocketApp | None,
        error: Exception,
    ) -> None:
        logger.warning("WebSocket error: {}", error)

    def _on_close(
        self,
        ws: websocket.WebSocketApp | None,
        close_status_code: int | None,
        close_msg: str | None,
    ) -> None:
        self._connected.clear()
        logger.info(
            "WebSocket closed: code={} msg={} (messages={}, reconnects={})",
            close_status_code, close_msg, self._message_count, self._reconnect_count,
        )

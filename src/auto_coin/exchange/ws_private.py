"""Upbit Private WebSocket — myOrder / myAsset 실시간 동기화.

업비트 개인 채널을 WebSocket으로 구독하여
주문 상태 전이와 잔고 변동을 실시간으로 추적한다.

초기화 흐름:
    1. REST 초기 자산 조회 (asset_fetcher 제공 시)
    2. JWT 토큰 생성 → private WS 연결
    3. myOrder + myAsset 구독
    4. 이벤트 수신 → 내부 상태 갱신

재연결 흐름:
    1. 연결 끊김 감지
    2. REST 재동기화 (미완료 주문 확인 + 자산 재조회)
    3. 새 JWT 토큰 → WS 재연결 → 재구독

Reconcile 정책:
    - 주문: terminal state(done/cancel)는 불변. 비terminal은 최신 이벤트 수용.
    - 자산: 매 이벤트가 전체 스냅샷. timestamp 기반 ordering.
    - reconnect 후: REST full resync → WS 증분 반영 재개.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import websocket
from loguru import logger

try:
    import jwt as pyjwt
except ImportError:  # pragma: no cover
    pyjwt = None  # type: ignore[assignment]


def _safe_float(val: Any) -> float:
    """값을 float로 안전하게 변환."""
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# 주문 상태: terminal state는 불변
_TERMINAL_STATES = frozenset({"done", "cancel"})


@dataclass
class OrderState:
    """추적 중인 주문의 현재 상태."""

    uuid: str
    code: str
    state: str  # wait | watch | trade | done | cancel
    ask_bid: str  # ASK | BID
    order_type: str  # limit | price | market
    avg_price: float = 0.0
    volume: float = 0.0
    remaining_volume: float = 0.0
    executed_volume: float = 0.0
    paid_fee: float = 0.0
    identifier: str = ""
    trade_uuid: str = ""
    timestamp: int = 0  # server timestamp (ms)
    updated_at: float = field(default_factory=time.time)


@dataclass
class AssetEntry:
    """단일 자산 항목."""

    currency: str
    balance: float = 0.0
    locked: float = 0.0
    avg_buy_price: float = 0.0
    unit_currency: str = "KRW"


class UpbitPrivateWebSocket:
    """Upbit 개인 채널 WebSocket (myOrder + myAsset).

    사용:
        ws = UpbitPrivateWebSocket(
            access_key="...", secret_key="...",
            asset_fetcher=lambda: {"KRW": {"balance": 1000000, ...}},
        )
        ws.start()
        order = ws.get_order("uuid-...")
        assets = ws.get_assets()
        ws.stop()
    """

    _ENDPOINT = "wss://api.upbit.com/websocket/v1/private"
    _PING_INTERVAL = 30
    _PING_TIMEOUT = 10

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        *,
        tickers: list[str] | None = None,
        order_fetcher: Callable[[str], dict] | None = None,
        asset_fetcher: Callable[[], dict[str, dict]] | None = None,
        on_order_update: Callable[[OrderState], None] | None = None,
        on_asset_update: Callable[[dict[str, AssetEntry]], None] | None = None,
        reconnect_delay: float = 5.0,
        debug_log: bool = False,
    ) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._tickers = [t.upper() for t in tickers] if tickers else None
        self._order_fetcher = order_fetcher
        self._asset_fetcher = asset_fetcher
        self._on_order_update = on_order_update
        self._on_asset_update = on_asset_update
        self._reconnect_delay = reconnect_delay
        self._debug_log = debug_log

        # Order tracking
        self._orders: dict[str, OrderState] = {}
        self._order_lock = threading.Lock()

        # Asset tracking
        self._assets: dict[str, AssetEntry] = {}
        self._asset_ts: int = 0
        self._asset_lock = threading.Lock()

        # Connection
        self._running = False
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()

        # Metrics
        self._reconnect_count = 0
        self._order_event_count = 0
        self._asset_event_count = 0

    # ---- public API ----

    def start(self) -> None:
        """백그라운드 스레드에서 Private WS 연결을 시작한다."""
        if not self._access_key or not self._secret_key:
            logger.warning("Private WS: credentials not configured, skipping")
            return
        self._running = True
        self._sync_assets_from_rest("initial")
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if self._connected.wait(timeout=10.0):
            logger.info("Private WebSocket started (assets={})", len(self._assets))
        else:
            logger.warning("Private WebSocket connection timeout (will retry)")

    def stop(self) -> None:
        """Private WS 연결을 종료한다."""
        self._running = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                self._ws.close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        logger.info(
            "Private WS stopped (order_events={}, asset_events={}, reconnects={})",
            self._order_event_count,
            self._asset_event_count,
            self._reconnect_count,
        )

    def get_order(self, uuid: str) -> OrderState | None:
        """추적 중인 주문 조회. 없으면 None."""
        with self._order_lock:
            return self._orders.get(uuid)

    def get_tracked_orders(self) -> dict[str, OrderState]:
        """추적 중인 모든 주문의 복사본."""
        with self._order_lock:
            return dict(self._orders)

    def get_assets(self) -> dict[str, AssetEntry]:
        """현재 자산 상태의 복사본."""
        with self._asset_lock:
            return dict(self._assets)

    def get_asset(self, currency: str) -> AssetEntry | None:
        """단일 자산 조회."""
        with self._asset_lock:
            return self._assets.get(currency.upper())

    def is_connected(self) -> bool:
        """Private WS 연결 상태."""
        return self._connected.is_set()

    @property
    def stats(self) -> dict:
        """운영 모니터링용 통계."""
        return {
            "connected": self.is_connected(),
            "reconnect_count": self._reconnect_count,
            "order_event_count": self._order_event_count,
            "asset_event_count": self._asset_event_count,
            "tracked_orders": len(self._orders),
            "tracked_assets": len(self._assets),
        }

    # ---- JWT ----

    def _generate_jwt(self) -> str:
        if pyjwt is None:  # pragma: no cover
            raise RuntimeError("PyJWT required for private WS (pip install pyjwt)")
        payload = {
            "access_key": self._access_key,
            "nonce": uuid4().hex,
        }
        return pyjwt.encode(payload, self._secret_key, algorithm="HS256")

    # ---- REST sync ----

    def _sync_assets_from_rest(self, reason: str) -> None:
        """REST API로 자산 상태를 동기화한다."""
        if self._asset_fetcher is None:
            return
        try:
            raw = self._asset_fetcher()
            with self._asset_lock:
                self._assets = {
                    currency: AssetEntry(
                        currency=currency,
                        balance=_safe_float(info.get("balance")),
                        locked=_safe_float(info.get("locked")),
                        avg_buy_price=_safe_float(info.get("avg_buy_price")),
                        unit_currency=info.get("unit_currency", "KRW"),
                    )
                    for currency, info in raw.items()
                }
                self._asset_ts = 0  # REST → WS가 항상 우선
            logger.info("REST asset sync ({}): {} currencies", reason, len(raw))
        except Exception:
            logger.warning("REST asset sync ({}) failed", reason, exc_info=True)

    def _reconcile_orders_from_rest(self, reason: str) -> None:
        """REST API로 미완료 주문 상태를 재확인한다."""
        if self._order_fetcher is None:
            return
        with self._order_lock:
            pending = [
                (uuid, o.state)
                for uuid, o in self._orders.items()
                if o.state not in _TERMINAL_STATES
            ]
        if not pending:
            return
        reconciled = 0
        for uuid, ws_state in pending:
            try:
                rest_data = self._order_fetcher(uuid)
                rest_state = rest_data.get("state", "")
                if rest_state in _TERMINAL_STATES:
                    with self._order_lock:
                        existing = self._orders.get(uuid)
                        if existing and existing.state not in _TERMINAL_STATES:
                            existing.state = rest_state
                            existing.executed_volume = _safe_float(
                                rest_data.get("executed_volume"),
                            )
                            existing.remaining_volume = _safe_float(
                                rest_data.get("remaining_volume"),
                            )
                            existing.paid_fee = _safe_float(rest_data.get("paid_fee"))
                            existing.avg_price = _safe_float(rest_data.get("avg_price"))
                            existing.updated_at = time.time()
                            reconciled += 1
                            logger.info(
                                "order reconcile [{}]: {} -> {} (REST)",
                                uuid[:8],
                                ws_state,
                                rest_state,
                            )
            except Exception:
                logger.warning("order reconcile failed for {}", uuid[:8], exc_info=True)
        if reconciled:
            logger.info(
                "REST order reconcile ({}): {}/{} advanced",
                reason,
                reconciled,
                len(pending),
            )

    def _reconcile(self, reason: str) -> None:
        """REST full resync: 자산 + 미완료 주문."""
        self._sync_assets_from_rest(reason)
        self._reconcile_orders_from_rest(reason)

    # ---- connection loop ----

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._connect()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Private WS disconnected, reconnecting in {}s (count={})",
                    self._reconnect_delay,
                    self._reconnect_count + 1,
                )
            self._connected.clear()
            if self._running:
                self._reconnect_count += 1
                self._reconcile("reconnect")
                time.sleep(self._reconnect_delay)

    def _connect(self) -> None:
        token = self._generate_jwt()
        ws = websocket.WebSocketApp(
            self._ENDPOINT,
            header=[f"Authorization: Bearer {token}"],
            on_open=self._on_open,
            on_message=self._on_message,
            on_ping=self._on_ping,
            on_pong=self._on_pong,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws = ws
        if self._debug_log:
            logger.debug(
                "Private WS keepalive enabled: ping_interval={} ping_timeout={}",
                self._PING_INTERVAL,
                self._PING_TIMEOUT,
            )
        ws.run_forever(
            ping_interval=self._PING_INTERVAL,
            ping_timeout=self._PING_TIMEOUT,
        )  # keepalive: idle 연결 종료 방지

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        subscribe: list[dict] = [
            {"ticket": f"auto-coin-priv-{uuid4().hex[:8]}"},
            {"type": "myOrder"},
            {"type": "myAsset"},
            {"format": "DEFAULT"},
        ]
        # myOrder에 codes를 지정하면 해당 마켓만 구독
        if self._tickers:
            subscribe[1]["codes"] = self._tickers
        ws.send(json.dumps(subscribe))
        self._connected.set()
        logger.info(
            "Private WS connected, subscribed myOrder+myAsset (reconnects={})",
            self._reconnect_count,
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
            logger.warning("Private WS: unparseable message")
            return

        msg_type = data.get("type")
        if msg_type == "myOrder":
            self._handle_order(data)
        elif msg_type == "myAsset":
            self._handle_asset(data)

    def _on_ping(
        self,
        ws: websocket.WebSocketApp | None,
        message: str | bytes,
    ) -> None:
        if self._debug_log:
            logger.debug(
                "Private WS ping received (payload_len={}, reconnects={})",
                len(message) if message else 0,
                self._reconnect_count,
            )

    def _on_pong(
        self,
        ws: websocket.WebSocketApp | None,
        message: str | bytes,
    ) -> None:
        if self._debug_log:
            logger.debug(
                "Private WS pong received (payload_len={}, reconnects={})",
                len(message) if message else 0,
                self._reconnect_count,
            )

    # ---- myOrder ----

    def _handle_order(self, data: dict) -> None:
        uuid = data.get("uuid", "")
        if not uuid:
            return

        new_state = data.get("state", "")

        with self._order_lock:
            existing = self._orders.get(uuid)

            # Terminal state는 불변 — 역행 차단
            if existing and existing.state in _TERMINAL_STATES:
                if self._debug_log:
                    logger.debug(
                        "myOrder skip [{}]: already terminal ({})",
                        uuid[:8],
                        existing.state,
                    )
                return

            prev_state = existing.state if existing else None

            order = OrderState(
                uuid=uuid,
                code=data.get("code", ""),
                state=new_state,
                ask_bid=data.get("ask_bid", ""),
                order_type=data.get("order_type", ""),
                avg_price=_safe_float(data.get("avg_price")),
                volume=_safe_float(data.get("volume")),
                remaining_volume=_safe_float(data.get("remaining_volume")),
                executed_volume=_safe_float(data.get("executed_volume")),
                paid_fee=_safe_float(data.get("paid_fee")),
                identifier=data.get("identifier", "") or "",
                trade_uuid=data.get("trade_uuid", "") or "",
                timestamp=int(data.get("order_timestamp", 0) or 0),
            )
            self._orders[uuid] = order

        self._order_event_count += 1

        # 주문 라이프사이클 추적 로그
        if prev_state != new_state:
            logger.info(
                "myOrder [{}] {} {} {} -> {} exec={}/{} avg={} fee={}",
                uuid[:8],
                order.code,
                order.ask_bid,
                prev_state or "NEW",
                new_state,
                order.executed_volume,
                order.volume,
                order.avg_price,
                order.paid_fee,
            )
        elif self._debug_log:
            logger.debug(
                "myOrder [{}] {} (fill update) exec={}/{} avg={}",
                uuid[:8],
                new_state,
                order.executed_volume,
                order.volume,
                order.avg_price,
            )

        if self._on_order_update:
            try:
                self._on_order_update(order)
            except Exception:
                logger.warning("on_order_update callback failed", exc_info=True)

    # ---- myAsset ----

    def _handle_asset(self, data: dict) -> None:
        msg_ts = int(data.get("timestamp", 0) or 0)
        assets_raw = data.get("assets", [])
        if not assets_raw:
            return

        with self._asset_lock:
            if msg_ts < self._asset_ts:
                if self._debug_log:
                    logger.debug("myAsset skip: ts={} < stored={}", msg_ts, self._asset_ts)
                return

            new_assets: dict[str, AssetEntry] = {}
            for a in assets_raw:
                currency = (a.get("currency") or "").upper()
                if not currency:
                    continue
                new_assets[currency] = AssetEntry(
                    currency=currency,
                    balance=_safe_float(a.get("balance")),
                    locked=_safe_float(a.get("locked")),
                    avg_buy_price=_safe_float(a.get("avg_buy_price")),
                    unit_currency=a.get("unit_currency", "KRW"),
                )
            self._assets = new_assets
            self._asset_ts = msg_ts

        self._asset_event_count += 1
        logger.info("myAsset updated: {} currencies", len(new_assets))

        if self._on_asset_update:
            try:
                self._on_asset_update(new_assets)
            except Exception:
                logger.warning("on_asset_update callback failed", exc_info=True)

    # ---- error / close ----

    def _on_error(
        self,
        ws: websocket.WebSocketApp | None,
        error: Exception,
    ) -> None:
        logger.warning("Private WS error: {}", error)

    def _on_close(
        self,
        ws: websocket.WebSocketApp | None,
        close_status_code: int | None,
        close_msg: str | None,
    ) -> None:
        self._connected.clear()
        logger.info(
            "Private WS closed: code={} msg={} (orders={}, assets={}, reconnects={})",
            close_status_code,
            close_msg,
            self._order_event_count,
            self._asset_event_count,
            self._reconnect_count,
        )

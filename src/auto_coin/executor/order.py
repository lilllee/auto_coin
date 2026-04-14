"""주문 실행기.

`RiskManager`가 생산한 `Decision`을 받아 실제 거래소(또는 페이퍼 시뮬레이션)로 보낸다.
포지션·주문 기록은 `OrderStore`로 영속화한다.

페이퍼 모드(`live=False`)가 디폴트다. 실거래는 호출자가 명시적으로 `live=True`를 전달해야 한다.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

from loguru import logger

from auto_coin.exchange.upbit_client import UpbitClient
from auto_coin.executor.store import OrderRecord, OrderStore, Position, now_iso
from auto_coin.formatting import format_price
from auto_coin.risk.manager import Action, Decision


class OrderExecutor:
    def __init__(
        self,
        client: UpbitClient,
        store: OrderStore,
        ticker: str,
        *,
        live: bool = False,
    ) -> None:
        self._client = client
        self._store = store
        self._ticker = ticker
        self._live = live
        if live and not client.authenticated:
            raise ValueError("live mode requires authenticated UpbitClient")

    @property
    def live(self) -> bool:
        return self._live

    def execute(self, decision: Decision, *, current_price: float) -> OrderRecord | None:
        """결정 실행. HOLD면 None, BUY/SELL이면 OrderRecord 반환."""
        if decision.action is Action.HOLD:
            logger.debug("HOLD: {}", decision.reason)
            return None
        if decision.action is Action.BUY:
            return self._do_buy(decision, current_price=current_price)
        if decision.action is Action.SELL:
            return self._do_sell(decision, current_price=current_price)
        raise ValueError(f"unknown action: {decision.action!r}")

    # ----- buy -----

    def _do_buy(self, decision: Decision, *, current_price: float) -> OrderRecord:
        if decision.krw_amount is None or decision.krw_amount <= 0:
            raise ValueError("BUY decision missing krw_amount")
        client_uuid = self._new_uuid()
        if self._live:
            result = self._client.buy_market(self._ticker, decision.krw_amount)
            external_uuid = result.uuid
            status = "placed"
            note = f"client_uuid={client_uuid}"
        else:
            external_uuid = client_uuid
            status = "paper"
            note = "paper buy"

        # 페이퍼 체결 가정: 현재가에 즉시 전량 체결
        volume = decision.krw_amount / current_price if current_price > 0 else 0.0
        record = OrderRecord(
            uuid=external_uuid,
            side="buy",
            market=self._ticker,
            krw_amount=decision.krw_amount,
            volume=volume if not self._live else None,
            price=current_price if not self._live else None,
            placed_at=now_iso(),
            status=status,
            note=note,
        )
        self._record_and_open_position(record, current_price=current_price, volume=volume)
        logger.info("BUY {} {:.0f} KRW @ {} (live={}, uuid={})",
                    self._ticker, decision.krw_amount,
                    format_price(current_price), self._live, record.uuid)
        return record

    # ----- sell -----

    def _do_sell(self, decision: Decision, *, current_price: float) -> OrderRecord:
        if decision.volume is None or decision.volume <= 0:
            raise ValueError("SELL decision missing volume")
        client_uuid = self._new_uuid()
        if self._live:
            result = self._client.sell_market(self._ticker, decision.volume)
            external_uuid = result.uuid
            status = "placed"
            note = f"client_uuid={client_uuid}"
        else:
            external_uuid = client_uuid
            status = "paper"
            note = "paper sell"

        record = OrderRecord(
            uuid=external_uuid,
            side="sell",
            market=self._ticker,
            krw_amount=decision.volume * current_price if not self._live else None,
            volume=decision.volume,
            price=current_price if not self._live else None,
            placed_at=now_iso(),
            status=status,
            note=f"{note} | reason={decision.reason}",
        )
        self._record_and_close_position(record, current_price=current_price)
        logger.info("SELL {} vol={:.8f} @ {} (live={}, uuid={}) — {}",
                    self._ticker, decision.volume,
                    format_price(current_price), self._live, record.uuid,
                    decision.reason)
        return record

    # ----- state mutations -----

    def _record_and_open_position(
        self, record: OrderRecord, *, current_price: float, volume: float
    ) -> None:
        state = self._store.load()
        if any(o.uuid == record.uuid for o in state.orders):
            logger.warning("duplicate order uuid {} — skipping", record.uuid)
            return
        state.orders.append(record)
        # 페이퍼는 즉시 체결 가정 → 포지션 생성. 실거래는 체결 확인 전이라도 임시로 보유 표시
        # (M6에서 체결 폴링 추가 예정)
        state.position = Position(
            ticker=self._ticker,
            volume=volume if not self._live else 0.0,
            avg_entry_price=current_price,
            entry_uuid=record.uuid,
            entry_at=record.placed_at,
        )
        self._store.save(state)

    def _record_and_close_position(self, record: OrderRecord, *, current_price: float) -> None:
        state = self._store.load()
        if any(o.uuid == record.uuid for o in state.orders):
            logger.warning("duplicate order uuid {} — skipping", record.uuid)
            return
        state.orders.append(record)
        # 일일 손익 누적: 페이퍼 모드에서만 정확히 계산 가능 (체결가 알 수 있음)
        if state.position is not None and not self._live and state.position.avg_entry_price > 0:
            ret = (current_price - state.position.avg_entry_price) / state.position.avg_entry_price
            state = replace(state, daily_pnl_ratio=state.daily_pnl_ratio + ret)
        state.position = None
        self._store.save(state)

    @staticmethod
    def _new_uuid() -> str:
        return str(uuid.uuid4())

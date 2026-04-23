"""주문 실행기.

`RiskManager`가 생산한 `Decision`을 받아 실제 거래소(또는 페이퍼 시뮬레이션)로 보낸다.
포지션·주문 기록은 `OrderStore`로 영속화한다.

페이퍼 모드(`live=False`)가 디폴트다. 실거래는 호출자가 명시적으로 `live=True`를 전달해야 한다.
"""

from __future__ import annotations

import time
import uuid

from loguru import logger

from auto_coin.config import UPBIT_FEE_RATE
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
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
        strategy_name: str = "",
        on_trade_closed=None,
        fill_poll_interval: float = 1.0,
        fill_poll_timeout: float = 10.0,
    ) -> None:
        self._client = client
        self._store = store
        self._ticker = ticker
        self._live = live
        self._strategy_name = strategy_name
        self._on_trade_closed = on_trade_closed
        self._fill_poll_interval = fill_poll_interval
        self._fill_poll_timeout = fill_poll_timeout
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

    # ----- fill polling -----

    def _poll_fill(self, order_uuid: str, side: str) -> dict | None:
        """실거래 체결 확인 폴링. 타임아웃 내 체결되면 상세 정보 반환, 아니면 None."""
        if not self._live:
            return None

        interval = self._fill_poll_interval
        timeout = self._fill_poll_timeout
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                order = self._client.get_order(order_uuid)
            except UpbitError as exc:
                logger.warning("fill poll failed for {}: {}", order_uuid, exc)
                time.sleep(interval)
                continue

            state_val = order.get("state", "")
            # 업비트 주문 상태: wait(대기), watch(예약), done(체결완료), cancel(취소)
            if state_val == "done":
                logger.info("order {} filled ({})", order_uuid, side)
                return order
            if state_val == "cancel":
                logger.warning("order {} was cancelled", order_uuid)
                return order

            time.sleep(interval)

        logger.warning("fill poll timeout for {} after {:.0f}s", order_uuid, timeout)
        return None

    @staticmethod
    def _extract_sell_fill(
        fill_info: dict,
    ) -> tuple[float | None, float | None, float | None]:
        """fill_info에서 (avg_price, executed_volume, paid_fee)를 안전하게 추출.

        업비트 `get_order` 응답 스펙 편차에 강건하게 대응:
        1) avg_price: 직접 필드 → 없으면 trades[] 합산(sum(funds)/sum(volume)).
        2) executed_volume: 직접 필드.
        3) paid_fee: 직접 필드.
        각각 구할 수 없거나 0이면 None을 반환하여 호출자가 fallback을 쓰게 한다.
        """
        def _f(x) -> float | None:
            if x is None:
                return None
            try:
                v = float(x)
            except (TypeError, ValueError):
                return None
            return v if v > 0 else None

        avg_price = _f(fill_info.get("avg_price"))
        executed_volume = _f(fill_info.get("executed_volume"))
        paid_fee = _f(fill_info.get("paid_fee"))

        if avg_price is None:
            trades = fill_info.get("trades") or []
            if isinstance(trades, list) and trades:
                vol_sum = 0.0
                funds_sum = 0.0
                for tr in trades:
                    if not isinstance(tr, dict):
                        continue
                    v = _f(tr.get("volume"))
                    f = _f(tr.get("funds"))
                    if f is None:
                        p = _f(tr.get("price"))
                        if p is not None and v is not None:
                            f = p * v
                    if v is not None and f is not None:
                        vol_sum += v
                        funds_sum += f
                if vol_sum > 0 and funds_sum > 0:
                    avg_price = funds_sum / vol_sum

        return avg_price, executed_volume, paid_fee

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
        # 실거래는 추정치를 기록 (체결 확인 전이지만 force_exit 등이 volume 0을 보지 않도록)
        volume = decision.krw_amount / current_price if current_price > 0 else 0.0

        # 실거래 체결 확인 폴링 — 체결되면 실제 데이터로 갱신
        if self._live:
            fill_info = self._poll_fill(external_uuid, "buy")
            if fill_info and fill_info.get("state") == "done":
                executed_volume = float(fill_info.get("executed_volume", 0))
                avg_price = (
                    float(fill_info["avg_price"])
                    if fill_info.get("avg_price")
                    else current_price
                )
                if executed_volume > 0:
                    volume = executed_volume
                    current_price = avg_price
                status = "filled"
                note = f"client_uuid={client_uuid} | filled"

        record = OrderRecord(
            uuid=external_uuid,
            side="buy",
            market=self._ticker,
            krw_amount=decision.krw_amount,
            volume=volume,
            price=current_price,
            placed_at=now_iso(),
            status=status,
            note=note,
        )
        self._record_and_open_position(record, current_price=current_price, volume=volume)
        logger.info("BUY {} {:.0f} KRW @ {} (live={}, uuid={}, status={})",
                    self._ticker, decision.krw_amount,
                    format_price(current_price), self._live, record.uuid, status)
        return record

    # ----- sell -----

    def _do_sell(self, decision: Decision, *, current_price: float) -> OrderRecord:
        if decision.volume is None or decision.volume <= 0:
            # 실거래에서 position.volume이 추정치로 기록된 경우 0.0이 올 수 있다.
            # store에서 포지션 volume을 폴백으로 사용한다.
            state = self._store.load()
            fallback_volume = state.position.volume if state.position is not None else None
            if fallback_volume and fallback_volume > 0:
                logger.warning(
                    "SELL decision.volume={} — falling back to position.volume={:.8f}",
                    decision.volume, fallback_volume,
                )
                decision = Decision(
                    action=decision.action,
                    reason=decision.reason,
                    volume=fallback_volume,
                    krw_amount=decision.krw_amount,
                    reason_code=decision.reason_code,
                )
            else:
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

        # 실거래 체결 확인 폴링 — fill 성공 시 실제 avg_price / executed_volume / paid_fee 추출
        fill_avg_price: float | None = None
        fill_volume: float | None = None
        paid_fee: float | None = None
        if self._live:
            fill_info = self._poll_fill(external_uuid, "sell")
            if fill_info and fill_info.get("state") == "done":
                status = "filled"
                fill_avg_price, fill_volume, paid_fee = self._extract_sell_fill(fill_info)
                note = f"client_uuid={client_uuid} | filled"

        # OrderRecord: live면 fill 값 우선, 없으면 None(=미확정). paper는 current_price 사용.
        if self._live:
            record_price = fill_avg_price                        # None이면 미확정
            record_volume = fill_volume if fill_volume is not None else decision.volume
            record_krw = (
                fill_avg_price * fill_volume
                if (fill_avg_price is not None and fill_volume is not None)
                else None
            )
        else:
            record_price = current_price
            record_volume = decision.volume
            record_krw = decision.volume * current_price

        record = OrderRecord(
            uuid=external_uuid,
            side="sell",
            market=self._ticker,
            krw_amount=record_krw,
            volume=record_volume,
            price=record_price,
            placed_at=now_iso(),
            status=status,
            note=(
                f"{note} | reason={decision.reason} | "
                f"decision_price={format_price(current_price)}"
            ),
        )
        # TradeLog용 effective 값: fill이 있으면 실제 체결 기준, 없으면 decision 기준 fallback.
        effective_exit_price = fill_avg_price if fill_avg_price is not None else current_price
        self._record_and_close_position(
            record, current_price=effective_exit_price,
            reason_code=decision.reason_code, reason_text=decision.reason,
            fill_volume=fill_volume,
            paid_fee=paid_fee,
            decision_exit_price=current_price,
        )
        logger.info(
            "SELL {} vol={:.8f} @ {} (live={}, uuid={}, status={}, fill_price={}, paid_fee={}) — {}",
            self._ticker, record_volume, format_price(effective_exit_price),
            self._live, record.uuid, status,
            format_price(fill_avg_price) if fill_avg_price else "N/A",
            f"{paid_fee:.2f}" if paid_fee else "N/A",
            decision.reason,
        )
        return record

    # ----- state mutations -----

    def _record_and_open_position(
        self, record: OrderRecord, *, current_price: float, volume: float
    ) -> None:
        def _update(state):
            if any(o.uuid == record.uuid for o in state.orders):
                logger.warning("duplicate order uuid {} — skipping", record.uuid)
                return state
            state.orders.append(record)
            # 페이퍼는 즉시 체결 가정 → 포지션 생성.
            # 실거래는 체결 확인 후 실제 volume/price로 기록 (폴링 타임아웃 시 추정치 사용).
            state.position = Position(
                ticker=self._ticker,
                volume=volume,
                avg_entry_price=current_price,
                entry_uuid=record.uuid,
                entry_at=record.placed_at,
            )
            return state

        self._store.atomic_update(_update)

    def _record_and_close_position(
        self, record: OrderRecord, *, current_price: float,
        reason_code: str | None = None, reason_text: str | None = None,
        fill_volume: float | None = None,
        paid_fee: float | None = None,
        decision_exit_price: float | None = None,
    ) -> None:
        """포지션 청산 기록 + TradeLog callback.

        Args:
            current_price: 청산 "유효" 가격. live면 fill avg_price (있을 때), 없으면
                decision 시점 current_price. paper는 항상 decision 시점 가격.
            fill_volume: live 체결 확인된 volume. None이면 position.volume fallback.
            paid_fee: live 실제 매도 수수료. None이면 UPBIT_FEE_RATE 근사.
            decision_exit_price: 의사결정 시점의 current_price. TradeLog에 원본 보존 →
                나중에 슬리피지(decision vs fill) 계산 가능.
        """
        def _update(state):
            if any(o.uuid == record.uuid for o in state.orders):
                logger.warning("duplicate order uuid {} — skipping", record.uuid)
                return state

            state.orders.append(record)
            # 일일 손익 누적 (fee-adjusted) — paper 전용 기존 동작 유지
            if state.position is not None and state.position.avg_entry_price > 0:
                fee_rate = UPBIT_FEE_RATE
                ret_legacy = (
                    current_price * (1 - fee_rate)
                ) / (state.position.avg_entry_price * (1 + fee_rate)) - 1
                if not self._live:
                    state.daily_pnl_ratio += ret_legacy

                if self._on_trade_closed is not None:
                    try:
                        from datetime import datetime as _dt

                        actual_volume = (
                            fill_volume
                            if (fill_volume is not None and fill_volume > 0)
                            else state.position.volume
                        )
                        entry_val = state.position.avg_entry_price * actual_volume
                        exit_val = current_price * actual_volume

                        # fee 우선순위:
                        #   1) live + 실제 paid_fee → sell_fee = paid_fee, buy_fee ≈ entry_val*rate
                        #   2) fallback (paper 및 live-no-paid_fee) → 기존 공식 유지
                        if self._live and paid_fee is not None and paid_fee > 0:
                            buy_fee_approx = entry_val * fee_rate
                            fee_krw = buy_fee_approx + float(paid_fee)
                            pnl_krw = exit_val - entry_val - fee_krw
                            pnl_ratio = pnl_krw / entry_val if entry_val > 0 else 0.0
                        else:
                            fee_krw = (entry_val + exit_val) * fee_rate
                            pnl_krw = exit_val - entry_val - fee_krw
                            pnl_ratio = ret_legacy

                        entry_dt = _dt.fromisoformat(state.position.entry_at)
                        exit_dt = _dt.fromisoformat(record.placed_at)
                        hold_sec = max(int((exit_dt - entry_dt).total_seconds()), 0)
                        self._on_trade_closed({
                            "ticker": self._ticker,
                            "strategy_name": self._strategy_name,
                            "mode": "live" if self._live else "paper",
                            "entry_at": entry_dt,
                            "exit_at": exit_dt,
                            "entry_price": state.position.avg_entry_price,
                            "exit_price": current_price,
                            "decision_exit_price": decision_exit_price,
                            "quantity": actual_volume,
                            "entry_value_krw": entry_val,
                            "exit_value_krw": exit_val,
                            "fee_krw": fee_krw,
                            "pnl_ratio": pnl_ratio,
                            "pnl_krw": pnl_krw,
                            "hold_seconds": hold_sec,
                            "exit_reason_code": reason_code,
                            "exit_reason_text": reason_text,
                        })
                    except Exception:
                        logger.warning("on_trade_closed callback failed", exc_info=True)

            state.last_exit_at = now_iso()
            state.position = None
            return state

        self._store.atomic_update(_update)

    @staticmethod
    def _new_uuid() -> str:
        return str(uuid.uuid4())

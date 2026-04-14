"""실거래 안전판.

`RiskManager.evaluate`는 Strategy 시그널을 그대로 통과시키지 않는다:
- BUY는 잔고/한도/킬스위치 통과 시에만 승인
- SELL은 보유 중일 때만 승인
- HOLD라도 보유 포지션이 손절선에 닿으면 강제 SELL

이 모듈은 I/O를 하지 않는다 — 모든 상태는 호출자가 `RiskContext`로 주입한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from auto_coin.config import Settings
from auto_coin.strategy.base import Signal


class Action(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str
    krw_amount: float | None = None  # BUY 시 매수에 사용할 KRW
    volume: float | None = None      # SELL 시 매도 수량


@dataclass(frozen=True)
class RiskContext:
    krw_balance: float
    coin_balance: float
    current_price: float
    avg_entry_price: float | None = None  # 보유 중일 때만 손절 평가에 사용
    # 일일 손익률 — 단일 종목 모드면 이 종목만, 포트폴리오 모드면 전 종목 합산.
    # 호출자(TradingBot)가 값을 세팅할 책임을 진다.
    daily_pnl_ratio: float = 0.0
    # 포트폴리오 제약 (멀티 종목). 단일 종목이면 기본값 그대로 쓰면 된다.
    portfolio_open_positions: int = 0  # 지금 보유 중인 종목 수 (자신 제외 X, 포함해서 센다)
    portfolio_max_positions: int = 1   # 동시 보유 상한
    cooldown_active: bool = False  # True면 해당 종목이 쿨다운 기간 중


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def evaluate(self, signal: Signal, ctx: RiskContext) -> Decision:
        s = self._s
        has_position = ctx.coin_balance > 0

        # 0) 가격 데이터 무효 — 어떤 판단도 하지 않음
        if ctx.current_price <= 0:
            return Decision(Action.HOLD, reason="invalid price (<=0)")

        # 1) 보유 중 손절은 모든 다른 판단보다 우선 — 즉시 청산
        if has_position and ctx.avg_entry_price is not None:
            if ctx.avg_entry_price <= 0:
                # avg_entry_price가 0 이하이면 P&L 계산 불가 — 안전을 위해 강제 청산
                return Decision(
                    action=Action.SELL,
                    reason="avg_entry_price invalid (<=0), forced exit for safety",
                    volume=ctx.coin_balance,
                )
            unrealized = (ctx.current_price - ctx.avg_entry_price) / ctx.avg_entry_price
            if unrealized <= s.stop_loss_ratio:
                return Decision(
                    action=Action.SELL,
                    reason=f"stop_loss triggered ({unrealized*100:+.2f}% <= {s.stop_loss_ratio*100:.2f}%)",
                    volume=ctx.coin_balance,
                )

        # 2) Kill-switch는 신규 진입(BUY)만 차단 — 기존 포지션 청산은 막지 않는다
        if s.kill_switch and signal is Signal.BUY:
            return Decision(Action.HOLD, reason="kill_switch active")

        # 2.5) 쿨다운 기간 중 신규 진입 차단
        if signal is Signal.BUY and ctx.cooldown_active:
            return Decision(Action.HOLD, reason="cooldown active (recent exit)")

        # 3) 일일 손실 한도 도달 시 신규 진입 차단
        if signal is Signal.BUY and ctx.daily_pnl_ratio <= s.daily_loss_limit:
            return Decision(
                Action.HOLD,
                reason=f"daily_loss_limit hit ({ctx.daily_pnl_ratio*100:+.2f}%)",
            )

        # 4) BUY 처리
        if signal is Signal.BUY:
            if has_position:
                return Decision(Action.HOLD, reason="already in position")
            # 포트폴리오 동시 보유 상한 체크 (단일 종목이면 기본 1 slot)
            if ctx.portfolio_open_positions >= ctx.portfolio_max_positions:
                return Decision(
                    Action.HOLD,
                    reason=f"portfolio slot full "
                           f"({ctx.portfolio_open_positions}/{ctx.portfolio_max_positions})",
                )
            krw_amount = ctx.krw_balance * s.max_position_ratio
            if krw_amount < s.min_order_krw:
                return Decision(
                    Action.HOLD,
                    reason=f"order size {krw_amount:.0f} KRW below min {s.min_order_krw}",
                )
            return Decision(Action.BUY, reason="signal=BUY approved", krw_amount=krw_amount)

        # 5) SELL 처리 (전략이 직접 SELL을 내는 경우는 드물지만 지원)
        if signal is Signal.SELL:
            if not has_position:
                return Decision(Action.HOLD, reason="no position to sell")
            return Decision(Action.SELL, reason="signal=SELL approved", volume=ctx.coin_balance)

        # 6) HOLD
        return Decision(Action.HOLD, reason="signal=HOLD")

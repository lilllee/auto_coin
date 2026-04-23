from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd


class Signal(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class MarketSnapshot:
    """전략에 전달되는 시장 스냅샷.

    Attributes:
        df: `enrich_daily`로 보조 컬럼이 채워진 일봉 DataFrame.
            마지막 행이 "오늘"이며 `open`/`target`/`maN`이 채워져 있어야 한다.
        current_price: 현재가 (실거래) 또는 백테스트 시점 가격.
        has_position: 보유 중 여부. True면 신규 진입은 막힌다.
    """

    df: pd.DataFrame
    current_price: float
    has_position: bool


@dataclass(frozen=True)
class PositionSnapshot:
    """백테스트/리뷰용 포지션 상태 스냅샷."""

    entry_price: float
    hold_days: int
    highest_close: float
    highest_high: float


@dataclass(frozen=True)
class ExitDecision:
    """전략 정의형 청산 결정."""

    reason: str
    exit_price: float | None = None


class Strategy(ABC):
    """전략 인터페이스.

    구현체는 순수 함수처럼 동작해야 한다 — 주문/네트워크/로깅/시간을 직접 호출하지 않는다.
    동일한 입력에는 동일한 출력을 보장해야 백테스트와 실거래가 일치한다.
    """

    name: str = "abstract"

    @abstractmethod
    def generate_signal(self, snap: MarketSnapshot) -> Signal:
        ...

    def generate_exit(
        self,
        snap: MarketSnapshot,
        position: PositionSnapshot,
    ) -> ExitDecision | None:
        """보유 포지션의 전략 정의형 청산 조건.

        기본 구현은 아무 것도 하지 않는다. 기존 전략은 이 메서드를
        구현하지 않아도 동작한다.
        """
        return None

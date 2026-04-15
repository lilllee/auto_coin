"""실시간 전략 상태판 서비스.

종목별로 현재 전략 신호 상태와 이유를 계산한다.
실제 API 호출(업비트 시세)이 필요하므로, 호출 빈도에 주의.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any

from loguru import logger

from auto_coin.data.candles import fetch_daily, recommended_history_days
from auto_coin.exchange.upbit_client import UpbitClient, UpbitError
from auto_coin.review.reasons import derive_review_reason
from auto_coin.strategy import STRATEGY_LABELS, create_strategy
from auto_coin.strategy.base import MarketSnapshot, Signal


def _float_or_none(value: Any) -> float | None:
    """값을 float로 변환하되, None/NaN/inf면 None을 반환한다."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if isfinite(num) else None


@dataclass(frozen=True)
class TickerSignalState:
    """종목 1개의 현재 전략 상태."""

    ticker: str
    signal: str  # "buy", "sell", "hold"
    reason: str  # 사람이 읽을 수 있는 이유
    status: str  # "buyable", "waiting", "blocked", "holding"
    status_label: str  # UI 표시용 한국어
    has_position: bool
    current_price: float | None
    indicators: dict[str, float | None] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SignalBoardResult:
    """전체 상태판 결과."""

    strategy_name: str
    strategy_label: str
    regime: str  # "risk-on", "risk-off", "unknown"
    regime_reason: str
    tickers: list[TickerSignalState]
    slot_used: int
    slot_max: int
    kill_switch: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "strategy_label": self.strategy_label,
            "regime": self.regime,
            "regime_reason": self.regime_reason,
            "tickers": [t.to_dict() for t in self.tickers],
            "slot_used": self.slot_used,
            "slot_max": self.slot_max,
            "kill_switch": self.kill_switch,
        }


def compute_signal_board(
    client: UpbitClient,
    *,
    strategy_name: str,
    strategy_params: dict | None = None,
    tickers: list[str],
    position_tickers: set[str],
    ma_window: int = 5,
    k: float = 0.5,
    slot_used: int = 0,
    slot_max: int = 3,
    kill_switch: bool = False,
) -> SignalBoardResult:
    """모든 종목의 현재 전략 상태를 계산한다.

    Args:
        client: 업비트 API 클라이언트 (공개 엔드포인트라 인증 불필요하지만 throttle 이점).
        strategy_name: 전략 이름 (STRATEGY_REGISTRY 키).
        strategy_params: 전략 파라미터 dict. None이면 기본값 사용.
        tickers: 조회할 종목 리스트 (예: ["KRW-BTC", "KRW-ETH"]).
        position_tickers: 현재 보유 중인 종목 set.
        ma_window: 기본 MA 창 크기 (fetch_daily에 전달).
        k: 변동성 돌파 계수 (fetch_daily에 전달).
        slot_used: 현재 사용 중인 슬롯 수.
        slot_max: 최대 동시 보유 종목 수.
        kill_switch: True면 신규 진입 전면 차단.

    Returns:
        전체 종목 상태가 담긴 SignalBoardResult.
    """
    params = strategy_params or {}
    strategy = create_strategy(strategy_name, params)
    history_days = recommended_history_days(strategy_name, params, ma_window=ma_window)

    ticker_states: list[TickerSignalState] = []
    regime = "unknown"
    regime_reason = ""

    for ticker in tickers:
        has_position = ticker in position_tickers
        try:
            df = fetch_daily(
                client,
                ticker,
                count=history_days,
                ma_window=ma_window,
                k=k,
                strategy_name=strategy_name,
                strategy_params=params,
            )
            if df is None or df.empty:
                ticker_states.append(
                    TickerSignalState(
                        ticker=ticker,
                        signal="hold",
                        reason="데이터 없음",
                        status="blocked",
                        status_label="데이터 없음",
                        has_position=has_position,
                        current_price=None,
                        error="no candle data",
                    )
                )
                continue

            last = df.iloc[-1]
            price = _float_or_none(last.get("close"))
            if price is None or price <= 0:
                ticker_states.append(
                    TickerSignalState(
                        ticker=ticker,
                        signal="hold",
                        reason="유효하지 않은 가격",
                        status="blocked",
                        status_label="가격 오류",
                        has_position=has_position,
                        current_price=None,
                        error="invalid price",
                    )
                )
                continue

            snap = MarketSnapshot(
                df=df,
                current_price=price,
                has_position=has_position,
            )
            signal = strategy.generate_signal(snap)
            reason = derive_review_reason(
                strategy_name,
                strategy,
                last,
                current_price=price,
                has_position=has_position,
                signal=signal,
            )

            # 상태 판단
            if has_position:
                status = "holding"
                status_label = "보유 중"
            elif kill_switch:
                status = "blocked"
                status_label = "Kill-switch ON"
            elif slot_used >= slot_max:
                status = "blocked"
                status_label = "슬롯 가득"
            elif signal is Signal.BUY:
                status = "buyable"
                status_label = "매수 가능"
            else:
                status = "waiting"
                status_label = "대기"

            # 레짐 판단 (첫 종목 기준, SMA 계열 전략만)
            if regime == "unknown" and strategy_name in (
                "sma200_ema_adx_composite",
                "sma200_regime",
            ):
                sma_attr = getattr(
                    strategy,
                    "sma_window",
                    getattr(strategy, "ma_window", 200),
                )
                sma_col = f"sma{sma_attr}"
                sma_val = _float_or_none(last.get(sma_col))
                if sma_val is not None:
                    if price >= sma_val:
                        regime = "risk-on"
                        regime_reason = f"{ticker}: price >= {sma_col}"
                    else:
                        regime = "risk-off"
                        regime_reason = f"{ticker}: price < {sma_col}"

            indicators: dict[str, float | None] = {"close": price}

            ticker_states.append(
                TickerSignalState(
                    ticker=ticker,
                    signal=signal.value,
                    reason=reason,
                    status=status,
                    status_label=status_label,
                    has_position=has_position,
                    current_price=price,
                    indicators=indicators,
                )
            )

        except UpbitError as exc:
            logger.warning("signal board: {} upbit error: {}", ticker, exc)
            ticker_states.append(
                TickerSignalState(
                    ticker=ticker,
                    signal="hold",
                    reason=f"API 오류: {exc}",
                    status="blocked",
                    status_label="API 오류",
                    has_position=has_position,
                    current_price=None,
                    error=str(exc),
                )
            )
        except Exception as exc:
            logger.warning("signal board: {} error: {}", ticker, exc)
            ticker_states.append(
                TickerSignalState(
                    ticker=ticker,
                    signal="hold",
                    reason=f"오류: {exc}",
                    status="blocked",
                    status_label="오류",
                    has_position=has_position,
                    current_price=None,
                    error=str(exc),
                )
            )

    if regime == "unknown":
        regime_reason = "레짐 판단 불가 (SMA 미사용 전략)"

    return SignalBoardResult(
        strategy_name=strategy_name,
        strategy_label=STRATEGY_LABELS.get(strategy_name, strategy_name),
        regime=regime,
        regime_reason=regime_reason,
        tickers=ticker_states,
        slot_used=slot_used,
        slot_max=slot_max,
        kill_switch=kill_switch,
    )

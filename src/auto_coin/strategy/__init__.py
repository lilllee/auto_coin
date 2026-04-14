"""전략 레지스트리 및 팩토리.

이름 → 클래스 매핑으로 런타임에 전략 인스턴스를 생성한다.
새 전략 추가 시 이 모듈의 ``STRATEGY_REGISTRY``에 등록하면 된다.
"""

from __future__ import annotations

from auto_coin.strategy.atr_channel_breakout import AtrChannelBreakoutStrategy
from auto_coin.strategy.base import Strategy
from auto_coin.strategy.sma200_regime import Sma200RegimeStrategy
from auto_coin.strategy.volatility_breakout import VolatilityBreakout

# Registry: name → class
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "volatility_breakout": VolatilityBreakout,
    "sma200_regime": Sma200RegimeStrategy,
    "atr_channel_breakout": AtrChannelBreakoutStrategy,
}

# UI-friendly metadata for each strategy's parameters
STRATEGY_PARAMS: dict[str, list[dict]] = {
    "volatility_breakout": [
        {
            "name": "k",
            "label": "K (변동성 돌파 계수)",
            "type": "number",
            "step": "0.01",
            "min": "0.1",
            "max": "1.0",
            "default": 0.5,
            "hint": "target = 오늘 시가 + 전일 range x K",
        },
        {
            "name": "ma_window",
            "label": "MA 필터 창 (일)",
            "type": "number",
            "step": "1",
            "min": "1",
            "max": "200",
            "default": 5,
            "hint": "종가 N일 이평선 위일 때만 진입",
        },
        {
            "name": "require_ma_filter",
            "label": "MA 필터 사용",
            "type": "checkbox",
            "default": True,
            "hint": "MA 필터 비활성화 시 돌파만으로 진입",
        },
    ],
    "sma200_regime": [
        {
            "name": "ma_window",
            "label": "SMA 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "500",
            "default": 200,
            "hint": "기본 200일. 종가의 N일 단순이동평균",
        },
        {
            "name": "buffer_pct",
            "label": "진입 완충 (%)",
            "type": "number",
            "step": "0.001",
            "min": "0",
            "max": "0.1",
            "default": 0.0,
            "hint": "SMA 위 N% 이상일 때만 진입. 0이면 비활성",
        },
        {
            "name": "allow_sell_signal",
            "label": "SMA 하향 이탈 시 SELL",
            "type": "checkbox",
            "default": False,
            "hint": "활성화하면 보유 중 SMA 아래로 내려갈 때 매도 시그널 생성",
        },
    ],
    "atr_channel_breakout": [
        {
            "name": "atr_window",
            "label": "ATR 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "100",
            "default": 14,
            "hint": "Average True Range 계산 기간. 기본 14일",
        },
        {
            "name": "channel_multiplier",
            "label": "채널 배수",
            "type": "number",
            "step": "0.1",
            "min": "0.1",
            "max": "5.0",
            "default": 1.0,
            "hint": "upper_channel = low + ATR × 배수. 기본 1.0",
        },
        {
            "name": "allow_sell_signal",
            "label": "하향 채널 이탈 시 SELL",
            "type": "checkbox",
            "default": False,
            "hint": "활성화하면 lower_channel 아래로 내려갈 때 매도 시그널",
        },
    ],
}

# Human-readable names
STRATEGY_LABELS: dict[str, str] = {
    "volatility_breakout": "변동성 돌파 (Larry Williams)",
    "sma200_regime": "SMA200 추세 필터",
    "atr_channel_breakout": "ATR 채널 돌파",
}


def create_strategy(name: str, params: dict | None = None) -> Strategy:
    """이름과 파라미터로 전략 인스턴스 생성."""
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"unknown strategy: {name!r}. available: {list(STRATEGY_REGISTRY)}"
        )
    if params is None:
        params = {}
    return cls(**params)


def get_strategy_names() -> list[str]:
    """등록된 전략 이름 목록."""
    return list(STRATEGY_REGISTRY.keys())

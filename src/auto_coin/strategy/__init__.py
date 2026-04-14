"""전략 레지스트리 및 팩토리.

이름 → 클래스 매핑으로 런타임에 전략 인스턴스를 생성한다.
새 전략 추가 시 이 모듈의 ``STRATEGY_REGISTRY``에 등록하면 된다.
"""

from __future__ import annotations

from auto_coin.strategy.ad_turtle import AdTurtleStrategy
from auto_coin.strategy.atr_channel_breakout import AtrChannelBreakoutStrategy
from auto_coin.strategy.base import Strategy
from auto_coin.strategy.ema_adx_atr_trend import EmaAdxAtrTrendStrategy
from auto_coin.strategy.sma200_regime import Sma200RegimeStrategy
from auto_coin.strategy.volatility_breakout import VolatilityBreakout

# Registry: name → class
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "volatility_breakout": VolatilityBreakout,
    "sma200_regime": Sma200RegimeStrategy,
    "atr_channel_breakout": AtrChannelBreakoutStrategy,
    "ema_adx_atr_trend": EmaAdxAtrTrendStrategy,
    "ad_turtle": AdTurtleStrategy,
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
    "ema_adx_atr_trend": [
        {
            "name": "ema_fast_window",
            "label": "EMA 단기 (일)",
            "type": "number",
            "min": "1",
            "max": "200",
            "default": 27,
            "hint": "단기 지수이동평균 기간. 기본 27일",
        },
        {
            "name": "ema_slow_window",
            "label": "EMA 장기 (일)",
            "type": "number",
            "min": "2",
            "max": "500",
            "default": 125,
            "hint": "장기 지수이동평균 기간. 기본 125일 (단기보다 커야 함)",
        },
        {
            "name": "adx_window",
            "label": "ADX 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "200",
            "default": 90,
            "hint": "추세 강도 지표 기간. 기본 90일",
        },
        {
            "name": "adx_threshold",
            "label": "ADX 임계값",
            "type": "number",
            "step": "0.1",
            "min": "0",
            "max": "100",
            "default": 14.0,
            "hint": "이 값 이상이면 추세 존재로 판단. 기본 14",
        },
        {
            "name": "allow_sell_signal",
            "label": "EMA 데드크로스 시 SELL",
            "type": "checkbox",
            "default": False,
            "hint": "활성화하면 EMA 단기 < 장기일 때 매도 시그널",
        },
    ],
    "ad_turtle": [
        {
            "name": "entry_window",
            "label": "진입 채널 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "200",
            "default": 20,
            "hint": "Donchian 상단 — N일 최고가 돌파 시 진입. 기본 20일",
        },
        {
            "name": "exit_window",
            "label": "청산 채널 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "100",
            "default": 10,
            "hint": "Donchian 하단 — N일 최저가 이탈 시 청산. 진입보다 짧아야 함",
        },
        {
            "name": "allow_sell_signal",
            "label": "Donchian 하단 이탈 시 SELL",
            "type": "checkbox",
            "default": False,
            "hint": "활성화하면 exit_window 최저가 이탈 시 매도 시그널",
        },
    ],
}

# Human-readable names
STRATEGY_LABELS: dict[str, str] = {
    "volatility_breakout": "변동성 돌파 (Larry Williams)",
    "sma200_regime": "SMA200 추세 필터",
    "atr_channel_breakout": "ATR 채널 돌파",
    "ema_adx_atr_trend": "EMA+ADX 추세추종",
    "ad_turtle": "AdTurtle (개선형 Turtle)",
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

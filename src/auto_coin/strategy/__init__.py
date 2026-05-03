"""전략 레지스트리 및 팩토리.

이름 → 클래스 매핑으로 런타임에 전략 인스턴스를 생성한다.
새 전략 추가 시 이 모듈의 ``STRATEGY_REGISTRY``에 등록하면 된다.
"""

from __future__ import annotations

from auto_coin.strategy.ad_turtle import AdTurtleStrategy
from auto_coin.strategy.atr_channel_breakout import AtrChannelBreakoutStrategy
from auto_coin.strategy.base import Strategy
from auto_coin.strategy.ema_adx_atr_trend import EmaAdxAtrTrendStrategy
from auto_coin.strategy.rcdb import RcdbStrategy
from auto_coin.strategy.rcdb_v2 import RcdbV2Strategy
from auto_coin.strategy.regime_pullback_continuation_30m import (
    RegimePullbackContinuation30mStrategy,
)
from auto_coin.strategy.regime_reclaim_1h import RegimeReclaim1HStrategy
from auto_coin.strategy.regime_reclaim_30m import RegimeReclaim30mStrategy
from auto_coin.strategy.regime_relative_breakout_30m import RegimeRelativeBreakout30mStrategy
from auto_coin.strategy.sma200_ema_adx_composite import Sma200EmaAdxCompositeStrategy
from auto_coin.strategy.sma200_regime import Sma200RegimeStrategy
from auto_coin.strategy.volatility_breakout import VolatilityBreakout
from auto_coin.strategy.vwap_ema_pullback import VwapEmaPullbackStrategy

# Registry: name → class
STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "volatility_breakout": VolatilityBreakout,
    "sma200_regime": Sma200RegimeStrategy,
    "atr_channel_breakout": AtrChannelBreakoutStrategy,
    "ema_adx_atr_trend": EmaAdxAtrTrendStrategy,
    "ad_turtle": AdTurtleStrategy,
    "sma200_ema_adx_composite": Sma200EmaAdxCompositeStrategy,
    "rcdb": RcdbStrategy,
    "rcdb_v2": RcdbV2Strategy,
    "regime_reclaim_1h": RegimeReclaim1HStrategy,
    "regime_reclaim_30m": RegimeReclaim30mStrategy,
    "regime_pullback_continuation_30m": RegimePullbackContinuation30mStrategy,
    "regime_relative_breakout_30m": RegimeRelativeBreakout30mStrategy,
    "vwap_ema_pullback": VwapEmaPullbackStrategy,
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
            "name": "atr_window",
            "label": "ATR 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "100",
            "default": 14,
            "hint": "외부 리스크 관리용 ATR 컬럼 기간. 기본 14일",
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
    "sma200_ema_adx_composite": [
        {
            "name": "sma_window",
            "label": "SMA 레짐 필터 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "500",
            "default": 200,
            "hint": "이 SMA 아래면 risk-off (진입 차단 + 보유 청산). 기본 200일",
        },
        {
            "name": "ema_fast_window",
            "label": "EMA 단기 (일)",
            "type": "number",
            "min": "1",
            "max": "200",
            "default": 27,
            "hint": "단기 지수이동평균. 기본 27일",
        },
        {
            "name": "ema_slow_window",
            "label": "EMA 장기 (일)",
            "type": "number",
            "min": "2",
            "max": "500",
            "default": 125,
            "hint": "장기 지수이동평균. 기본 125일 (단기보다 커야 함)",
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
    ],
    "rcdb": [
        {
            "name": "regime_ticker",
            "label": "Regime 기준 티커",
            "type": "text",
            "default": "KRW-BTC",
            "hint": "risk-on / risk-off 판단에 사용할 기준 자산",
        },
        {
            "name": "regime_ma_window",
            "label": "Regime SMA 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "300",
            "default": 120,
            "hint": "기준 자산 종가의 SMA 위일 때만 진입",
        },
        {
            "name": "dip_lookback_days",
            "label": "Dip 측정 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "30",
            "default": 5,
            "hint": "N일 누적 수익률이 dip threshold 이하일 때만 진입",
        },
        {
            "name": "dip_threshold_pct",
            "label": "Dip 임계값",
            "type": "number",
            "step": "0.01",
            "min": "-0.5",
            "max": "-0.01",
            "default": -0.08,
            "hint": "예: -0.08 = 최근 N일 -8% 이상 하락",
        },
        {
            "name": "rsi_window",
            "label": "RSI 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "50",
            "default": 14,
            "hint": "과매도 확인용 RSI 기간",
        },
        {
            "name": "rsi_threshold",
            "label": "RSI 임계값",
            "type": "number",
            "step": "0.1",
            "min": "1",
            "max": "99",
            "default": 30,
            "hint": "RSI가 이 값 미만일 때만 진입",
        },
        {
            "name": "max_hold_days",
            "label": "최대 보유일",
            "type": "number",
            "min": "1",
            "max": "30",
            "default": 7,
            "hint": "반등이 지연되면 N일 후 fallback 청산",
        },
        {
            "name": "atr_window",
            "label": "ATR 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "50",
            "default": 14,
            "hint": "ATR trailing 계산 기간",
        },
        {
            "name": "atr_trailing_mult",
            "label": "ATR trailing 배수",
            "type": "number",
            "step": "0.1",
            "min": "0.5",
            "max": "10.0",
            "default": 2.5,
            "hint": "highest_close - ATR × 배수 아래면 청산",
        },
    ],
    "rcdb_v2": [
        {
            "name": "regime_ticker",
            "label": "Regime 기준 티커",
            "type": "text",
            "default": "KRW-BTC",
            "hint": "risk-on / risk-off 판단에 사용할 기준 자산",
        },
        {
            "name": "regime_ma_window",
            "label": "Regime SMA 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "300",
            "default": 120,
            "hint": "기준 자산 종가의 SMA 위일 때만 진입",
        },
        {
            "name": "dip_lookback_days",
            "label": "Dip 측정 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "30",
            "default": 5,
            "hint": "N일 누적 수익률 기준 dip 점수 계산",
        },
        {
            "name": "vol_window",
            "label": "변동성 창 (일)",
            "type": "number",
            "min": "2",
            "max": "60",
            "default": 20,
            "hint": "dip 점수 정규화에 사용할 realized volatility 창",
        },
        {
            "name": "dip_z_threshold",
            "label": "Dip Z 임계값",
            "type": "number",
            "step": "0.05",
            "min": "-5.0",
            "max": "-0.1",
            "default": -1.75,
            "hint": "정규화 dip 점수가 이 값 이하일 때만 setup",
        },
        {
            "name": "rsi_window",
            "label": "RSI 기간 (일)",
            "type": "number",
            "min": "2",
            "max": "50",
            "default": 14,
            "hint": "과매도 확인용 RSI 기간",
        },
        {
            "name": "rsi_threshold",
            "label": "RSI 임계값",
            "type": "number",
            "step": "0.1",
            "min": "1",
            "max": "99",
            "default": 35,
            "hint": "RSI가 이 값 이하일 때만 진입 가능",
        },
        {
            "name": "reversal_ema_window",
            "label": "반전 EMA 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "30",
            "default": 5,
            "hint": "현재 종가가 이전 EMA 위로 복귀해야 진입",
        },
        {
            "name": "max_hold_days",
            "label": "최대 보유일",
            "type": "number",
            "min": "1",
            "max": "20",
            "default": 5,
            "hint": "reversion 미완료 시 safety fallback 청산",
        },
        {
            "name": "atr_window",
            "label": "ATR 기간 (일)",
            "type": "number",
            "min": "1",
            "max": "50",
            "default": 14,
            "hint": "trailing 계산용 ATR 기간",
        },
        {
            "name": "atr_trailing_mult",
            "label": "ATR trailing 배수",
            "type": "number",
            "step": "0.1",
            "min": "0.5",
            "max": "10.0",
            "default": 2.0,
            "hint": "highest_high - ATR × 배수 아래면 보호성 청산",
        },
    ],
    "regime_reclaim_1h": [
        {
            "name": "regime_ticker",
            "label": "Daily regime 기준 티커",
            "type": "text",
            "default": "KRW-BTC",
            "hint": "상위 daily regime 판단에 사용할 기준 자산",
        },
        {
            "name": "daily_regime_ma_window",
            "label": "Daily regime SMA (일)",
            "type": "number",
            "min": "2",
            "max": "300",
            "default": 120,
            "hint": "daily close가 이 SMA 위일 때만 신규 진입",
        },
        {
            "name": "dip_lookback_bars",
            "label": "1H pullback 기간 (bars)",
            "type": "number",
            "min": "1",
            "max": "72",
            "default": 8,
            "hint": "최근 N시간 pullback 수익률 기준",
        },
        {
            "name": "pullback_threshold_pct",
            "label": "1H pullback 임계값",
            "type": "number",
            "step": "0.005",
            "min": "-0.20",
            "max": "-0.005",
            "default": -0.025,
            "hint": "예: -0.025 = 최근 N시간 -2.5% 이상 눌림",
        },
        {
            "name": "rsi_window",
            "label": "1H RSI 기간",
            "type": "number",
            "min": "2",
            "max": "50",
            "default": 14,
            "hint": "1H 과매도 확인용 RSI 기간",
        },
        {
            "name": "rsi_threshold",
            "label": "1H RSI 임계값",
            "type": "number",
            "step": "0.1",
            "min": "1",
            "max": "99",
            "default": 35,
            "hint": "RSI가 이 값 이하일 때만 reclaim 진입 검토",
        },
        {
            "name": "reclaim_ema_window",
            "label": "1H reclaim EMA 기간",
            "type": "number",
            "min": "1",
            "max": "30",
            "default": 6,
            "hint": "close > prev_close and close > EMA 일 때 reclaim 확인",
        },
        {
            "name": "max_hold_bars",
            "label": "최대 보유 bars",
            "type": "number",
            "min": "1",
            "max": "240",
            "default": 36,
            "hint": "reversion 실패 시 safety only 시간 청산",
        },
        {
            "name": "atr_window",
            "label": "1H ATR 기간",
            "type": "number",
            "min": "1",
            "max": "100",
            "default": 14,
            "hint": "보호성 ATR trailing 계산 기간",
        },
          {
              "name": "atr_trailing_mult",
              "label": "ATR trailing 배수",
              "type": "number",
             "step": "0.1",
             "min": "0.5",
             "max": "10.0",
             "default": 2.0,
             "hint": "highest_high - ATR × 배수 아래면 trailing exit",
          },
     ],
    "regime_reclaim_30m": [
        {
            "name": "regime_ticker",
            "label": "Daily regime 기준 티커",
            "type": "text",
            "default": "KRW-BTC",
            "hint": "상위 daily regime 판단에 사용할 기준 자산",
        },
        {
            "name": "daily_regime_ma_window",
            "label": "Daily regime SMA (일)",
            "type": "number",
            "min": "2",
            "max": "300",
            "default": 100,
            "hint": "daily close가 이 SMA 위일 때만 신규 진입. 기본 100일",
        },
         {
             "name": "hourly_pullback_bars",
             "label": "1H pullback 기간 (bars)",
             "type": "number",
             "min": "1",
             "max": "72",
             "default": 8,
             "hint": "1H timeframe 기준 N시간 pullback 수익률 확인",
         },
         {
             "name": "hourly_pullback_threshold_pct",
             "label": "1H pullback 임계값",
             "type": "number",
             "step": "0.005",
             "min": "-0.20",
             "max": "-0.005",
             "default": -0.025,
             "hint": "1H pullback 수익률이 이 값 이하일 때 setup",
         },
         {
             "name": "setup_rsi_window",
             "label": "1H RSI 기간",
             "type": "number",
             "min": "2",
             "max": "50",
             "default": 14,
             "hint": "1H 과매도 확인용 RSI 기간",
         },
         {
             "name": "setup_rsi_threshold",
             "label": "1H RSI 임계값",
             "type": "number",
             "step": "0.1",
             "min": "1",
             "max": "99",
             "default": 35,
             "hint": "1H RSI 가 이 값 이하일 때만 setup",
         },
         {
             "name": "trigger_reclaim_ema_window",
             "label": "30m reclaim EMA 기간",
             "type": "number",
             "min": "1",
             "max": "30",
             "default": 6,
             "hint": "30m close > EMA 일 때 reclaim 확인",
         },
         {
             "name": "trigger_rsi_rebound_threshold",
             "label": "30m RSI 반등 임계값",
             "type": "number",
             "step": "0.1",
             "min": "1",
             "max": "99",
             "default": 30,
             "hint": "Trigger B: RSI 가 이 값 이상 + 전 봉보다 3 이상 상승",
         },
         {
             "name": "max_hold_bars_30m",
             "label": "최대 보유 bars (30분)",
             "type": "number",
             "min": "1",
             "max": "240",
             "default": 36,
             "hint": "reversion 실패 시 safety only 시간 청산 (36 bars = 18시간)",
         },
         {
             "name": "atr_window",
             "label": "30m ATR 기간",
             "type": "number",
             "min": "1",
             "max": "100",
             "default": 14,
             "hint": "trailing 계산용 ATR 기간",
         },
         {
             "name": "atr_trailing_mult",
             "label": "ATR trailing 배수",
             "type": "number",
            "step": "0.1",
            "min": "0.5",
            "max": "10.0",
            "default": 2.0,
            "hint": "highest_high - ATR × 배수 아래면 trailing exit",
        },
        {
            "name": "reversion_sma_window_override",
            "label": "Reversion SMA 기간 override",
            "type": "number",
            "min": "1",
            "max": "96",
            "default": None,
            "hint": "None이면 hourly_pullback_bars 사용. v1.1 후보: 12/24/36/48 bars",
        },
        {
            "name": "min_hold_bars_30m",
            "label": "최소 보유 bars (reversion)",
            "type": "number",
            "min": "0",
            "max": "20",
            "default": 0,
            "hint": "진입 후 최소 N bars 동안 reversion_exit만 금지. 0 = 비활성. v1.1 후보: 2~4",
        },
        {
            "name": "reversion_min_profit_pct",
            "label": "Reversion 최소 이익률",
            "type": "number",
            "step": "0.001",
            "min": "0",
            "max": "0.05",
            "default": 0.0,
            "hint": "ratio 단위. 0.003 = 0.3%, 0.005 = 0.5%, 0.008 = 0.8%",
        },
        {
            "name": "reversion_confirmation_type",
            "label": "Reversion 확인 유형",
            "type": "select",
            "options": ["none", "rsi", "consecutive"],
            "default": "none",
            "hint": "none=SMA touch, rsi=SMA touch+RSI>=50, consecutive=현재/전 bar SMA 위",
        },
    ],

    "vwap_ema_pullback": [
        {"name": "ema_period", "label": "EMA 기간", "type": "number", "min": "1", "max": "100", "default": 9, "hint": "눌림목/청산 기준 EMA. 기본 9"},
        {"name": "vwap_period", "label": "VWAP rolling 기간", "type": "number", "min": "2", "max": "500", "default": 48, "hint": "HLC3×volume rolling VWAP 기간"},
        {"name": "ema_touch_tolerance", "label": "EMA touch tolerance", "type": "number", "step": "0.001", "min": "0", "max": "0.05", "default": 0.003, "hint": "low <= EMA×(1+tolerance)면 눌림으로 인정"},
        {"name": "sideways_lookback", "label": "횡보 필터 lookback", "type": "number", "min": "2", "max": "100", "default": 12, "hint": "VWAP 교차/EMA slope 판단 바 수"},
        {"name": "max_vwap_cross_count", "label": "최대 VWAP 교차 수", "type": "number", "min": "0", "max": "50", "default": 3, "hint": "초과 시 횡보장으로 보고 진입 차단"},
        {"name": "min_ema_slope_ratio", "label": "최소 EMA slope ratio", "type": "number", "step": "0.0001", "min": "0", "max": "0.1", "default": 0.001, "hint": "절대 기울기 비율이 이보다 작으면 횡보장"},
        {"name": "require_bullish_candle", "label": "양봉 확인 필요", "type": "checkbox", "default": True, "hint": "close > open 조건 요구"},
        {"name": "use_volume_profile", "label": "Volume Profile 사용", "type": "checkbox", "default": False, "hint": "Phase 1 기본 OFF. 정확/근사 Profile은 후속 단계"},
        {"name": "exit_mode", "label": "Exit mode", "type": "text", "default": "close_below_ema", "hint": "close_below_ema/body_below_ema/confirm_close_below_ema/atr_buffer_exit"},
        {"name": "exit_confirm_bars", "label": "Exit confirm bars", "type": "number", "min": "1", "max": "10", "default": 2, "hint": "confirm_close_below_ema 연속 확인봉 수"},
        {"name": "exit_atr_multiplier", "label": "Exit ATR multiplier", "type": "number", "step": "0.1", "min": "0", "max": "5", "default": 0.3, "hint": "atr_buffer_exit: EMA - ATR×배수 아래에서 청산"},
        {"name": "atr_window", "label": "ATR window", "type": "number", "min": "1", "max": "100", "default": 14, "hint": "ATR buffer exit 계산 기간"},
        {"name": "volume_profile_lookback", "label": "Volume Profile lookback", "type": "number", "min": "1", "max": "500", "default": 48, "hint": "후속 Phase용 예약 파라미터"},
        {"name": "volume_profile_bin_count", "label": "Volume Profile bins", "type": "number", "min": "1", "max": "200", "default": 24, "hint": "후속 Phase용 예약 파라미터"},
        {"name": "volume_gap_threshold", "label": "Volume gap threshold", "type": "number", "step": "0.05", "min": "0", "max": "1", "default": 0.3, "hint": "후속 Phase용 예약 파라미터"},
    ],
    "regime_relative_breakout_30m": [
        {"name": "regime_ticker", "label": "Daily regime 기준 티커", "type": "text", "default": "KRW-BTC", "hint": "BTC daily regime 참조 자산"},
        {"name": "daily_regime_ma_window", "label": "Daily regime SMA (일)", "type": "number", "min": "2", "max": "300", "default": 100, "hint": "BTC close > 전일 기준 SMA 일 때만 진입"},
        {"name": "hourly_ema_fast", "label": "1H EMA fast", "type": "number", "min": "1", "max": "100", "default": 20, "hint": "1H 추세 fast EMA"},
        {"name": "hourly_ema_slow", "label": "1H EMA slow", "type": "number", "min": "2", "max": "200", "default": 60, "hint": "1H 추세 slow EMA (fast보다 커야 함)"},
        {"name": "hourly_slope_lookback", "label": "1H EMA slope lookback", "type": "number", "min": "1", "max": "20", "default": 3, "hint": "fast EMA - fast EMA.shift(N) >= 0 요구"},
        {"name": "rs_24h_bars_30m", "label": "24h RS 기간 (30m bars)", "type": "number", "min": "1", "max": "240", "default": 48, "hint": "24시간 = 48 × 30m"},
        {"name": "rs_7d_bars_30m", "label": "7d RS 기간 (30m bars)", "type": "number", "min": "2", "max": "720", "default": 336, "hint": "7일 = 336 × 30m"},
        {"name": "breakout_lookback_30m", "label": "30m prior_high lookback", "type": "number", "min": "1", "max": "48", "default": 6, "hint": "close > 전 N개 high 최대값"},
        {"name": "volume_window_30m", "label": "30m volume MA 윈도우", "type": "number", "min": "1", "max": "96", "default": 20, "hint": "volume > ma × 배수"},
        {"name": "volume_mult", "label": "Volume multiplier", "type": "number", "step": "0.05", "min": "0.5", "max": "5.0", "default": 1.2, "hint": "기본 1.2배 이상 거래량"},
        {"name": "close_location_min", "label": "CLV 최소값", "type": "number", "step": "0.01", "min": "0.0", "max": "1.0", "default": 0.55, "hint": "캔들 상단 55% 이상 마감"},
        {"name": "atr_window", "label": "ATR window", "type": "number", "min": "1", "max": "100", "default": 14, "hint": "ATR stop/trailing 계산"},
        {"name": "initial_stop_atr_mult", "label": "Initial stop ATR 배수", "type": "number", "step": "0.1", "min": "0.5", "max": "10.0", "default": 2.0, "hint": "entry - ATR × 배수"},
        {"name": "atr_trailing_mult", "label": "ATR trailing 배수", "type": "number", "step": "0.1", "min": "0.5", "max": "10.0", "default": 3.0, "hint": "highest_high - ATR × 배수"},
        {"name": "trend_exit_confirm_bars", "label": "Trend exit 확인 1H bars", "type": "number", "min": "1", "max": "10", "default": 2, "hint": "1H close < EMA20 연속 N 1H bar 확인"},
        {"name": "max_hold_bars_30m", "label": "Max hold bars (30m)", "type": "number", "min": "1", "max": "240", "default": 48, "hint": "safety-only 시간 청산"},
    ],
    "regime_pullback_continuation_30m": [
        {"name": "regime_ticker", "label": "Daily regime 기준 티커", "type": "text", "default": "KRW-BTC", "hint": "상위 risk-on 판단 기준"},
        {"name": "daily_regime_ma_window", "label": "Daily regime SMA", "type": "number", "min": "2", "max": "300", "default": 100, "hint": "BTC daily close > SMA"},
        {"name": "trend_ema_fast_1h", "label": "1H trend EMA fast", "type": "number", "min": "1", "max": "100", "default": 20, "hint": "1H 추세 fast EMA"},
        {"name": "trend_ema_slow_1h", "label": "1H trend EMA slow", "type": "number", "min": "2", "max": "200", "default": 60, "hint": "1H 추세 slow EMA"},
        {"name": "pullback_lookback_1h", "label": "1H pullback bars", "type": "number", "min": "1", "max": "48", "default": 8, "hint": "눌림 수익률 측정 기간"},
        {"name": "pullback_min_pct", "label": "Pullback deep bound", "type": "number", "step": "0.001", "min": "-0.20", "max": "-0.001", "default": -0.045, "hint": "이보다 깊으면 추세 훼손으로 간주"},
        {"name": "pullback_max_pct", "label": "Pullback shallow bound", "type": "number", "step": "0.001", "min": "-0.10", "max": "-0.001", "default": -0.012, "hint": "이보다 얕으면 기회 부족"},
        {"name": "setup_rsi_recovery", "label": "1H RSI recovery", "type": "number", "step": "0.1", "min": "1", "max": "99", "default": 40.0, "hint": "눌림 후 RSI 회복 확인"},
        {"name": "trigger_required_votes", "label": "30m trigger votes", "type": "number", "min": "1", "max": "5", "default": 2, "hint": "30m 재가속 조건 최소 통과 수"},
        {"name": "trigger_breakout_lookback_30m", "label": "30m breakout lookback", "type": "number", "min": "1", "max": "48", "default": 6, "hint": "최근 고점 돌파 확인"},
        {"name": "trigger_volume_mult", "label": "30m volume multiplier", "type": "number", "step": "0.05", "min": "0.1", "max": "5.0", "default": 1.1, "hint": "평균 거래량 대비 trigger volume"},
        {"name": "atr_window", "label": "ATR window", "type": "number", "min": "1", "max": "100", "default": 14, "hint": "stop/trailing 계산"},
        {"name": "initial_stop_atr_mult", "label": "Initial stop ATR", "type": "number", "step": "0.1", "min": "0.5", "max": "10.0", "default": 1.5, "hint": "진입가 - ATR×배수"},
        {"name": "atr_trailing_mult", "label": "ATR trailing", "type": "number", "step": "0.1", "min": "0.5", "max": "10.0", "default": 2.5, "hint": "highest_high - ATR×배수"},
        {"name": "max_hold_bars_30m", "label": "Max hold bars", "type": "number", "min": "1", "max": "240", "default": 96, "hint": "safety only 최대 보유"},
    ],
}

# Human-readable names
STRATEGY_LABELS: dict[str, str] = {
    "volatility_breakout": "변동성 돌파 (Larry Williams)",
    "sma200_regime": "SMA200 추세 필터",
    "atr_channel_breakout": "ATR 채널 돌파",
    "ema_adx_atr_trend": "EMA+ADX 추세추종",
    "ad_turtle": "AdTurtle (개선형 Turtle)",
    "sma200_ema_adx_composite": "SMA200 필터 + EMA+ADX 추세추종 (권장)",
    "rcdb": "RCDB (Regime-Conditioned Dip Buy)",
    "rcdb_v2": "RCDB v2 (Vol-normalized Dip + Reversal)",
    "regime_reclaim_1h": "Daily Regime + 1H Reclaim Mean Reversion",
    "regime_reclaim_30m": "Daily Regime + 1H Setup + 30m Trigger Reclaim",
    "regime_pullback_continuation_30m": "Daily/1H Trend Pullback + 30m Continuation",
    "regime_relative_breakout_30m": "BTC Regime + Alt RS + 1H Trend + 30m Breakout",
    "vwap_ema_pullback": "VWAP + EMA9 눌림목",
}

EXPERIMENTAL_STRATEGIES: set[str] = {
    "rcdb",
    "rcdb_v2",
    "regime_reclaim_1h",
    "regime_reclaim_30m",
    "regime_pullback_continuation_30m",
    "regime_relative_breakout_30m",
    "vwap_ema_pullback",
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


def get_strategy_names(*, include_experimental: bool = False) -> list[str]:
    """등록된 전략 이름 목록."""
    names = list(STRATEGY_REGISTRY.keys())
    if include_experimental:
        return names
    return [name for name in names if name not in EXPERIMENTAL_STRATEGIES]


# 전략별 진입 확인 tick 수. 0이면 즉시 진입 (debounce 없음).
STRATEGY_ENTRY_CONFIRMATION: dict[str, int] = {
    "volatility_breakout": 0,        # 장중 돌파 포착 — 지연 금지
    "atr_channel_breakout": 1,       # 채널 돌파 1회 확인
    "ad_turtle": 1,                  # Donchian 돌파 1회 확인
    "sma200_ema_adx_composite": 0,   # daily_confirm이 debounce를 대체
    "ema_adx_atr_trend": 0,          # daily_confirm이 debounce를 대체
    "sma200_regime": 0,              # daily_confirm이 debounce를 대체
    "rcdb": 0,                       # 일봉 확정 기반 mean reversion
    "rcdb_v2": 0,                    # 일봉 확정 기반 normalized mean reversion
    "regime_reclaim_1h": 0,          # 1H 봉 확정 reclaim 진입
    "regime_reclaim_30m": 0,         # 30m 봉 확정 reclaim 진입
    "regime_pullback_continuation_30m": 0,  # 30m 봉 확정 continuation 진입
    "regime_relative_breakout_30m": 0,      # 30m 봉 확정 breakout 진입
    "vwap_ema_pullback": 0,                 # VWAP/EMA pullback 즉시 판단
}

# 전략별 실행 모드.
# - "intraday": 매 tick BUY 판단 (현재가 반응형)
# - "daily_confirm": 거래일당 1회만 BUY 판단 (일봉 확정 후 첫 tick)
STRATEGY_EXECUTION_MODE: dict[str, str] = {
    "volatility_breakout": "intraday",
    "atr_channel_breakout": "intraday",
    "ad_turtle": "intraday",
    "sma200_ema_adx_composite": "daily_confirm",
    "ema_adx_atr_trend": "daily_confirm",
    "sma200_regime": "daily_confirm",
    "rcdb": "daily_confirm",
    "rcdb_v2": "daily_confirm",
    "regime_reclaim_1h": "intraday",
    "regime_reclaim_30m": "intraday",
    "regime_pullback_continuation_30m": "intraday",
    "regime_relative_breakout_30m": "intraday",
    "vwap_ema_pullback": "intraday",
}

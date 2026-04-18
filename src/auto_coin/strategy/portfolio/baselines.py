"""Portfolio-level baselines — CSMOM 과 무관한 순수 baseline 전략.

CSMOM 의 성과 중 어느 부분이 "cross-sectional momentum selection"이고
어느 부분이 단순 "regime filter 로 bear 회피"인지 분리하기 위한 비교군.

두 가지 제공:
- `regime_equal_weight` : regime ON 이면 universe 동등 가중, OFF 면 cash
- `regime_btc_only`      : regime ON 이면 BTC 100%, OFF 면 cash

둘 다 cross-sectional ranking 없음 — 완전한 baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from auto_coin.backtest.portfolio_runner import PortfolioContext, PortfolioSignal
from auto_coin.strategy.portfolio.csmom import CsmomParams
from auto_coin.strategy.portfolio.csmom import _is_risk_on as _csmom_is_risk_on


@dataclass(frozen=True)
class RegimeBaselineParams:
    """regime-only baseline 파라미터.

    CSMOM 의 regime filter 로직을 그대로 재사용하기 위해 regime_ticker / regime_ma_window
    를 동일 형식으로 받는다. mode 로 두 baseline 중 하나 선택.
    """

    mode: str = "equal_weight"          # "equal_weight" | "btc_only"
    regime_ticker: str = "KRW-BTC"
    regime_ma_window: int = 100
    regime_enabled: bool = True

    def validate(self) -> None:
        if self.mode not in {"equal_weight", "btc_only"}:
            raise ValueError(f"mode must be 'equal_weight' or 'btc_only', got {self.mode!r}")
        if self.regime_ma_window < 2:
            raise ValueError(f"regime_ma_window must be >= 2, got {self.regime_ma_window}")


def _regime_params_adapter(p: RegimeBaselineParams) -> CsmomParams:
    """CsmomParams 의 _is_risk_on 헬퍼를 재사용하기 위한 얇은 어댑터."""
    # lookback_days / top_k 은 _is_risk_on 에서 사용하지 않으므로 아무 valid 값
    return CsmomParams(
        lookback_days=2, top_k=1,
        regime_enabled=p.regime_enabled,
        regime_ticker=p.regime_ticker,
        regime_ma_window=p.regime_ma_window,
    )


def make_regime_baseline_signal(params: RegimeBaselineParams) -> PortfolioSignal:
    params.validate()
    regime_probe = _regime_params_adapter(params)

    def signal(
        candles: dict[str, pd.DataFrame],
        current_date: pd.Timestamp,
        ctx: PortfolioContext,
    ) -> dict[str, float]:
        if not _csmom_is_risk_on(candles, regime_probe):
            return {}
        if params.mode == "btc_only":
            if params.regime_ticker in candles and not candles[params.regime_ticker].empty:
                return {params.regime_ticker: ctx.risk_budget}
            return {}
        # equal_weight
        available = [t for t, df in candles.items() if len(df) > 0]
        if not available:
            return {}
        w = ctx.risk_budget / len(available)
        return {t: w for t in available}

    return signal


def regime_baseline_factory_equal(
    params_dict: dict[str, Any],
) -> tuple[PortfolioSignal, dict[str, Any]]:
    """walk_forward.SignalFactory 호환 — equal_weight 모드 고정."""
    regime_keys = {"regime_ticker", "regime_ma_window", "regime_enabled"}
    regime_args = {k: v for k, v in params_dict.items() if k in regime_keys}
    params = RegimeBaselineParams(mode="equal_weight", **regime_args)

    ctx_overrides: dict[str, Any] = {}
    for key in ("rebal_days", "hold_N", "risk_budget", "active_strategy_group"):
        if key in params_dict:
            ctx_overrides[key] = params_dict[key]
    return make_regime_baseline_signal(params), ctx_overrides


def regime_baseline_factory_btc(
    params_dict: dict[str, Any],
) -> tuple[PortfolioSignal, dict[str, Any]]:
    """walk_forward.SignalFactory 호환 — btc_only 모드 고정."""
    regime_keys = {"regime_ticker", "regime_ma_window", "regime_enabled"}
    regime_args = {k: v for k, v in params_dict.items() if k in regime_keys}
    params = RegimeBaselineParams(mode="btc_only", **regime_args)

    ctx_overrides: dict[str, Any] = {}
    for key in ("rebal_days", "hold_N", "risk_budget", "active_strategy_group"):
        if key in params_dict:
            ctx_overrides[key] = params_dict[key]
    return make_regime_baseline_signal(params), ctx_overrides

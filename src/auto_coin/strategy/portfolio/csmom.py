"""CSMOM — Cross-Sectional Momentum Rotation (v1 minimal).

PLAN_CSMOM §2 의 최소 구현.

전략 개념:
    1. Universe 내 각 자산의 `lookback_days` 수익률을 계산한다.
    2. 상위 `top_k` 종목을 선택한다.
    3. Regime filter: `regime_ticker` (기본 BTC) 의 close > N-day SMA 가 아니면
       전원 flat (risk-off).
    4. `rebal_days` 간격의 rebalance tick 에만 선택을 갱신한다 — 이 cadence 는
       `portfolio_runner.PortfolioContext.rebal_days` 로 제어.
    5. Sizing 은 Top-K 균등분할 × `risk_budget`. vol-scaled 는 v2 이후.

본 모듈은 `portfolio_runner.PortfolioSignal` 프로토콜을 구현한다
(`candles_dict × date × PortfolioContext → dict[ticker, weight]`).

v1 의도적 단순화 (상세는 docs/v4/PLAN_CSMOM.md):
    - 레짐은 "BTC close > SMA(N)" 단일 조건 (slope 없음)
    - Sizing 은 equal-weight (ATR 가중 없음)
    - Catastrophic stop / 개별 exit 없음 — rebalance 로만 청산
    - Survivorship bias 보정 없음 — portfolio_runner 의 universe 교집합에 의존
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from auto_coin.backtest.portfolio_runner import PortfolioContext, PortfolioSignal

# ---------------------------------------------------------------------------
# Params
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CsmomParams:
    """CSMOM 최소 파라미터 세트.

    PortfolioContext 의 일부 값(rebal_days, risk_budget, hold_N) 과 중복되는 부분은
    **Context 가 우선**이다. CsmomParams 는 "signal 내부 로직" 에만 관여한다.
    """

    lookback_days: int = 60
    top_k: int = 3

    # regime filter
    regime_enabled: bool = True
    regime_ticker: str = "KRW-BTC"
    regime_ma_window: int = 100          # BTC close > SMA(N) 이면 risk-on

    def validate(self) -> None:
        if self.lookback_days < 2:
            raise ValueError(f"lookback_days must be >= 2, got {self.lookback_days}")
        if self.top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {self.top_k}")
        if self.regime_ma_window < 2:
            raise ValueError(f"regime_ma_window must be >= 2, got {self.regime_ma_window}")


# ---------------------------------------------------------------------------
# Core logic (pure)
# ---------------------------------------------------------------------------


def _momentum_score(df: pd.DataFrame, lookback_days: int) -> float | None:
    """과거 `lookback_days` close 대비 수익률. 데이터 부족 시 None."""
    if df.empty or len(df) < lookback_days + 1:
        return None
    try:
        today = float(df.iloc[-1]["close"])
        past = float(df.iloc[-lookback_days - 1]["close"])
    except (KeyError, IndexError, ValueError, TypeError):
        return None
    if not math.isfinite(today) or not math.isfinite(past) or past <= 0:
        return None
    return today / past - 1.0


def _is_risk_on(
    candles: dict[str, pd.DataFrame],
    params: CsmomParams,
) -> bool:
    """Regime filter: regime_ticker close > SMA(regime_ma_window) 이면 risk-on."""
    if not params.regime_enabled:
        return True
    df = candles.get(params.regime_ticker)
    if df is None or df.empty:
        # regime 데이터 없음 → 안전을 위해 risk-off 처리 (전원 flat)
        return False
    if len(df) < params.regime_ma_window + 1:
        return False
    try:
        last_close = float(df.iloc[-1]["close"])
        sma = float(df["close"].tail(params.regime_ma_window).mean())
    except (KeyError, IndexError, ValueError, TypeError):
        return False
    if not math.isfinite(last_close) or not math.isfinite(sma) or sma <= 0:
        return False
    return last_close > sma


def _rank_top_k(scores: dict[str, float], top_k: int) -> list[str]:
    """점수 내림차순 정렬해 상위 K 선택 (tie-breaker: ticker name)."""
    # (score, -reverse_rank_by_ticker) 구조로 안정 정렬
    ordered = sorted(
        scores.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return [t for t, _ in ordered[:top_k]]


# ---------------------------------------------------------------------------
# Signal factory — 바로 PortfolioSignal 로 쓸 수 있도록
# ---------------------------------------------------------------------------


def make_csmom_signal(params: CsmomParams) -> PortfolioSignal:
    """CsmomParams 로부터 PortfolioSignal Callable 을 생성."""
    params.validate()

    def signal(
        candles: dict[str, pd.DataFrame],
        current_date: pd.Timestamp,
        ctx: PortfolioContext,
    ) -> dict[str, float]:
        # 1. regime filter
        if not _is_risk_on(candles, params):
            return {}

        # 2. momentum score per ticker (regime_ticker 도 universe 에 있으면 포함 가능)
        scores: dict[str, float] = {}
        for ticker, df in candles.items():
            s = _momentum_score(df, params.lookback_days)
            if s is None:
                continue
            scores[ticker] = s

        if not scores:
            return {}

        # 3. 양(+) momentum 만 후보 — 음수는 제외 (no-shorting 환경)
        positive = {t: s for t, s in scores.items() if s > 0}
        if not positive:
            return {}

        # 4. Top-K 선택 (Context.hold_N 이 있으면 min 으로 truncate)
        top_k = params.top_k
        if ctx.hold_N > 0:
            top_k = min(top_k, ctx.hold_N)
        top = _rank_top_k(positive, top_k)
        if not top:
            return {}

        # 5. equal weight × risk_budget
        w = ctx.risk_budget / len(top)
        return {t: w for t in top}

    return signal


def csmom_factory(params_dict: dict[str, Any]) -> tuple[PortfolioSignal, dict[str, Any]]:
    """walk_forward.SignalFactory 호환 factory.

    Args:
        params_dict: {"lookback_days": ..., "top_k": ..., ...} 등.
            rebal_days / hold_N 등 Context 쪽 값은 overrides 로 분리해 반환.

    Returns:
        (signal, context_overrides)
    """
    # Context overrides (portfolio_walk_forward 가 PortfolioContext 에 반영)
    overrides: dict[str, Any] = {}
    for ctx_key in ("rebal_days", "hold_N", "risk_budget", "lookback_days", "active_strategy_group"):
        if ctx_key in params_dict:
            overrides[ctx_key] = params_dict[ctx_key]

    # CsmomParams 는 오직 signal 로직 knob 만
    csmom_keys = {"lookback_days", "top_k", "regime_enabled", "regime_ticker", "regime_ma_window"}
    csmom_args = {k: v for k, v in params_dict.items() if k in csmom_keys}
    params = CsmomParams(**csmom_args)
    return make_csmom_signal(params), overrides


# ---------------------------------------------------------------------------
# CLI — Stage 2 in-sample backtest 실행
# ---------------------------------------------------------------------------


def _fetch_candles_multi(
    tickers: list[str], days: int,
) -> dict[str, pd.DataFrame]:
    """업비트에서 여러 ticker 의 일봉을 수집. 길이가 부족한 ticker 는 탈락 경고."""
    import pyupbit

    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = pyupbit.get_ohlcv(t, interval="day", count=days)
        if df is None or df.empty:
            print(f"# WARN: {t} — no data, skipping")
            continue
        out[t] = df
        print(f"# {t}: {len(df)} candles {df.index[0].date()} → {df.index[-1].date()}")
    return out


def cli(argv: list[str] | None = None) -> int:
    import argparse

    from auto_coin.backtest.portfolio_runner import (
        DEFAULT_SLIPPAGE,
        UPBIT_DEFAULT_FEE,
        portfolio_backtest,
    )

    p = argparse.ArgumentParser(
        prog="auto-coin-csmom",
        description="CSMOM (Cross-Sectional Momentum Rotation) in-sample backtest.",
    )
    p.add_argument("--tickers", default="KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL,KRW-DOGE",
                   help="comma-separated universe")
    p.add_argument("--days", type=int, default=730,
                   help="candle count to fetch")
    p.add_argument("--lookback", type=int, default=60)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--rebal-days", type=int, default=7)
    p.add_argument("--risk-budget", type=float, default=0.8)
    p.add_argument("--regime-ticker", default="KRW-BTC")
    p.add_argument("--regime-ma", type=int, default=100)
    p.add_argument("--no-regime", action="store_true",
                   help="regime filter 비활성화 (순수 CSMOM)")
    p.add_argument("--fee", type=float, default=UPBIT_DEFAULT_FEE)
    p.add_argument("--slippage", type=float, default=DEFAULT_SLIPPAGE)
    p.add_argument("--initial-krw", type=float, default=1_000_000.0)
    args = p.parse_args(argv)

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print("ERROR: no tickers given", flush=True)
        return 1

    candles = _fetch_candles_multi(tickers, args.days)
    if not candles:
        print("ERROR: no candles fetched", flush=True)
        return 1

    params = CsmomParams(
        lookback_days=args.lookback,
        top_k=args.top_k,
        regime_enabled=not args.no_regime,
        regime_ticker=args.regime_ticker,
        regime_ma_window=args.regime_ma,
    )
    ctx = PortfolioContext(
        risk_budget=args.risk_budget,
        rebal_days=args.rebal_days,
        hold_N=args.top_k,
        lookback_days=args.lookback,
        active_strategy_group="csmom_v1",
    )

    signal = make_csmom_signal(params)
    result = portfolio_backtest(
        candles, signal,
        context=ctx,
        fee=args.fee, slippage=args.slippage,
        initial_krw=args.initial_krw,
    )

    # 리포트
    print()
    print("═" * 72)
    print(f"  CSMOM Stage 2 · in-sample backtest  ({len(candles)} tickers, {args.days}d)")
    print("═" * 72)
    print(f"  params: lookback={args.lookback}  top_k={args.top_k}  rebal={args.rebal_days}d  "
          f"regime={'ON' if not args.no_regime else 'OFF'}"
          + (f" ({args.regime_ticker}>SMA{args.regime_ma})" if not args.no_regime else ""))
    print(f"  fee={args.fee}  slippage={args.slippage}  risk_budget={args.risk_budget}")
    print("─" * 72)
    print(f"  Initial KRW          : {result.initial_krw:,.0f}")
    print(f"  Final Equity         : {result.final_equity_krw:,.0f}")
    print(f"  Cumulative Return    : {result.cumulative_return*100:+7.2f}%")
    print(f"  B&H (equal-weight)   : {result.benchmark_return*100:+7.2f}%")
    print(f"  Excess Return        : {result.excess_return*100:+7.2f}%")
    print(f"  MDD                  : {result.mdd*100:+6.2f}%")
    print(f"  Sharpe (daily→ann)   : {result.sharpe_ratio:5.2f}")
    print(f"  Total Trades         : {result.n_trades}")
    print(f"  Total Rebalances     : {result.n_rebalances}")
    if result.n_rebalances > 0:
        turnover = result.n_trades / result.n_rebalances
        print(f"  Avg trades / rebal   : {turnover:.2f}")
    print("═" * 72)

    # Stage 2 판정 힌트 (PLAN_CSMOM §4 Stage 2 기준)
    print()
    print("Stage 2 판정 힌트 (PLAN_CSMOM §4):")
    ok_excess = result.excess_return >= 0.10
    warn_excess = 0 < result.excess_return < 0.10
    fail_excess = result.excess_return <= 0
    ok_sharpe = result.sharpe_ratio >= 0.8
    ok_mdd = result.mdd >= -0.30
    warn_mdd = -0.50 < result.mdd < -0.30
    ok_trades = result.n_trades >= 60

    def mark(cond_ok: bool, cond_warn: bool = False) -> str:
        if cond_ok:
            return "✅ pass"
        if cond_warn:
            return "⚠️  warn"
        return "❌ hard-fail"

    print(f"  Excess vs B&H ≥ +10%  : {mark(ok_excess, warn_excess)}  ({result.excess_return*100:+.2f}%)")
    print(f"  Sharpe ≥ 0.8          : {mark(ok_sharpe, result.sharpe_ratio >= 0.4)}  ({result.sharpe_ratio:.2f})")
    print(f"  MDD ≥ -30%            : {mark(ok_mdd, warn_mdd)}  ({result.mdd*100:.2f}%)")
    print(f"  Trade count ≥ 60      : {mark(ok_trades, result.n_trades >= 30)}  ({result.n_trades})")

    return 0 if not fail_excess else 2


if __name__ == "__main__":
    raise SystemExit(cli())

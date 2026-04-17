"""KPI 집계 서비스 — TradeLog / DailySnapshot 기반.

순수 함수만 포함. DB·네트워크 의존 없음.
라우터가 TradeLog / DailySnapshot 리스트를 쿼리해서 넘기면, 본 모듈이 집계해 frozen
dataclass로 돌려준다. 테스트는 mock 객체로도 가능.

명명 규약 (의도적):
- TradeLog `pnl_ratio` 단순합은 **누적 수익률이 아니다** — `trade_total_pnl_krw`,
  `avg_pnl_ratio`, `win_rate` 등 거래 통계 용어만 쓴다.
- DailySnapshot `total_pnl_ratio`로 만든 equity curve / MDD는 **추정치**다.
  (종목별 수익률 단순합 구조라 정확한 포트폴리오 수익률이 아님.)
  따라서 필드명에 `estimated_` 접두사를 붙이고, 화면/JSON 어디에서도 이 점을 숨기지 않는다.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Protocol


class _TradeLike(Protocol):
    ticker: str
    strategy_name: str
    mode: str
    pnl_ratio: float
    pnl_krw: float
    fee_krw: float
    hold_seconds: int
    exit_reason_code: str | None
    # 슬리피지 집계용 (TradeLog에 이미 존재). 일부 구버전 row는 None일 수 있음.
    exit_at: datetime
    exit_price: float
    quantity: float
    decision_exit_price: float | None


class _SnapshotLike(Protocol):
    snapshot_date: date
    total_pnl_ratio: float
    realized_pnl_krw: float


@dataclass(frozen=True)
class StrategyBreakdown:
    strategy_name: str
    trade_count: int
    win_rate: float                 # 0~100
    trade_total_pnl_krw: float
    avg_pnl_ratio: float            # 거래 평균 수익률 (누적 수익률 아님)


@dataclass(frozen=True)
class TickerBreakdown:
    ticker: str
    trade_count: int
    win_rate: float
    trade_total_pnl_krw: float
    avg_pnl_ratio: float


@dataclass(frozen=True)
class ExitReasonBreakdown:
    reason_code: str
    count: int
    pct: float                      # 전체 거래 대비 비중 (0~100)


@dataclass(frozen=True)
class DailyPoint:
    """일별 데이터 1행.

    `estimated_cumulative`는 종목별 수익률 합으로 구성된 근사 equity curve 값이다.
    정확한 portfolio equity가 아니라는 점을 필드명으로 명시한다.
    """

    date: date
    pnl_ratio: float                # 해당 일 total_pnl_ratio (원본 그대로)
    estimated_cumulative: float     # 근사 누적 equity (1.0 시작)
    realized_krw: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "pnl_ratio": self.pnl_ratio,
            "estimated_cumulative": self.estimated_cumulative,
            "realized_krw": self.realized_krw,
        }


@dataclass(frozen=True)
class TradeKpiResult:
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float                     # 0~100
    avg_pnl_ratio: float                # 전체 평균 수익률
    avg_win_ratio: float                # 수익 거래 평균 (없으면 0)
    avg_loss_ratio: float               # 손실 거래 평균 (없으면 0)
    avg_hold_seconds: float
    trade_total_pnl_krw: float          # 거래 단위 실현 PnL 합 (포트폴리오 누적 수익률과 다름)
    total_fee_krw: float
    by_strategy: list[StrategyBreakdown] = field(default_factory=list)
    by_ticker: list[TickerBreakdown] = field(default_factory=list)
    by_exit_reason: list[ExitReasonBreakdown] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # dataclass asdict는 list[dataclass]도 잘 변환함.
        return d


@dataclass(frozen=True)
class DailyKpiResult:
    days_count: int
    win_days: int
    loss_days: int
    daily_series: list[DailyPoint] = field(default_factory=list)
    # 근사 지표: 포트폴리오 구조상 정확한 수익률/MDD가 아님. 접두사로 명시.
    estimated_mdd: float = 0.0
    estimated_mdd_peak_date: date | None = None
    estimated_mdd_trough_date: date | None = None
    estimated_cumulative_return: float = 0.0
    total_realized_krw: float = 0.0
    avg_daily_pnl_ratio: float = 0.0
    best_day: DailyPoint | None = None
    worst_day: DailyPoint | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "days_count": self.days_count,
            "win_days": self.win_days,
            "loss_days": self.loss_days,
            "daily_series": [p.to_dict() for p in self.daily_series],
            "estimated_mdd": self.estimated_mdd,
            "estimated_mdd_peak_date": (
                self.estimated_mdd_peak_date.isoformat()
                if self.estimated_mdd_peak_date else None
            ),
            "estimated_mdd_trough_date": (
                self.estimated_mdd_trough_date.isoformat()
                if self.estimated_mdd_trough_date else None
            ),
            "estimated_cumulative_return": self.estimated_cumulative_return,
            "total_realized_krw": self.total_realized_krw,
            "avg_daily_pnl_ratio": self.avg_daily_pnl_ratio,
            "best_day": self.best_day.to_dict() if self.best_day else None,
            "worst_day": self.worst_day.to_dict() if self.worst_day else None,
            "note": (
                "estimated_* 지표는 DailySnapshot.total_pnl_ratio (종목별 수익률 합)"
                " 기반 추정치(근사)로, 정확한 포트폴리오 가중 수익률이 아닙니다."
            ),
        }


@dataclass(frozen=True)
class SlippageReasonBreakdown:
    reason_code: str
    count: int
    avg_bp: float
    worst_bp: float


@dataclass(frozen=True)
class SlippageTickerBreakdown:
    ticker: str
    count: int
    avg_bp: float
    worst_bp: float


@dataclass(frozen=True)
class SlippageRecent:
    exit_at: datetime
    ticker: str
    decision_exit_price: float
    exit_price: float
    slippage_bp: float
    exit_reason_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_at": self.exit_at.isoformat(),
            "ticker": self.ticker,
            "decision_exit_price": self.decision_exit_price,
            "exit_price": self.exit_price,
            "slippage_bp": self.slippage_bp,
            "exit_reason_code": self.exit_reason_code,
        }


@dataclass(frozen=True)
class SlippageKpiResult:
    """SELL 슬리피지 집계.

    부호 정책: signed 그대로 보존. SELL 기준 음수 bp = 결정가보다 낮게 체결 = 불리.
    `worst_bp`는 가장 작은(=가장 음수) 값.
    `estimated_total_slippage_krw`는 결정가 대비 체결가 차이의 추정 합으로,
    실제 확정 손실액과 동일하지 않다.
    """

    measurable_count: int = 0
    exact_match_count: int = 0           # exit==decision인 건수 (fallback "가능성" 힌트)
    avg_bp: float = 0.0
    median_bp: float = 0.0
    worst_bp: float = 0.0                # min(bp); SELL 기준 가장 불리
    best_bp: float = 0.0                 # max(bp); SELL 기준 가장 유리
    estimated_total_slippage_krw: float = 0.0
    by_ticker: list[SlippageTickerBreakdown] = field(default_factory=list)
    by_reason: list[SlippageReasonBreakdown] = field(default_factory=list)
    recent: list[SlippageRecent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "measurable_count": self.measurable_count,
            "exact_match_count": self.exact_match_count,
            "avg_bp": self.avg_bp,
            "median_bp": self.median_bp,
            "worst_bp": self.worst_bp,
            "best_bp": self.best_bp,
            "estimated_total_slippage_krw": self.estimated_total_slippage_krw,
            "by_ticker": [asdict(b) for b in self.by_ticker],
            "by_reason": [asdict(b) for b in self.by_reason],
            "recent": [r.to_dict() for r in self.recent],
            "note": (
                "포함 기준: mode=live + decision_exit_price>0 + exit_price>0. "
                "SELL 기준 — 음수 bp는 결정가보다 낮게 체결(불리). "
                "exact_match_count는 exit_price==decision_exit_price인 건수로, "
                "fallback(체결가 미확정) '가능성 힌트'일 뿐 확정이 아닙니다 — 우연 일치도 가능합니다. "
                "estimated_total_slippage_krw는 (exit-decision)*quantity의 단순 합으로, "
                "결정가 대비 체결가 차이의 추정 합이며 실제 확정 손실액과는 다를 수 있습니다."
            ),
        }


@dataclass(frozen=True)
class KpiSummary:
    period_label: str
    trade_kpi: TradeKpiResult
    daily_kpi: DailyKpiResult
    slippage_kpi: SlippageKpiResult = field(default_factory=SlippageKpiResult)

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_label": self.period_label,
            "trade_kpi": self.trade_kpi.to_dict(),
            "daily_kpi": self.daily_kpi.to_dict(),
            "slippage_kpi": self.slippage_kpi.to_dict(),
        }


# ---------------------------------------------------------------------------
# Trade KPI
# ---------------------------------------------------------------------------

def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _breakdowns_by(
    key_name: str,
    trades: list[_TradeLike],
    *,
    kind: str,
) -> list:
    """kind: "strategy" | "ticker" — 공통 group-by."""
    grouped: dict[str, list[_TradeLike]] = defaultdict(list)
    for t in trades:
        grouped[getattr(t, key_name)].append(t)

    out = []
    for key, items in grouped.items():
        wins = sum(1 for x in items if x.pnl_ratio > 0)
        ratios = [x.pnl_ratio for x in items]
        payload = {
            "trade_count": len(items),
            "win_rate": (wins / len(items) * 100.0) if items else 0.0,
            "trade_total_pnl_krw": sum(x.pnl_krw for x in items),
            "avg_pnl_ratio": _safe_mean(ratios),
        }
        if kind == "strategy":
            out.append(StrategyBreakdown(strategy_name=key, **payload))
        else:
            out.append(TickerBreakdown(ticker=key, **payload))

    out.sort(key=lambda b: b.trade_total_pnl_krw, reverse=True)
    return out


def _exit_reason_breakdown(trades: list[_TradeLike]) -> list[ExitReasonBreakdown]:
    grouped: dict[str, int] = defaultdict(int)
    for t in trades:
        code = t.exit_reason_code or "unknown"
        grouped[code] += 1
    total = len(trades)
    rows = [
        ExitReasonBreakdown(
            reason_code=code,
            count=count,
            pct=(count / total * 100.0) if total else 0.0,
        )
        for code, count in grouped.items()
    ]
    rows.sort(key=lambda r: r.count, reverse=True)
    return rows


def compute_trade_kpi(trades: list[_TradeLike]) -> TradeKpiResult:
    """TradeLog 리스트로부터 거래 단위 KPI를 계산한다.

    주의: `trade_total_pnl_krw`는 거래 실현 KRW 합이고, `avg_pnl_ratio`는 거래별 평균이다.
    이 둘을 "누적 수익률"로 해석하지 말 것. 포트폴리오 수익률은 DailyKpiResult의
    `estimated_cumulative_return`을 참조.
    """
    trades = list(trades)
    if not trades:
        return TradeKpiResult(
            total_trades=0, win_count=0, loss_count=0, win_rate=0.0,
            avg_pnl_ratio=0.0, avg_win_ratio=0.0, avg_loss_ratio=0.0,
            avg_hold_seconds=0.0, trade_total_pnl_krw=0.0, total_fee_krw=0.0,
        )

    win_ratios = [t.pnl_ratio for t in trades if t.pnl_ratio > 0]
    loss_ratios = [t.pnl_ratio for t in trades if t.pnl_ratio <= 0]
    total = len(trades)
    wins = len(win_ratios)
    losses = len(loss_ratios)

    return TradeKpiResult(
        total_trades=total,
        win_count=wins,
        loss_count=losses,
        win_rate=(wins / total * 100.0),
        avg_pnl_ratio=_safe_mean([t.pnl_ratio for t in trades]),
        avg_win_ratio=_safe_mean(win_ratios),
        avg_loss_ratio=_safe_mean(loss_ratios),
        avg_hold_seconds=_safe_mean([float(t.hold_seconds) for t in trades]),
        trade_total_pnl_krw=sum(t.pnl_krw for t in trades),
        total_fee_krw=sum(t.fee_krw for t in trades),
        by_strategy=_breakdowns_by("strategy_name", trades, kind="strategy"),
        by_ticker=_breakdowns_by("ticker", trades, kind="ticker"),
        by_exit_reason=_exit_reason_breakdown(trades),
    )


# ---------------------------------------------------------------------------
# Daily KPI
# ---------------------------------------------------------------------------

def _aggregate_snapshots_by_date(
    snapshots: list[_SnapshotLike],
) -> list[tuple[date, float, float]]:
    """같은 날짜에 여러 snapshot이 있을 수 있으므로 합산.

    반환: (date, pnl_ratio_sum, realized_krw_sum) 오름차순 리스트.
    """
    bucket: dict[date, list[float]] = defaultdict(list)
    krw_bucket: dict[date, list[float]] = defaultdict(list)
    for s in snapshots:
        bucket[s.snapshot_date].append(s.total_pnl_ratio)
        krw_bucket[s.snapshot_date].append(s.realized_pnl_krw)

    out = []
    for d in sorted(bucket):
        out.append((d, sum(bucket[d]), sum(krw_bucket[d])))
    return out


def _compute_estimated_mdd(
    series: list[DailyPoint],
) -> tuple[float, date | None, date | None]:
    if not series:
        return 0.0, None, None
    peak = series[0].estimated_cumulative
    peak_date = series[0].date
    mdd = 0.0
    mdd_peak_date: date | None = None
    mdd_trough_date: date | None = None
    for pt in series:
        if pt.estimated_cumulative > peak:
            peak = pt.estimated_cumulative
            peak_date = pt.date
        dd = (pt.estimated_cumulative - peak) / peak if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd
            mdd_peak_date = peak_date
            mdd_trough_date = pt.date
    return mdd, mdd_peak_date, mdd_trough_date


def compute_daily_kpi(snapshots: list[_SnapshotLike]) -> DailyKpiResult:
    """DailySnapshot 리스트로부터 일별 KPI를 계산한다.

    경고: 결과의 estimated_* 지표는 `total_pnl_ratio` (종목별 수익률 합) 기반 근사치다.
    정확한 포트폴리오 equity가 필요하면 DailySnapshot 모델에 total_equity_krw 추가 후
    재계산해야 한다 (Phase 3).
    """
    snapshots = list(snapshots)
    if not snapshots:
        return DailyKpiResult(days_count=0, win_days=0, loss_days=0)

    aggregated = _aggregate_snapshots_by_date(snapshots)
    series: list[DailyPoint] = []
    equity = 1.0
    for d, ratio, krw in aggregated:
        equity *= (1.0 + ratio)
        series.append(DailyPoint(
            date=d,
            pnl_ratio=ratio,
            estimated_cumulative=equity,
            realized_krw=krw,
        ))

    win_days = sum(1 for p in series if p.pnl_ratio > 0)
    loss_days = sum(1 for p in series if p.pnl_ratio <= 0)

    mdd, mdd_peak, mdd_trough = _compute_estimated_mdd(series)

    best_day = max(series, key=lambda p: p.pnl_ratio) if series else None
    worst_day = min(series, key=lambda p: p.pnl_ratio) if series else None
    final_cumulative = series[-1].estimated_cumulative if series else 1.0

    return DailyKpiResult(
        days_count=len(series),
        win_days=win_days,
        loss_days=loss_days,
        daily_series=series,
        estimated_mdd=mdd,
        estimated_mdd_peak_date=mdd_peak,
        estimated_mdd_trough_date=mdd_trough,
        estimated_cumulative_return=final_cumulative - 1.0,
        total_realized_krw=sum(p.realized_krw for p in series),
        avg_daily_pnl_ratio=_safe_mean([p.pnl_ratio for p in series]),
        best_day=best_day,
        worst_day=worst_day,
    )


def compute_summary(
    trades: list[_TradeLike],
    snapshots: list[_SnapshotLike],
    period_label: str,
    *,
    slippage_recent_n: int = 20,
) -> KpiSummary:
    return KpiSummary(
        period_label=period_label,
        trade_kpi=compute_trade_kpi(trades),
        daily_kpi=compute_daily_kpi(snapshots),
        slippage_kpi=compute_slippage_kpi(trades, recent_n=slippage_recent_n),
    )


# ---------------------------------------------------------------------------
# Slippage KPI (live SELL only — P2-4)
# ---------------------------------------------------------------------------

def _is_slippage_measurable(t: _TradeLike) -> bool:
    """집계 모집단 필터. paper와 누락 데이터 제외."""
    if getattr(t, "mode", None) != "live":
        return False
    decision = getattr(t, "decision_exit_price", None)
    if decision is None or decision <= 0:
        return False
    exit_price = getattr(t, "exit_price", 0.0) or 0.0
    if exit_price <= 0:
        return False
    quantity = getattr(t, "quantity", 0.0) or 0.0
    return quantity > 0


def _slippage_bp(decision: float, fill: float) -> float:
    return (fill / decision - 1.0) * 10_000.0


def compute_slippage_kpi(
    trades: list[_TradeLike], *, recent_n: int = 20,
) -> SlippageKpiResult:
    """SELL 슬리피지 집계.

    부호 그대로 보존 (auto-flip 안 함). worst_bp는 가장 음수.
    fallback이 의심되는 동값 거래(exit==decision)는 모집단에 포함하되
    `exact_match_count`로 별도 노출 — 사용자 판단에 맡김.
    """
    pool = [t for t in trades if _is_slippage_measurable(t)]
    if not pool:
        return SlippageKpiResult()

    bps: list[float] = []
    krw_sum = 0.0
    exact_match = 0

    by_ticker_bucket: dict[str, list[float]] = defaultdict(list)
    by_reason_bucket: dict[str, list[float]] = defaultdict(list)

    for t in pool:
        bp = _slippage_bp(t.decision_exit_price, t.exit_price)
        bps.append(bp)
        krw_sum += (t.exit_price - t.decision_exit_price) * t.quantity
        if t.exit_price == t.decision_exit_price:
            exact_match += 1
        by_ticker_bucket[t.ticker].append(bp)
        by_reason_bucket[t.exit_reason_code or "unknown"].append(bp)

    by_ticker = [
        SlippageTickerBreakdown(
            ticker=tk, count=len(vs),
            avg_bp=_safe_mean(vs), worst_bp=min(vs),
        )
        for tk, vs in by_ticker_bucket.items()
    ]
    by_ticker.sort(key=lambda b: b.avg_bp)  # 가장 불리한(음수) 종목 상단

    by_reason = [
        SlippageReasonBreakdown(
            reason_code=rc, count=len(vs),
            avg_bp=_safe_mean(vs), worst_bp=min(vs),
        )
        for rc, vs in by_reason_bucket.items()
    ]
    by_reason.sort(key=lambda b: b.avg_bp)

    recent_sorted = sorted(pool, key=lambda t: t.exit_at, reverse=True)[:recent_n]
    recent = [
        SlippageRecent(
            exit_at=t.exit_at,
            ticker=t.ticker,
            decision_exit_price=t.decision_exit_price,
            exit_price=t.exit_price,
            slippage_bp=_slippage_bp(t.decision_exit_price, t.exit_price),
            exit_reason_code=t.exit_reason_code,
        )
        for t in recent_sorted
    ]

    return SlippageKpiResult(
        measurable_count=len(pool),
        exact_match_count=exact_match,
        avg_bp=_safe_mean(bps),
        median_bp=float(statistics.median(bps)),
        worst_bp=min(bps),
        best_bp=max(bps),
        estimated_total_slippage_krw=krw_sum,
        by_ticker=by_ticker,
        by_reason=by_reason,
        recent=recent,
    )

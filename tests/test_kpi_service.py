"""P2-2 — web/services/kpi.py 순수 집계 함수 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pytest

from auto_coin.web.services.kpi import (
    compute_daily_kpi,
    compute_slippage_kpi,
    compute_summary,
    compute_trade_kpi,
)


@dataclass
class _T:
    """TradeLog-shaped stand-in (SQLModel 없이도 순수 함수 테스트)."""

    ticker: str
    strategy_name: str
    mode: str
    pnl_ratio: float
    pnl_krw: float
    fee_krw: float
    hold_seconds: int
    exit_reason_code: str | None
    # 슬리피지 집계 필드 (default → 기존 trade KPI 테스트 영향 없음)
    exit_at: datetime = datetime(2026, 4, 16, 12, 0, 0)
    exit_price: float = 0.0
    quantity: float = 0.0
    decision_exit_price: float | None = None


@dataclass
class _S:
    """DailySnapshot-shaped stand-in."""

    snapshot_date: date
    total_pnl_ratio: float
    realized_pnl_krw: float
    portfolio_equity_krw: float | None = None


def _trade(
    *,
    ticker="KRW-BTC", strategy="vb", mode="paper",
    ratio=0.01, krw=1000.0, fee=50.0, hold=3600, reason="signal_sell",
    exit_at: datetime | None = None,
    exit_price: float = 0.0, quantity: float = 0.0,
    decision_exit_price: float | None = None,
) -> _T:
    return _T(
        ticker=ticker, strategy_name=strategy, mode=mode,
        pnl_ratio=ratio, pnl_krw=krw, fee_krw=fee,
        hold_seconds=hold, exit_reason_code=reason,
        exit_at=exit_at or datetime(2026, 4, 16, 12, 0, 0),
        exit_price=exit_price, quantity=quantity,
        decision_exit_price=decision_exit_price,
    )


def _live_sell(
    *,
    ticker="KRW-BTC", reason="signal_sell",
    decision: float, fill: float, qty: float = 1.0,
    exit_at: datetime | None = None,
) -> _T:
    """헬퍼: live SELL 슬리피지 테스트용."""
    return _trade(
        ticker=ticker, mode="live", reason=reason,
        decision_exit_price=decision, exit_price=fill, quantity=qty,
        exit_at=exit_at or datetime(2026, 4, 16, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# Trade KPI
# ---------------------------------------------------------------------------

def test_trade_kpi_empty():
    r = compute_trade_kpi([])
    assert r.total_trades == 0
    assert r.win_rate == 0.0
    assert r.avg_pnl_ratio == 0.0
    assert r.trade_total_pnl_krw == 0.0
    assert r.by_strategy == []
    assert r.by_ticker == []
    assert r.by_exit_reason == []


def test_trade_kpi_basic_win_rate_and_averages():
    trades = [
        _trade(ratio=0.02, krw=2000),
        _trade(ratio=0.04, krw=4000),
        _trade(ratio=-0.03, krw=-3000),
    ]
    r = compute_trade_kpi(trades)
    assert r.total_trades == 3
    assert r.win_count == 2
    assert r.loss_count == 1
    assert r.win_rate == pytest.approx(66.666, rel=1e-3)
    assert r.avg_pnl_ratio == pytest.approx(0.01, rel=1e-6)
    assert r.avg_win_ratio == pytest.approx(0.03, rel=1e-6)
    assert r.avg_loss_ratio == pytest.approx(-0.03, rel=1e-6)
    assert r.trade_total_pnl_krw == 3000.0


def test_trade_kpi_by_strategy_splits_correctly():
    trades = [
        _trade(strategy="vb", ratio=0.02, krw=2000),
        _trade(strategy="vb", ratio=-0.01, krw=-1000),
        _trade(strategy="sma", ratio=0.05, krw=5000),
    ]
    r = compute_trade_kpi(trades)
    names = {b.strategy_name: b for b in r.by_strategy}
    assert set(names) == {"vb", "sma"}
    assert names["vb"].trade_count == 2
    assert names["vb"].trade_total_pnl_krw == 1000.0
    assert names["vb"].win_rate == pytest.approx(50.0)
    assert names["sma"].trade_count == 1
    assert names["sma"].trade_total_pnl_krw == 5000.0
    # sorted by trade_total_pnl_krw desc
    assert r.by_strategy[0].strategy_name == "sma"


def test_trade_kpi_by_ticker_splits_correctly():
    trades = [
        _trade(ticker="KRW-BTC", krw=100.0, ratio=0.01),
        _trade(ticker="KRW-BTC", krw=200.0, ratio=0.02),
        _trade(ticker="KRW-ETH", krw=-50.0, ratio=-0.01),
    ]
    r = compute_trade_kpi(trades)
    names = {b.ticker: b for b in r.by_ticker}
    assert names["KRW-BTC"].trade_count == 2
    assert names["KRW-BTC"].trade_total_pnl_krw == 300.0
    assert names["KRW-ETH"].trade_count == 1


def test_trade_kpi_by_exit_reason_pct():
    trades = [
        _trade(reason="stop_loss"),
        _trade(reason="stop_loss"),
        _trade(reason="signal_sell"),
        _trade(reason=None),
    ]
    r = compute_trade_kpi(trades)
    codes = {b.reason_code: b for b in r.by_exit_reason}
    assert codes["stop_loss"].count == 2
    assert codes["stop_loss"].pct == pytest.approx(50.0)
    assert codes["signal_sell"].count == 1
    assert codes["signal_sell"].pct == pytest.approx(25.0)
    assert codes["unknown"].count == 1  # None → "unknown"


def test_trade_kpi_hold_seconds_average():
    trades = [
        _trade(hold=1800),
        _trade(hold=3600),
        _trade(hold=7200),
    ]
    r = compute_trade_kpi(trades)
    assert r.avg_hold_seconds == pytest.approx(4200.0)


def test_trade_kpi_all_losses():
    trades = [_trade(ratio=-0.01, krw=-100), _trade(ratio=-0.02, krw=-200)]
    r = compute_trade_kpi(trades)
    assert r.win_rate == 0.0
    assert r.avg_win_ratio == 0.0          # empty win list → 0
    assert r.avg_loss_ratio == pytest.approx(-0.015)


# ---------------------------------------------------------------------------
# Daily KPI — equity curve / MDD / win-loss days
# ---------------------------------------------------------------------------

def test_daily_kpi_empty():
    r = compute_daily_kpi([])
    assert r.days_count == 0
    assert r.estimated_mdd == 0.0
    assert r.estimated_mdd_peak_date is None
    assert r.estimated_mdd_trough_date is None
    assert r.estimated_cumulative_return == 0.0
    assert r.daily_series == []
    assert r.best_day is None


def test_daily_kpi_equity_curve_compounds():
    # +2%, -1%, +3% → (1.02)(0.99)(1.03) = 1.039994
    snaps = [
        _S(date(2026, 4, 1), 0.02, 20_000),
        _S(date(2026, 4, 2), -0.01, -10_000),
        _S(date(2026, 4, 3), 0.03, 30_000),
    ]
    r = compute_daily_kpi(snaps)
    assert r.days_count == 3
    assert r.daily_series[0].estimated_cumulative == pytest.approx(1.02)
    assert r.daily_series[1].estimated_cumulative == pytest.approx(1.02 * 0.99)
    assert r.daily_series[2].estimated_cumulative == pytest.approx(1.02 * 0.99 * 1.03)
    assert r.estimated_cumulative_return == pytest.approx(
        1.02 * 0.99 * 1.03 - 1.0,
    )
    assert r.total_realized_krw == 40_000.0


def test_daily_kpi_mdd_peak_trough_dates():
    # +10%, -5%, -5%, +3% : peak at day0 (1.10), trough at day2 (1.10*0.95*0.95=0.99275)
    snaps = [
        _S(date(2026, 4, 1), 0.10, 0),
        _S(date(2026, 4, 2), -0.05, 0),
        _S(date(2026, 4, 3), -0.05, 0),
        _S(date(2026, 4, 4), 0.03, 0),
    ]
    r = compute_daily_kpi(snaps)
    # MDD relative to peak=1.10 at day0, trough=1.10*0.95*0.95 at day2
    expected_trough = 1.10 * 0.95 * 0.95
    expected_mdd = (expected_trough - 1.10) / 1.10
    assert r.estimated_mdd == pytest.approx(expected_mdd)
    assert r.estimated_mdd_peak_date == date(2026, 4, 1)
    assert r.estimated_mdd_trough_date == date(2026, 4, 3)


def test_daily_kpi_win_loss_days():
    snaps = [
        _S(date(2026, 4, 1), 0.01, 0),
        _S(date(2026, 4, 2), 0.02, 0),
        _S(date(2026, 4, 3), -0.01, 0),
        _S(date(2026, 4, 4), 0.0, 0),
        _S(date(2026, 4, 5), -0.02, 0),
    ]
    r = compute_daily_kpi(snaps)
    assert r.win_days == 2
    assert r.loss_days == 3  # 0도 loss로 집계 (> 0만 win)


def test_daily_kpi_best_worst_day():
    snaps = [
        _S(date(2026, 4, 1), 0.03, 0),
        _S(date(2026, 4, 2), -0.04, 0),
        _S(date(2026, 4, 3), 0.01, 0),
    ]
    r = compute_daily_kpi(snaps)
    assert r.best_day is not None and r.best_day.date == date(2026, 4, 1)
    assert r.worst_day is not None and r.worst_day.date == date(2026, 4, 2)


def test_daily_kpi_aggregates_same_date_multiple_rows():
    # 같은 날 2개 snapshot (전략별 row) → 합산
    snaps = [
        _S(date(2026, 4, 1), 0.02, 2000),
        _S(date(2026, 4, 1), 0.01, 1000),
        _S(date(2026, 4, 2), -0.01, -500),
    ]
    r = compute_daily_kpi(snaps)
    assert r.days_count == 2
    assert r.daily_series[0].pnl_ratio == pytest.approx(0.03)
    assert r.daily_series[0].realized_krw == pytest.approx(3000)


def test_daily_kpi_uses_portfolio_equity_when_available():
    snaps = [
        _S(date(2026, 4, 1), 0.02, 20_000, portfolio_equity_krw=1_000_000.0),
        _S(date(2026, 4, 2), -0.50, -10_000, portfolio_equity_krw=1_050_000.0),
        _S(date(2026, 4, 3), -0.30, 30_000, portfolio_equity_krw=1_100_000.0),
    ]
    r = compute_daily_kpi(snaps)
    assert r.equity_basis == "portfolio_equity_krw"
    assert r.daily_series[0].estimated_cumulative == pytest.approx(1.0)
    assert r.daily_series[1].estimated_cumulative == pytest.approx(1.05)
    assert r.daily_series[2].estimated_cumulative == pytest.approx(1.10)
    assert r.estimated_cumulative_return == pytest.approx(0.10)
    assert r.estimated_mdd == 0.0
    assert r.start_portfolio_equity_krw == pytest.approx(1_000_000.0)
    assert r.end_portfolio_equity_krw == pytest.approx(1_100_000.0)


# ---------------------------------------------------------------------------
# Summary + to_dict
# ---------------------------------------------------------------------------

def test_summary_combines_and_labels_estimates_in_dict():
    trades = [_trade(ratio=0.02, krw=2000)]
    snaps = [_S(date(2026, 4, 1), 0.02, 2000)]
    summary = compute_summary(trades, snaps, "최근 14일")
    d = summary.to_dict()
    assert d["period_label"] == "최근 14일"
    # Trade KPI — no "cumulative" wording
    assert "trade_total_pnl_krw" in d["trade_kpi"]
    assert d["trade_kpi"]["trade_total_pnl_krw"] == 2000.0
    # Daily KPI — estimated_* naming enforced
    dk = d["daily_kpi"]
    for key in ("estimated_mdd", "estimated_cumulative_return"):
        assert key in dk
    assert "note" in dk and "추정치" in dk["note"]
    assert dk["daily_series"][0]["date"] == "2026-04-01"
    assert "estimated_cumulative" in dk["daily_series"][0]


# ---------------------------------------------------------------------------
# Slippage KPI (P2-4)
# ---------------------------------------------------------------------------

def test_slippage_kpi_empty():
    r = compute_slippage_kpi([])
    assert r.measurable_count == 0
    assert r.exact_match_count == 0
    assert r.avg_bp == 0.0
    assert r.estimated_total_slippage_krw == 0.0
    assert r.by_ticker == []
    assert r.by_reason == []
    assert r.recent == []


def test_slippage_kpi_excludes_paper_trades():
    # paper만 있으면 모집단 0
    trades = [_trade(mode="paper", decision_exit_price=100.0, exit_price=99.0, quantity=1.0)]
    r = compute_slippage_kpi(trades)
    assert r.measurable_count == 0


def test_slippage_kpi_excludes_missing_or_invalid_prices():
    trades = [
        _live_sell(decision=0.0, fill=100.0, qty=1.0),     # decision=0 제외
        _trade(mode="live", decision_exit_price=None,
               exit_price=100.0, quantity=1.0),             # decision None 제외
        _trade(mode="live", decision_exit_price=100.0,
               exit_price=0.0, quantity=1.0),               # exit_price=0 제외
        _live_sell(decision=100.0, fill=99.0, qty=0.0),    # qty=0 제외
    ]
    r = compute_slippage_kpi(trades)
    assert r.measurable_count == 0


def test_slippage_kpi_signed_negative_bp_is_adverse_for_sell():
    # 100 → 99로 체결: ratio = -0.01, bp = -100
    r = compute_slippage_kpi([_live_sell(decision=100.0, fill=99.0, qty=1.0)])
    assert r.measurable_count == 1
    assert r.avg_bp == pytest.approx(-100.0)
    assert r.worst_bp == pytest.approx(-100.0)
    assert r.best_bp == pytest.approx(-100.0)
    assert r.estimated_total_slippage_krw == pytest.approx(-1.0)


def test_slippage_kpi_avg_median_worst_best_correct():
    # bp 분포: -50, -30, -10, 0, +20  (5건, 홀수)
    trades = [
        _live_sell(decision=100.0, fill=99.5, qty=1.0),    # -50 bp
        _live_sell(decision=100.0, fill=99.7, qty=1.0),    # -30 bp
        _live_sell(decision=100.0, fill=99.9, qty=1.0),    # -10 bp
        _live_sell(decision=100.0, fill=100.0, qty=1.0),   # 0 bp (exact match)
        _live_sell(decision=100.0, fill=100.2, qty=1.0),   # +20 bp
    ]
    r = compute_slippage_kpi(trades)
    assert r.measurable_count == 5
    assert r.avg_bp == pytest.approx((-50 - 30 - 10 + 0 + 20) / 5)
    assert r.median_bp == pytest.approx(-10.0)
    assert r.worst_bp == pytest.approx(-50.0)
    assert r.best_bp == pytest.approx(20.0)


def test_slippage_kpi_median_even_count():
    # bp: -40, -20  → median = -30
    trades = [
        _live_sell(decision=100.0, fill=99.6, qty=1.0),    # -40
        _live_sell(decision=100.0, fill=99.8, qty=1.0),    # -20
    ]
    r = compute_slippage_kpi(trades)
    assert r.median_bp == pytest.approx(-30.0)


def test_slippage_kpi_estimated_total_krw_uses_quantity():
    trades = [
        _live_sell(decision=100.0, fill=99.0, qty=2.0),    # -1 * 2 = -2
        _live_sell(decision=200.0, fill=205.0, qty=0.5),   # +5 * 0.5 = +2.5
    ]
    r = compute_slippage_kpi(trades)
    assert r.estimated_total_slippage_krw == pytest.approx(0.5)


def test_slippage_kpi_exact_match_counted_but_not_filtered():
    trades = [
        _live_sell(decision=100.0, fill=100.0, qty=1.0),   # exact
        _live_sell(decision=100.0, fill=99.0, qty=1.0),    # not
    ]
    r = compute_slippage_kpi(trades)
    assert r.measurable_count == 2
    assert r.exact_match_count == 1


def test_slippage_kpi_by_ticker_grouping():
    trades = [
        _live_sell(ticker="KRW-BTC", decision=100.0, fill=99.0, qty=1.0),  # -100
        _live_sell(ticker="KRW-BTC", decision=100.0, fill=99.5, qty=1.0),  # -50
        _live_sell(ticker="KRW-ETH", decision=100.0, fill=100.5, qty=1.0), # +50
    ]
    r = compute_slippage_kpi(trades)
    by = {b.ticker: b for b in r.by_ticker}
    assert by["KRW-BTC"].count == 2
    assert by["KRW-BTC"].avg_bp == pytest.approx(-75.0)
    assert by["KRW-BTC"].worst_bp == pytest.approx(-100.0)
    assert by["KRW-ETH"].count == 1
    # 가장 불리한 종목이 상단 (avg 오름차순)
    assert r.by_ticker[0].ticker == "KRW-BTC"


def test_slippage_kpi_by_reason_grouping():
    trades = [
        _live_sell(reason="stop_loss", decision=100.0, fill=98.0, qty=1.0),    # -200
        _live_sell(reason="stop_loss", decision=100.0, fill=99.0, qty=1.0),    # -100
        _live_sell(reason="signal_sell", decision=100.0, fill=99.9, qty=1.0),  # -10
        _live_sell(reason="time_exit", decision=100.0, fill=100.05, qty=1.0),  # +5
    ]
    r = compute_slippage_kpi(trades)
    by = {b.reason_code: b for b in r.by_reason}
    assert by["stop_loss"].count == 2
    assert by["stop_loss"].avg_bp == pytest.approx(-150.0)
    assert by["stop_loss"].worst_bp == pytest.approx(-200.0)
    assert by["signal_sell"].count == 1
    assert by["time_exit"].count == 1
    assert r.by_reason[0].reason_code == "stop_loss"  # avg 가장 음수


def test_slippage_kpi_recent_sorted_desc_and_limited():
    base = datetime(2026, 4, 16, 12, 0, 0)
    trades = [
        _live_sell(ticker="A", decision=100.0, fill=99.0, qty=1.0,
                   exit_at=base.replace(hour=10)),
        _live_sell(ticker="B", decision=100.0, fill=99.5, qty=1.0,
                   exit_at=base.replace(hour=12)),
        _live_sell(ticker="C", decision=100.0, fill=99.8, qty=1.0,
                   exit_at=base.replace(hour=14)),
    ]
    r = compute_slippage_kpi(trades, recent_n=2)
    assert len(r.recent) == 2
    # 최신순 — C(14시) → B(12시)
    assert r.recent[0].ticker == "C"
    assert r.recent[1].ticker == "B"


def test_summary_includes_slippage_with_clear_naming_and_note():
    trades = [_live_sell(decision=100.0, fill=99.0, qty=1.0)]
    summary = compute_summary(trades, [], "최근 14일")
    d = summary.to_dict()
    assert "slippage_kpi" in d
    s = d["slippage_kpi"]
    # 명명 정책 — estimated_ 접두사
    assert "estimated_total_slippage_krw" in s
    assert "total_slippage_krw" not in s
    # note 문구 — 두 가지 의미가 모두 명시되어야 함
    assert "note" in s
    assert "가능성" in s["note"]               # exact_match는 "가능성 힌트"
    assert "확정" in s["note"]                 # "확정 아님" 표기
    assert "추정" in s["note"]                 # estimated_total은 "추정 합"
    # recent의 datetime은 ISO 문자열로 직렬화
    assert isinstance(s["recent"][0]["exit_at"], str)
    assert s["recent"][0]["exit_at"].startswith("2026-04-16")

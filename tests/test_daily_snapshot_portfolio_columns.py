"""DailySnapshot portfolio-aware 컬럼 스키마 테스트 (B2)."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect
from sqlmodel import Session, select

from auto_coin.web import db as web_db
from auto_coin.web.models import DailySnapshot


@pytest.fixture
def app_engine(tmp_path, monkeypatch):
    """격리된 SQLite 엔진 — HOME 을 tmp_path 로 바꾸고 init_engine 호출."""
    monkeypatch.setenv("HOME", str(tmp_path))
    web_db.reset_engine()
    web_db.init_engine(tmp_path / ".auto_coin.db")
    try:
        yield web_db.engine()
    finally:
        web_db.reset_engine()


def test_dailysnapshot_has_portfolio_columns(app_engine):
    """schema 에 신규 3 컬럼이 존재해야 한다."""
    inspector = inspect(app_engine)
    cols = {c["name"] for c in inspector.get_columns("dailysnapshot")}
    assert "portfolio_equity_krw" in cols
    assert "portfolio_excess_vs_bnh" in cols
    assert "active_strategy_group" in cols


def test_dailysnapshot_portfolio_columns_nullable(app_engine):
    """신규 컬럼은 NULL 허용 — legacy 레코드가 깨지면 안 됨."""
    with Session(app_engine) as s:
        legacy = DailySnapshot(
            snapshot_date=date(2026, 4, 18),
            mode="paper",
            strategy_name="volatility_breakout",
            total_pnl_ratio=0.01,
            open_positions=1,
            closed_trades_count=2,
            win_count=1,
            loss_count=1,
            realized_pnl_krw=5000.0,
            # portfolio_* 는 주지 않음 (None)
        )
        s.add(legacy)
        s.commit()
        s.refresh(legacy)
        assert legacy.portfolio_equity_krw is None
        assert legacy.portfolio_excess_vs_bnh is None
        assert legacy.active_strategy_group is None


def test_dailysnapshot_portfolio_columns_store_and_load(app_engine):
    """portfolio_* 값을 저장하고 다시 읽어올 수 있어야 함."""
    with Session(app_engine) as s:
        snap = DailySnapshot(
            snapshot_date=date(2026, 4, 18),
            mode="paper",
            strategy_name="csmom_v1",
            total_pnl_ratio=0.02,
            open_positions=3,
            closed_trades_count=5,
            win_count=3,
            loss_count=2,
            realized_pnl_krw=20000.0,
            portfolio_equity_krw=1_150_000.0,
            portfolio_excess_vs_bnh=0.035,
            active_strategy_group="csmom_v1",
        )
        s.add(snap)
        s.commit()

    with Session(app_engine) as s:
        got = s.exec(
            select(DailySnapshot).where(DailySnapshot.active_strategy_group == "csmom_v1")
        ).first()
        assert got is not None
        assert got.portfolio_equity_krw == pytest.approx(1_150_000.0)
        assert got.portfolio_excess_vs_bnh == pytest.approx(0.035)
        assert got.active_strategy_group == "csmom_v1"


def test_existing_dailysnapshot_tests_unaffected(app_engine):
    """기존 legacy 경로가 깨지지 않는지 간단히 확인 (test_trade_log::test_daily_snapshot_model 과 유사)."""
    snap = DailySnapshot(
        snapshot_date=date(2026, 4, 16),
        mode="paper",
        strategy_name="volatility_breakout",
        total_pnl_ratio=0.015,
        open_positions=1,
        closed_trades_count=3,
        win_count=2,
        loss_count=1,
        realized_pnl_krw=15000.0,
    )
    assert snap.total_pnl_ratio == 0.015
    assert snap.portfolio_equity_krw is None

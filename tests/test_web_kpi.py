"""P2-2 — /kpi 라우터 통합 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auto_coin.web import db as web_db
from auto_coin.web.app import create_app
from auto_coin.web.crypto import SecretBox
from auto_coin.web.models import DailySnapshot, TradeLog
from auto_coin.web.user_service import get_user


@pytest.fixture
def app_env(tmp_path, monkeypatch, mocker):
    web_db.reset_engine()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TICKER=\nTICKERS=KRW-BTC,KRW-ETH\nMAX_CONCURRENT_POSITIONS=2\n"
        "WATCH_INTERVAL_MINUTES=1440\nHEARTBEAT_INTERVAL_HOURS=0\n"
        "CHECK_INTERVAL_SECONDS=3600\nSTATE_DIR=state\n",
        encoding="utf-8",
    )
    mocker.patch("auto_coin.bot.fetch_daily", return_value=None)
    mocker.patch("auto_coin.exchange.upbit_client.pyupbit.get_current_price",
                 return_value=0.0)
    mocker.patch("auto_coin.notifier.telegram.requests.post")
    mocker.patch("auto_coin.web.routers.dashboard._safe_current_price",
                 return_value=None)
    yield tmp_path
    web_db.reset_engine()


def _login(client: TestClient) -> None:
    client.post("/setup", data={"password": "hunter22", "password_confirm": "hunter22"})
    with Session(web_db.engine()) as db:
        user = get_user(db)
        secret = SecretBox().decrypt(user.totp_secret_enc)
    client.post("/setup/totp", data={"code": pyotp.TOTP(secret).now()})


def _seed_trade(
    db: Session,
    *,
    ticker: str = "KRW-BTC", strategy: str = "vb",
    days_ago: int = 1, pnl_ratio: float = 0.02, pnl_krw: float = 2000.0,
    reason: str = "signal_sell",
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    entry = now - timedelta(days=days_ago, hours=2)
    exit_ = now - timedelta(days=days_ago)
    db.add(TradeLog(
        ticker=ticker, strategy_name=strategy, mode="paper",
        entry_at=entry, exit_at=exit_,
        entry_price=100.0, exit_price=100.0 * (1 + pnl_ratio),
        quantity=1.0, entry_value_krw=100.0, exit_value_krw=100.0 * (1 + pnl_ratio),
        fee_krw=50.0, pnl_ratio=pnl_ratio, pnl_krw=pnl_krw,
        hold_seconds=int((exit_ - entry).total_seconds()),
        exit_reason_code=reason, exit_reason_text=f"test {reason}",
    ))


def _seed_live_sell(
    db: Session,
    *,
    ticker: str = "KRW-BTC", strategy: str = "vb",
    days_ago: int = 1, decision_price: float, fill_price: float,
    quantity: float = 1.0, reason: str = "signal_sell",
) -> None:
    """live SELL TradeLog seed (슬리피지 측정용)."""
    now = datetime.now(UTC).replace(tzinfo=None)
    entry = now - timedelta(days=days_ago, hours=2)
    exit_ = now - timedelta(days=days_ago)
    pnl_krw = (fill_price - 100.0) * quantity
    db.add(TradeLog(
        ticker=ticker, strategy_name=strategy, mode="live",
        entry_at=entry, exit_at=exit_,
        entry_price=100.0, exit_price=fill_price,
        quantity=quantity,
        entry_value_krw=100.0 * quantity, exit_value_krw=fill_price * quantity,
        fee_krw=10.0, pnl_ratio=(fill_price / 100.0 - 1.0), pnl_krw=pnl_krw,
        hold_seconds=int((exit_ - entry).total_seconds()),
        exit_reason_code=reason, exit_reason_text=f"test {reason}",
        decision_exit_price=decision_price,
    ))


def _seed_snapshot(
    db: Session,
    *,
    days_ago: int,
    pnl_ratio: float,
    krw: float = 0.0,
    strategy: str = "vb",
    portfolio_equity_krw: float | None = None,
) -> None:
    d = datetime.now(UTC).date() - timedelta(days=days_ago)
    db.add(DailySnapshot(
        snapshot_date=d, mode="paper", strategy_name=strategy,
        total_pnl_ratio=pnl_ratio, open_positions=0,
        closed_trades_count=1, win_count=1 if pnl_ratio > 0 else 0,
        loss_count=0 if pnl_ratio > 0 else 1, realized_pnl_krw=krw,
        portfolio_equity_krw=portfolio_equity_krw,
    ))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_kpi_page_renders(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/kpi")
        assert r.status_code == 200
        assert "KPI" in r.text
        # 추정치 표기가 화면에 있음 — 숨기지 말 것
        assert "추정치" in r.text or "estimated" in r.text


def test_kpi_page_requires_auth(app_env):
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/kpi", follow_redirects=False)
        assert r.status_code == 303


def test_kpi_data_empty_db_returns_zero_structure(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/kpi/data")
        assert r.status_code == 200
        data = r.json()
        assert data["period"] == "14d"
        assert data["trade_kpi"]["total_trades"] == 0
        assert data["trade_kpi"]["trade_total_pnl_krw"] == 0.0
        assert data["daily_kpi"]["days_count"] == 0
        assert data["daily_kpi"]["estimated_mdd"] == 0.0
        assert data["daily_kpi"]["estimated_cumulative_return"] == 0.0
        # "cumulative_return" 필드는 반드시 estimated_ 접두사를 가진다
        assert "cumulative_return" not in data["trade_kpi"]


def test_kpi_data_returns_trade_aggregates(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            _seed_trade(db, strategy="vb", ticker="KRW-BTC",
                        days_ago=1, pnl_ratio=0.02, pnl_krw=2000, reason="signal_sell")
            _seed_trade(db, strategy="vb", ticker="KRW-ETH",
                        days_ago=2, pnl_ratio=-0.01, pnl_krw=-1000, reason="stop_loss")
            _seed_trade(db, strategy="sma", ticker="KRW-BTC",
                        days_ago=3, pnl_ratio=0.04, pnl_krw=4000, reason="signal_sell")
            db.commit()

        r = client.get("/kpi/data?period=14d")
        assert r.status_code == 200
        data = r.json()
        t = data["trade_kpi"]
        assert t["total_trades"] == 3
        assert t["win_count"] == 2
        assert t["loss_count"] == 1
        assert t["trade_total_pnl_krw"] == pytest.approx(5000.0)
        strategies = {b["strategy_name"] for b in t["by_strategy"]}
        assert strategies == {"vb", "sma"}
        tickers = {b["ticker"] for b in t["by_ticker"]}
        assert tickers == {"KRW-BTC", "KRW-ETH"}
        reasons = {b["reason_code"] for b in t["by_exit_reason"]}
        assert reasons == {"signal_sell", "stop_loss"}


def test_kpi_data_daily_uses_estimated_naming(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            _seed_snapshot(db, days_ago=2, pnl_ratio=0.02, krw=2000)
            _seed_snapshot(db, days_ago=1, pnl_ratio=-0.01, krw=-1000)
            db.commit()
        r = client.get("/kpi/data?period=14d")
        d = r.json()["daily_kpi"]
        assert d["days_count"] == 2
        assert "estimated_cumulative_return" in d
        assert "estimated_mdd" in d
        # daily_series entries — date as ISO string + estimated_cumulative key
        assert d["daily_series"][0]["date"]
        assert "estimated_cumulative" in d["daily_series"][0]
        # note 문구로 추정치 성격을 숨기지 않음
        assert "추정치" in d["note"]


def test_kpi_data_prefers_portfolio_equity_when_available(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            _seed_snapshot(
                db,
                days_ago=2,
                pnl_ratio=0.02,
                krw=2000,
                portfolio_equity_krw=1_000_000.0,
            )
            _seed_snapshot(
                db,
                days_ago=1,
                pnl_ratio=-0.50,
                krw=-1000,
                portfolio_equity_krw=1_050_000.0,
            )
            db.commit()
        r = client.get("/kpi/data?period=14d")
        d = r.json()["daily_kpi"]
        assert d["equity_basis"] == "portfolio_equity_krw"
        assert d["estimated_cumulative_return"] == pytest.approx(0.05)
        assert d["start_portfolio_equity_krw"] == pytest.approx(1_000_000.0)
        assert d["end_portfolio_equity_krw"] == pytest.approx(1_050_000.0)
        assert d["daily_series"][0]["portfolio_equity_krw"] == pytest.approx(1_000_000.0)


def test_kpi_data_period_filter_excludes_older_rows(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            # 2일 전, 10일 전 → 7d 필터는 2일 전만 포함
            _seed_trade(db, days_ago=2, pnl_ratio=0.02, pnl_krw=2000)
            _seed_trade(db, days_ago=10, pnl_ratio=-0.05, pnl_krw=-5000)
            db.commit()

        r = client.get("/kpi/data?period=7d")
        data = r.json()
        assert data["trade_kpi"]["total_trades"] == 1
        assert data["trade_kpi"]["trade_total_pnl_krw"] == pytest.approx(2000.0)

        r_all = client.get("/kpi/data?period=all")
        assert r_all.json()["trade_kpi"]["total_trades"] == 2


def test_kpi_data_unknown_period_falls_back_to_default(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/kpi/data?period=bogus")
        assert r.status_code == 200
        assert r.json()["period"] == "14d"


# ---------------------------------------------------------------------------
# Slippage section (P2-4)
# ---------------------------------------------------------------------------

def test_kpi_data_slippage_section_present_even_when_empty(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/kpi/data")
        assert r.status_code == 200
        s = r.json()["slippage_kpi"]
        assert s["measurable_count"] == 0
        assert s["estimated_total_slippage_krw"] == 0.0
        # 명명 정책 확인
        assert "total_slippage_krw" not in s
        assert "가능성" in s["note"]
        assert "확정" in s["note"]


def test_kpi_data_slippage_aggregates_live_sells(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            _seed_live_sell(db, ticker="KRW-BTC", days_ago=2,
                            decision_price=100.0, fill_price=99.0, quantity=1.0,
                            reason="stop_loss")          # -100 bp
            _seed_live_sell(db, ticker="KRW-BTC", days_ago=1,
                            decision_price=100.0, fill_price=99.5, quantity=1.0,
                            reason="signal_sell")        # -50 bp
            _seed_live_sell(db, ticker="KRW-ETH", days_ago=3,
                            decision_price=100.0, fill_price=100.0, quantity=1.0,
                            reason="signal_sell")        # 0 bp (exact match)
            db.commit()

        r = client.get("/kpi/data?period=14d")
        s = r.json()["slippage_kpi"]
        assert s["measurable_count"] == 3
        assert s["exact_match_count"] == 1
        assert s["worst_bp"] == pytest.approx(-100.0)
        assert s["best_bp"] == pytest.approx(0.0)
        # estimated_total_slippage_krw = -1 + -0.5 + 0 = -1.5
        assert s["estimated_total_slippage_krw"] == pytest.approx(-1.5)
        # by_reason 그룹핑 확인
        reasons = {b["reason_code"]: b for b in s["by_reason"]}
        assert reasons["stop_loss"]["count"] == 1
        assert reasons["stop_loss"]["worst_bp"] == pytest.approx(-100.0)
        # 최근 거래 — 최신 1일전(stop-loss 아님) 우선
        assert s["recent"][0]["ticker"] == "KRW-BTC"
        assert s["recent"][0]["exit_reason_code"] == "signal_sell"


def test_kpi_data_slippage_excludes_paper_trades(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        with Session(web_db.engine()) as db:
            # paper trade — 슬리피지 모집단에서 제외돼야 함
            _seed_trade(db, days_ago=1, pnl_ratio=0.02, pnl_krw=2000)
            db.commit()
        r = client.get("/kpi/data")
        assert r.json()["slippage_kpi"]["measurable_count"] == 0


def test_kpi_page_renders_slippage_section(app_env):
    app = create_app()
    with TestClient(app) as client:
        _login(client)
        r = client.get("/kpi")
        assert r.status_code == 200
        assert "슬리피지" in r.text
